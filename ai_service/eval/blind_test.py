"""블라인드 테스트 — 생성도 채점도 이 코드를 짠 사람(나)이 아니라 LLM이 한다.

문제의식: 지금까지의 골든셋(match_dataset.json)은 내가 코드를 보고 만들었다.
가중치도 그 골든셋으로 스윕해서 정했다. "시험 문제를 낸 사람이 자기 답안도
채점하는" 구조라, 골든셋 점수가 좋다고 실제로 정확하다는 보장이 안 된다.
실제로 지금까지 발견된 진짜 버그 3개는 전부 골든셋이 아니라 사용자가 직접
써보다가 나왔다 — 골든셋이 그 버그들을 하나도 못 잡았다는 뜻이다.

이 스크립트는 그 구조를 깬다:
  1) 생성 — LLM에게 "이 앱이 뭘 하는지"만 알려주고 문장을 쓰게 한다.
     verb_class, margin gate, 반의어 목록 같은 내부 구현/알려진 약점은
     프롬프트에 절대 언급하지 않는다 — 내가 아는 약점을 문제 출제자가
     알면 그건 더 이상 블라인드가 아니다.
  2) 실행 — 실제 운영 코드(decompose + search_for_step_detailed)를 그대로 돌린다.
  3) 채점 — 또 다른 LLM 호출이 "문장과 그림 설명이 뜻이 맞는지"만 본다.
     내부 점수·판정 사유를 안 보여준다 — 순수하게 의미가 맞는지만 판단한다.
  4) 사람 검토 — LLM 채점도 틀릴 수 있으니, 불일치로 나온 것만 사람이
     최종 확인한 뒤 골든셋에 넣는다. 이 스크립트가 골든셋을 자동으로
     고치지는 않는다.

실행:
    cd ai_service
    export OPENAI_API_KEY=...   # 또는 저장소 루트 .env
    python -m eval.blind_test                       # 직무당 4문장(기본)
    python -m eval.blind_test --per-job 8            # 더 많이
    python -m eval.blind_test --job cafe             # 한 직무만
    python -m eval.blind_test --json result.json     # 결과 저장

매번 새 문장을 만들어 API 비용이 들고 결과가 실행마다 달라진다(그게 목적이다 —
같은 골든셋을 반복해서 재는 게 아니라 매번 새로운 케이스로 찔러본다).

로컬에서 저장소 루트 .env를 그대로 로드하면 AAC_DATA_DIR가 도커 전용 경로(/app/aac)로
잡혀 자산 파일을 못 찾는다. 로컬 실행 전에 그 변수는 지워야 한다:
    unset AAC_DATA_DIR   (또는 os.environ.pop('AAC_DATA_DIR', None))
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm  # noqa: E402
from decompose import decompose  # noqa: E402
from local_aac import search_for_step_detailed  # noqa: E402

# 이 앱의 실제 사용 범위(직무 5종)는 제품 사양이지 "내가 아는 약점"이 아니므로
# 생성 프롬프트에 포함해도 블라인드가 깨지지 않는다. 그 외에는 아무것도 안 준다.
_JOBS = {
    "cafe": "카페",
    "cleaning": "청소",
    "packaging": "포장",
    "assembly": "조립",
    "retail": "마트",
}

# 생성자 프롬프트 — 구현 세부사항을 절대 언급하지 않는다. 제품 설명만 준다.
_GENERATOR_SYSTEM = (
    "당신은 실제로 소규모 사업장을 운영하는 사장님입니다. 신입 직원(발달장애가 있어 "
    "짧고 구체적인 문장을 좋아함)에게 오늘 할 일을 자연스러운 말투로 알려주는 앱에 "
    "입력할 문장을 씁니다. 실제 사장님이 말하듯 자연스럽게, 여러 동작을 이어서 "
    "한 문단으로 씁니다(5~7개 동작 정도). 문어체 지시문이 아니라 구어체("
    "'~해주세요', '~하시고요', '~해야 해요')로 씁니다. 매번 다른 상황(마감/오픈/"
    "재고정리/고객응대/특별 요청 등)을 상상해서 새롭게 씁니다.\n"
    "출력은 JSON 하나: {\"scenarios\": [\"문장1\", \"문장2\", ...]}"
)


def generate_scenarios(job_label: str, count: int) -> list[str]:
    user = f"업종: {job_label}. 서로 다른 상황의 직무 지시문을 {count}개 만들어주세요."
    raw = llm.chat_json(_GENERATOR_SYSTEM, user, max_tokens=1200)
    scenarios = raw.get("scenarios") or []
    return [str(s).strip() for s in scenarios if str(s).strip()][:count]


# 채점자 프롬프트 — 내부 점수·판정 사유·후보 개수 같은 건 안 보여준다. 순수하게
# "이 그림 설명이 이 문장이 시키는 동작과 뜻이 맞는가"만 판단하게 한다.
_JUDGE_SYSTEM = (
    "당신은 그림카드가 문장과 맞는지 검수하는 사람입니다. 아래 [지시문]을 실제로 "
    "수행하는 모습을 [그림 설명]이 정확히 보여주는지 판단합니다.\n"
    "- 그림이 지시문과 다른 동작(반대 동작, 관련 없는 동작, 엉뚱한 물건)을 보여주면 "
    "'불일치'.\n"
    "- 그림이 지시문의 핵심 동작·대상을 제대로 보여주면(사소한 표현 차이는 괜찮음) "
    "'일치'.\n"
    "- 애매하면(그럴 수도 있는 정도) '애매'.\n"
    "출력은 JSON 하나: {\"verdict\": \"일치|불일치|애매\", \"reason\": \"한 줄 이유\"}"
)


def judge_match(sentence: str, label: str) -> dict:
    user = f"[지시문] {sentence}\n[그림 설명] {label}"
    try:
        return llm.chat_json(_JUDGE_SYSTEM, user, max_tokens=200)
    except Exception as e:  # noqa: BLE001
        return {"verdict": "오류", "reason": str(e)}


def run_case(job_key: str, job_label: str, sentence: str) -> list[dict]:
    """시나리오 하나를 분해하고 각 단계를 매칭해, 단계별 채점 결과를 낸다."""
    context = {"business_type": job_label, "raw_input": sentence}
    result = decompose(sentence, context)

    rows = []
    for step in result.steps:
        terms = step.symbol_query or [k.term for k in step.keywords]
        ctx = {
            "business_type": job_label,
            "sentence": step.sentence,
            "action_type": step.action_type,
            "raw_input": sentence,
        }
        decision = search_for_step_detailed(terms[:4], ctx)

        if decision["match"]:
            # 자동 채택 — 그 그림 하나만 채점한다.
            label = decision["match"]["label"]
            verdict = judge_match(step.sentence, label)
            rows.append({
                "job": job_key, "scenario": sentence, "step": step.sentence,
                "mode": "accepted", "label": label, **verdict,
            })
        elif decision["candidates"]:
            # 후보 제시 — 상위 3개 중 하나라도 맞으면 '일치'로 본다(사람이 고를 수
            # 있으므로). 셋 다 안 맞으면 recall 실패 — 이것도 블라인드로 잡아야 할
            # 결함이다.
            best = None
            for c in decision["candidates"][:3]:
                v = judge_match(step.sentence, c["label"])
                if best is None or v.get("verdict") == "일치":
                    best = {"label": c["label"], **v}
                if v.get("verdict") == "일치":
                    break
            rows.append({
                "job": job_key, "scenario": sentence, "step": step.sentence,
                "mode": "candidates", **(best or {"verdict": "불일치", "reason": "후보 없음"}),
            })
        else:
            rows.append({
                "job": job_key, "scenario": sentence, "step": step.sentence,
                "mode": "fallback", "label": None, "verdict": "일치",
                "reason": "정직하게 폴백(사진 권장)함 — 오답을 보여주는 것보다 낫다",
            })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="블라인드 테스트 — LLM이 내고 LLM이 채점")
    ap.add_argument("--per-job", type=int, default=4, help="직무당 생성할 시나리오 수")
    ap.add_argument("--job", help="특정 직무만(cafe/cleaning/packaging/assembly/retail)")
    ap.add_argument("--json", help="결과를 JSON으로 저장")
    args = ap.parse_args()

    if not llm.llm_available():
        raise SystemExit("OPENAI_API_KEY가 없습니다 — 생성·채점 둘 다 LLM이 필요합니다.")

    jobs = {args.job: _JOBS[args.job]} if args.job else _JOBS
    all_rows: list[dict] = []

    for job_key, job_label in jobs.items():
        print(f"\n[{job_label}] 시나리오 생성 중...")
        scenarios = generate_scenarios(job_label, args.per_job)
        for i, sentence in enumerate(scenarios, 1):
            print(f"  ({i}/{len(scenarios)}) {sentence[:50]}...")
            all_rows.extend(run_case(job_key, job_label, sentence))

    total = len(all_rows)
    mismatch = [r for r in all_rows if r.get("verdict") == "불일치"]
    ambiguous = [r for r in all_rows if r.get("verdict") == "애매"]
    error = [r for r in all_rows if r.get("verdict") == "오류"]

    print(f"\n{'=' * 78}")
    print(f"총 단계 {total}개 채점 — 불일치 {len(mismatch)} / 애매 {len(ambiguous)} / 오류 {len(error)}")
    print(f"불일치율: {len(mismatch) / total:.1%}" if total else "케이스 없음")
    print("=" * 78)

    if mismatch:
        print("\n[불일치로 판정된 것 — 사람이 최종 확인 필요, 자동으로 골든셋에 넣지 않음]")
        for r in mismatch:
            print(f"  [{r['job']}] {r['step']}")
            print(f"    -> {r.get('label', '(후보 없음)')}  |  {r.get('reason', '')}")

    if args.json:
        Path(args.json).write_text(
            json.dumps({"rows": all_rows, "mismatch_rate": len(mismatch) / total if total else 0},
                      ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n결과 저장: {args.json}")


if __name__ == "__main__":
    main()
