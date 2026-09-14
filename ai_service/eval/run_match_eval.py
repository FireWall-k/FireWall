"""AAC 이미지 매칭 평가 하네스 (점수판).

`run_eval.py`가 '문장을 잘 나눴는가'를 재는 것과 짝을 이뤄, 이 스크립트는
'그 문장에 맞는 그림을 골랐는가'를 잰다. 매칭 스코어러(`local_aac.py`)를 고칠 때마다
돌려서 개선/회귀를 숫자로 확인한다.

실행:
    cd ai_service
    python -m eval.run_match_eval                  # 전체 채점(LLM 경로)
    python -m eval.run_match_eval --query-mode sentence  # 규칙 폴백 경로
    python -m eval.run_match_eval --case cafe_sweep    # 특정 케이스만
    python -m eval.run_match_eval --job cleaning       # 특정 직무만
    python -m eval.run_match_eval --verbose            # 케이스별 상위 후보까지 출력
    python -m eval.run_match_eval --json before.json   # 스코어러 수정 전/후 비교용

네트워크·LLM을 쓰지 않는다. `local_aac.search_assets`와 `search_for_step`만 호출하므로
API 키 없이 항상 같은 결과가 나온다(결정적).

두 가지 질의 모드 — 둘 다 프로덕션에 실제로 존재하는 경로다:
    full      문장 + symbol_query (LLM 분해가 성공한 경우). 기본값.
    sentence  문장만 (LLM 키가 없거나 실패해 규칙 폴백으로 떨어진 경우).
              symbol_query가 없으므로 점수 하한선을 보여준다.

지표:
    top1_accuracy   1순위가 정답 집합에 있는 비율 (일반 케이스)
    recall@3        상위 3개 안에 정답이 있는 비율 → 사람에게 후보를 보여줄 때의 상한
    recall@N        상위 N개 안에 정답이 있는 비율 → 리랭커를 붙였을 때의 상한
    wrong_accept    정답이 아닌데 자동 채택한 비율 ← 가장 중요. 현장에 오답 카드가 나가는 비율
    gap_declined    정답 자산이 없는 케이스를 올바르게 거절한 비율
    handoff         자동 채택하지 않고 넘긴 비율(사람 확인 필요) — 너무 높으면 실용성 저하

정답 집합은 `group_id`로 자동 확장된다. 같은 행동의 변형 이미지(ASSEMBLY_031_01~04)는
어느 것이 나와도 정답으로 친다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# tests/ 와 동일한 경로 주입(ai_service를 import 루트로).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from local_aac import load_assets, search_assets, search_for_step_detailed  # noqa: E402

DATASET_PATH = Path(__file__).with_name("match_dataset.json")


# --- 정답 집합 확장 -----------------------------------------------------------

def _group_index() -> tuple[dict[str, str], dict[str, list[str]]]:
    """asset_id -> group_id, group_id -> [asset_id] 인덱스."""
    id_to_group: dict[str, str] = {}
    group_to_ids: dict[str, list[str]] = {}
    for asset in load_assets():
        gid = asset.get("group_id") or asset["id"]
        id_to_group[asset["id"]] = gid
        group_to_ids.setdefault(gid, []).append(asset["id"])
    return id_to_group, group_to_ids


def _expand_accept(accept: list[str], id_to_group: dict, group_to_ids: dict) -> set[str]:
    """정답 id를 같은 group_id의 모든 변형으로 확장한다."""
    expanded: set[str] = set()
    for asset_id in accept:
        gid = id_to_group.get(asset_id)
        if gid is None:
            raise SystemExit(f"정답셋에 없는 asset_id: {asset_id}")
        expanded.update(group_to_ids[gid])
    return expanded


# --- 케이스 실행 --------------------------------------------------------------

def eval_case(case: dict, accept: set[str], recall_depth: int, shortlist: int,
              query_mode: str = "full") -> dict:
    """한 케이스를 실행해 순위·판정 결과를 낸다.

    프로덕션 경로와 동일하게 문장을 context['sentence']에, action_type을
    context['action_type']에 넣고 symbol_query를 키워드로 넘긴다
    (backend/main.py의 _pick_symbol과 같은 형태).
    query_mode='sentence'면 symbol_query를 비워 규칙 폴백 경로를 재현한다.
    """
    ctx = dict(case.get("context") or {})
    ctx["sentence"] = case["sentence"]
    ctx["action_type"] = case.get("action_type", "other")
    keywords = list(case.get("symbol_query") or []) if query_mode == "full" else []

    ranked = search_assets(" ".join([case["sentence"], *keywords]), ctx, limit=recall_depth)
    ranked_ids = [r["asset_id"] for r in ranked]

    # 실제 채택 판정은 프로덕션과 같은 함수를 쓴다.
    decision = search_for_step_detailed(keywords, ctx)
    chosen = decision["match"]

    is_gap = bool(case.get("gap"))
    top1_hit = bool(ranked_ids) and ranked_ids[0] in accept
    accepted = chosen is not None
    accepted_hit = accepted and chosen["asset_id"] in accept

    return {
        "id": case["id"],
        "job": case.get("job", ""),
        "gap": is_gap,
        "sentence": case["sentence"],
        "reason": decision["reason"],
        "top1_hit": top1_hit,
        "in_shortlist": any(i in accept for i in ranked_ids[:shortlist]),
        "in_recall": any(i in accept for i in ranked_ids[:recall_depth]),
        "accepted": accepted,
        # 오답 채택: 채택했는데 정답이 아님(갭 케이스는 무엇을 채택하든 오답).
        "wrong_accept": accepted and not accepted_hit,
        "top_score": round(ranked[0]["score"], 4) if ranked else 0.0,
        "margin": round(ranked[0]["score"] - ranked[1]["score"], 4) if len(ranked) > 1 else 0.0,
        "top_label": ranked[0]["label"] if ranked else "",
        "top_id": ranked_ids[0] if ranked_ids else "",
        "candidates": [
            {"id": r["asset_id"], "label": r["label"], "score": round(r["score"], 4),
             "hit": r["asset_id"] in accept}
            for r in ranked[:shortlist]
        ],
    }


def _rate(num: int, den: int) -> float:
    return round(num / den, 3) if den else 0.0


def run(only_case: str | None = None, only_job: str | None = None,
        query_mode: str = "full") -> dict:
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    decision = data.get("decision", {})
    recall_depth = int(decision.get("recall_depth", 20))
    shortlist = int(decision.get("shortlist_depth", 3))

    cases = data["cases"]
    if only_case:
        cases = [c for c in cases if c["id"] == only_case]
    if only_job:
        cases = [c for c in cases if c.get("job") == only_job]
    if not cases:
        raise SystemExit("조건에 맞는 케이스가 없습니다.")

    id_to_group, group_to_ids = _group_index()

    rows = []
    for case in cases:
        accept = _expand_accept(case.get("accept", []), id_to_group, group_to_ids)
        rows.append(eval_case(case, accept, recall_depth, shortlist, query_mode))

    normal = [r for r in rows if not r["gap"]]
    gaps = [r for r in rows if r["gap"]]

    metrics = {
        "top1_accuracy": _rate(sum(r["top1_hit"] for r in normal), len(normal)),
        f"recall@{shortlist}": _rate(sum(r["in_shortlist"] for r in normal), len(normal)),
        f"recall@{recall_depth}": _rate(sum(r["in_recall"] for r in normal), len(normal)),
        "wrong_accept_rate": _rate(sum(r["wrong_accept"] for r in rows), len(rows)),
        "gap_declined_rate": _rate(sum(not r["accepted"] for r in gaps), len(gaps)),
        "handoff_rate": _rate(sum(not r["accepted"] for r in rows), len(rows)),
    }

    # 거절 사유 분포. low_score는 폴백으로, low_margin은 후보를 보여주고
    # 사람이 고르게 하는 경로다 — 검토 화면에서 다르게 다뤄야 하므로 따로 센다.
    reasons: dict[str, int] = {}
    for row in rows:
        reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1

    return {
        "query_mode": query_mode,
        "threshold": float(os.getenv("AAC_MATCH_THRESHOLD", "0.22")),
        "min_margin": float(os.getenv("AAC_MATCH_MIN_MARGIN", "0.02")),
        "n_cases": len(rows),
        "n_normal": len(normal),
        "n_gap": len(gaps),
        "metrics": metrics,
        "reasons": reasons,
        "cases": rows,
    }


# --- 출력 --------------------------------------------------------------------

def _print_report(report: dict, verbose: bool) -> None:
    m = report["metrics"]
    mode_label = {"full": "문장+symbol_query (LLM 경로)",
                  "sentence": "문장만 (규칙 폴백 경로)"}[report["query_mode"]]
    print(f"\n매칭 평가 — 케이스 {report['n_cases']}개"
          f"(일반 {report['n_normal']} / 커버리지갭 {report['n_gap']}), "
          f"채택 기준 점수≥{report['threshold']} 및 여유≥{report['min_margin']}")
    print(f"질의 모드: {mode_label}")
    print("=" * 78)
    for key, value in m.items():
        bar = "#" * int(value * 30)
        flag = ""
        if key == "wrong_accept_rate":
            flag = "  <-- 낮을수록 좋음(현장 오답 카드 비율)"
        print(f"  {key:<18} {value:>6.3f}  {bar}{flag}")
    print("-" * 78)
    desc = {"accepted": "자동 채택", "no_candidate": "후보 없음 → 폴백",
            "low_score": "점수 미달 → 폴백", "low_margin": "후보 경합 → 사람이 선택"}
    for reason, count in sorted(report["reasons"].items(), key=lambda kv: -kv[1]):
        print(f"  {desc.get(reason, reason):<24} {count:>3}건")
    print("=" * 78)

    fails = [r for r in report["cases"] if not r["gap"] and not r["top1_hit"]]
    if fails:
        print(f"\n[1순위 오답 {len(fails)}건]")
        print(f"  {'케이스':<22}{'점수':>6}{'여유':>7}  {'채택':<5} 1순위 결과")
        print("  " + "-" * 74)
        for r in sorted(fails, key=lambda x: -x["top_score"]):
            mark = "채택!" if r["accepted"] else "거절"
            hint = " (상위3위내 정답있음)" if r["in_shortlist"] else ""
            print(f"  {r['id']:<22}{r['top_score']:>6.3f}{r['margin']:>7.3f}  {mark:<5} "
                  f"{r['top_label']}{hint}")

    bad_gaps = [r for r in report["cases"] if r["gap"] and r["accepted"]]
    if bad_gaps:
        print(f"\n[커버리지 갭인데 오답 채택 {len(bad_gaps)}건]")
        for r in bad_gaps:
            print(f"  {r['id']:<22}{r['top_score']:>6.3f}        -> {r['top_label']}")

    if verbose:
        print("\n[전체 케이스 상위 후보]")
        for r in report["cases"]:
            status = "GAP" if r["gap"] else ("OK " if r["top1_hit"] else "MISS")
            print(f"\n  {status} {r['id']} — {r['sentence']}")
            for c in r["candidates"]:
                mark = "*" if c["hit"] else " "
                print(f"      {mark} {c['score']:.3f}  {c['label']}")
    print()


def _memoize_retrieval():
    """스윕 동안 검색 결과를 재사용한다.

    검색 순위는 임계값과 무관한데(임계값은 '채택할지'만 정한다) 임계값마다 401개 자산을
    다시 채점하면 스윕이 16배 느려진다. 프로덕션 코드는 건드리지 않고 모듈 속성만
    잠시 감싼다. 복원 함수를 돌려준다.
    """
    import local_aac

    original = local_aac.search_assets
    cache: dict[tuple, list[dict]] = {}

    def cached(query: str, context: dict | None = None, limit: int = 5) -> list[dict]:
        key = (query, json.dumps(context or {}, sort_keys=True, ensure_ascii=False), limit)
        if key not in cache:
            cache[key] = original(query, context, limit)
        return cache[key]

    local_aac.search_assets = cached
    # search_for_step은 같은 모듈 전역을 보므로 위 교체만으로 함께 적용된다.
    # 이 모듈이 import 시점에 바인딩한 이름도 바꿔준다.
    globals()["search_assets"] = cached

    def restore() -> None:
        local_aac.search_assets = original
        globals()["search_assets"] = original

    return restore


def sweep(query_mode: str, thresholds: list[float],
          margins: list[float] | None = None) -> list[dict]:
    """채택 기준을 바꿔가며 오답채택 / 사람확인 절충 곡선을 낸다.

    margins를 주면 (임계값 × 여유) 2차원으로 돌린다. 스코어러를 고치면 점수 척도가
    바뀌므로 두 값 모두 재교정해야 한다. 눈대중으로 숫자를 찍지 말고 곡선을 보고
    운영점을 고른다.
    """
    saved = {k: os.environ.get(k)
             for k in ("AAC_MATCH_THRESHOLD", "AAC_MATCH_MIN_MARGIN")}
    restore = _memoize_retrieval()
    rows = []
    try:
        for t in thresholds:
            for mg in (margins if margins is not None else [None]):
                os.environ["AAC_MATCH_THRESHOLD"] = str(t)
                if mg is not None:
                    os.environ["AAC_MATCH_MIN_MARGIN"] = str(mg)
                report = run(query_mode=query_mode)
                row = {"threshold": t, **report["metrics"]}
                if mg is not None:
                    row = {"threshold": t, "margin": mg, **report["metrics"]}
                rows.append(row)
    finally:
        restore()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return rows


def _print_sweep(rows: list[dict], query_mode: str) -> None:
    has_margin = "margin" in rows[0]
    label = "임계값 × 여유" if has_margin else "임계값"
    width = 80 if has_margin else 72
    print(f"\n{label} 스윕 — 질의 모드 {query_mode}")
    print("=" * width)
    head = f"{'임계값':>7}"
    if has_margin:
        head += f"{'여유':>7}"
    print(head + f"{'오답채택':>10}{'사람확인':>10}{'갭거절':>9}{'top1':>8}   판정")
    print("-" * width)
    for r in rows:
        # 오답을 현장에 내보내지 않으면서 사람 확인이 과하지 않은 구간을 표시한다.
        note = ""
        if r["wrong_accept_rate"] <= 0.02 and r["handoff_rate"] <= 0.25:
            note = "<- 권장 구간"
        line = f"{r['threshold']:>7.2f}"
        if has_margin:
            line += f"{r['margin']:>7.3f}"
        print(line + f"{r['wrong_accept_rate']:>10.3f}"
              f"{r['handoff_rate']:>10.3f}{r['gap_declined_rate']:>9.3f}"
              f"{r['top1_accuracy']:>8.3f}   {note}")
    print("=" * width)
    print("오답채택↓ 사람확인↓ 갭거절↑ 가 동시에 좋을 수는 없다. 오답채택을 먼저 누르고,")
    print("그 다음 사람확인이 견딜 만한 가장 낮은 기준을 고른다.\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="AAC 이미지 매칭 평가 하네스")
    ap.add_argument("--case", help="특정 케이스 id만 채점")
    ap.add_argument("--job", help="특정 직무만 채점 (cafe/cleaning/packaging/retail/assembly)")
    ap.add_argument("--query-mode", choices=["full", "sentence"], default="full",
                    help="full=문장+symbol_query(LLM 경로), sentence=문장만(규칙 폴백 경로)")
    ap.add_argument("--verbose", action="store_true", help="케이스별 상위 후보 출력")
    ap.add_argument("--sweep", action="store_true",
                    help="채택 임계값을 바꿔가며 오답채택/사람확인 절충 곡선 출력")
    ap.add_argument("--sweep-margin", action="store_true",
                    help="임계값 × 여유(margin) 2차원 스윕")
    ap.add_argument("--json", help="결과를 JSON 파일로 저장(수정 전/후 비교용)")
    args = ap.parse_args()

    if args.sweep or args.sweep_margin:
        if args.sweep_margin:
            thresholds = [round(0.14 + 0.02 * i, 2) for i in range(5)]
            margins = [0.0, 0.005, 0.01, 0.02, 0.03, 0.05]
        else:
            thresholds = [round(0.10 + 0.02 * i, 2) for i in range(16)]
            margins = None
        rows = sweep(args.query_mode, thresholds, margins)
        _print_sweep(rows, args.query_mode)
        if args.json:
            Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"결과 저장: {args.json}")
        return

    report = run(args.case, args.job, args.query_mode)
    _print_report(report, args.verbose)
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"결과 저장: {args.json}")


if __name__ == "__main__":
    main()
