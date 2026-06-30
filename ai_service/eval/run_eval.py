"""직무 분해 평가 하네스 (점수판).

프롬프트를 바꿀 때마다 이 스크립트를 돌려 분해 품질을 '점수'로 확인한다.
눈대중 대신 정량으로 개선/회귀를 잡는 것이 목적이다(하네스 4원칙 중 검증·관측).

실행:
    cd ai_service
    python -m eval.run_eval                # dataset.json 전체 채점
    python -m eval.run_eval --case cafe_close   # 특정 케이스만
    python -m eval.run_eval --json result.json  # 점수를 JSON으로 저장(전후 비교용)

동작 모드:
    - OPENAI_API_KEY가 있으면 → LLM 분해를 실제로 채점(프롬프트 개선 효과 측정).
    - 없으면 → 규칙 기반 폴백을 채점. symbol_query가 비어 LLM 전용 지표는 낮게 나오며,
      이는 'LLM+프롬프트가 왜 필요한지'를 그대로 보여준다(폴백은 점수 하한선).

채점 기준(rubric) — dataset.json의 rubric_weights로 가중치 조절:
    steps_in_range      기대 단계 수 범위 안에 있는가
    sentence_brevity    문장이 권장 글자수(기본 20자) 이내인 비율
    imperative_ending   명령형('~요/~세요/~다')으로 끝나는 비율
    symbol_query_quality 각 단계 symbol_query에 한글+영어가 함께 있는 비율(LLM 지표)
    action_typed        action_type이 'other'가 아닌(구체 분류된) 비율
    keyword_coverage    기대 키워드가 결과에 등장하는 비율
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# tests/ 와 동일한 경로 주입(ai_service를 import 루트로).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm  # noqa: E402
from decompose import decompose  # noqa: E402
from schemas import DecomposeResult  # noqa: E402

DATASET_PATH = Path(__file__).with_name("dataset.json")

_HANGUL = re.compile(r"[가-힣]")
_ENGLISH = re.compile(r"[A-Za-z]")
_IMPERATIVE_END = ("요", "요.", "세요", "세요.", "다", "다.")


# --- 개별 지표(각 0.0~1.0) --------------------------------------------------

def _m_steps_in_range(result: DecomposeResult, expect: dict) -> float:
    lo = expect.get("min_steps", 1)
    hi = expect.get("max_steps", 10)
    return 1.0 if lo <= len(result.steps) <= hi else 0.0


def _m_sentence_brevity(result: DecomposeResult, max_chars: int) -> float:
    if not result.steps:
        return 0.0
    ok = sum(1 for s in result.steps if len(s.sentence.strip()) <= max_chars)
    return ok / len(result.steps)


def _m_imperative_ending(result: DecomposeResult) -> float:
    if not result.steps:
        return 0.0
    ok = sum(1 for s in result.steps if s.sentence.strip().endswith(_IMPERATIVE_END))
    return ok / len(result.steps)


def _m_symbol_query_quality(result: DecomposeResult) -> float:
    """각 단계 symbol_query에 한글 토큰과 영어 토큰이 모두 있으면 1점."""
    if not result.steps:
        return 0.0
    good = 0
    for s in result.steps:
        q = " ".join(s.symbol_query)
        if s.symbol_query and _HANGUL.search(q) and _ENGLISH.search(q):
            good += 1
    return good / len(result.steps)


def _m_action_typed(result: DecomposeResult) -> float:
    if not result.steps:
        return 0.0
    ok = sum(1 for s in result.steps if s.action_type != "other")
    return ok / len(result.steps)


def _m_keyword_coverage(result: DecomposeResult, expect: dict) -> float:
    must = expect.get("must_have_keywords", [])
    if not must:
        return 1.0
    blob = " ".join(
        [result.task_title]
        + [s.sentence for s in result.steps]
        + [t for s in result.steps for t in s.symbol_query]
        + [k.term for s in result.steps for k in s.keywords]
    )
    found = sum(1 for kw in must if kw in blob)
    return found / len(must)


def score_case(result: DecomposeResult, case: dict, weights: dict, max_chars: int) -> dict:
    metrics = {
        "steps_in_range": _m_steps_in_range(result, case["expect"]),
        "sentence_brevity": _m_sentence_brevity(result, max_chars),
        "imperative_ending": _m_imperative_ending(result),
        "symbol_query_quality": _m_symbol_query_quality(result),
        "action_typed": _m_action_typed(result),
        "keyword_coverage": _m_keyword_coverage(result, case["expect"]),
    }
    total_w = sum(weights.get(k, 1.0) for k in metrics)
    weighted = sum(metrics[k] * weights.get(k, 1.0) for k in metrics)
    score = round(100 * weighted / total_w, 1) if total_w else 0.0
    return {"id": case["id"], "score": score, "n_steps": len(result.steps), "metrics": metrics}


# --- 실행 --------------------------------------------------------------------

def run(only_case: str | None = None) -> dict:
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    weights = data.get("rubric_weights", {})
    max_chars = data.get("brevity_max_chars", 20)
    cases = data["cases"]
    if only_case:
        cases = [c for c in cases if c["id"] == only_case]
        if not cases:
            raise SystemExit(f"케이스를 찾지 못했습니다: {only_case}")

    mode = "LLM" if llm.llm_available() else "규칙기반 폴백(LLM 키 없음)"
    rows = []
    for case in cases:
        result = decompose(case["raw_input"], case.get("context", {}))
        rows.append(score_case(result, case, weights, max_chars))

    total = round(sum(r["score"] for r in rows) / len(rows), 1) if rows else 0.0
    return {"mode": mode, "total": total, "cases": rows}


def _print_report(report: dict) -> None:
    print(f"\n분해 모드: {report['mode']}")
    print("=" * 72)
    print(f"{'케이스':<20}{'점수':>7}{'단계':>5}   세부(범위/간결/명령/심볼/동작/키워드)")
    print("-" * 72)
    for r in report["cases"]:
        m = r["metrics"]
        detail = "/".join(f"{m[k]:.2f}" for k in
                          ["steps_in_range", "sentence_brevity", "imperative_ending",
                           "symbol_query_quality", "action_typed", "keyword_coverage"])
        print(f"{r['id']:<20}{r['score']:>6.1f}{r['n_steps']:>5}   {detail}")
    print("-" * 72)
    print(f"{'총점(평균)':<20}{report['total']:>6.1f}")
    print("=" * 72)


def main() -> None:
    ap = argparse.ArgumentParser(description="직무 분해 평가 하네스")
    ap.add_argument("--case", help="특정 케이스 id만 채점")
    ap.add_argument("--json", help="결과를 JSON 파일로 저장(프롬프트 전후 비교용)")
    args = ap.parse_args()

    report = run(args.case)
    _print_report(report)
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"결과 저장: {args.json}")


if __name__ == "__main__":
    main()
