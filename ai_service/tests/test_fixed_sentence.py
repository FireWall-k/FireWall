"""2b-1 시연·클릭 수 시험용 고정 문장(규칙 엔진만, GPT·임베딩 없음).

이 문장을 입력 화면에 붙여 넣으면 규칙 나누기로 6단계가 되고, 단계마다 규칙 그림 매칭이 자동 채택(accepted)한다
→ 백엔드 picture_state는 6단계 모두 auto_high다. 1단계('커터칼로 …')는 조심 낱말(칼)이 있어 '✦ 자동 제안' 조심 표시가
켜진다(근로자 화면 조심 띠 시연). 모든 단계가 '~해요' 체이고 20자 이하라 문장 점검 경고가 없다.

- 사업주 클릭 수 시험(employer-clicks.spec, e2e-real/clicks-real.spec)과 창업자 시연 대본이 이 문장을 쓴다.
- 백엔드 시험(test_editor.py::test_fixed_sentence_six_auto_high)은 이 엔진의 실제 응답을 기록한 고정값
  (backend/tests/fixtures/fixed_sentence_rule_recorded.json)으로 같은 흐름을 서버 끝까지 돌린다. 규칙이 바뀌어
  기록과 달라지면 아래 test_recorded_fixture_is_current가 깨진다 — 그때는 이 파일을 직접 실행해 다시 기록한다:
    env -u OPENAI_API_KEY -u OPENAI_API_KEY_FILE python ai_service/tests/test_fixed_sentence.py
"""
import json
import os
import sys
from pathlib import Path

os.environ["AAC_EMBEDDINGS"] = "off"
os.environ["AAC_LLM_RERANK"] = "off"
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("OPENAI_API_KEY_FILE", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm  # noqa: E402
from decompose import decompose  # noqa: E402
from symbols import map_symbols  # noqa: E402

FIXED_SENTENCE = "커터칼로 상자를 열어요. 상품을 선반에 놓아요. 같은 상품끼리 모아요. 테이블을 행주로 닦아요. 바닥을 빗자루로 쓸어요. 손을 씻어요."

FIXTURE = (Path(__file__).resolve().parents[2] / "backend" / "tests" / "fixtures"
           / "fixed_sentence_rule_recorded.json")


def _symbol_context(raw: str, job: str, step) -> dict:
    # 백엔드 create_task의 _pick_symbol 맥락과 같다(업종을 적지 않은 직무: job은 비우고 추정 직무는 job_hint).
    return {"business_type": "", "work_environment": "", "raw_input": raw, "job": "", "job_hint": job,
            "sentence": step.sentence, "action_type": step.action_type}


def run_rule_engine(raw: str = FIXED_SENTENCE) -> dict:
    assert not llm.llm_available(), "규칙 엔진만으로 돌려야 한다(GPT 키 없음)"
    context = {"business_type": "", "work_environment": "", "worker_note": "", "raw_input": raw}
    result = decompose(raw, context)
    job = result.job or ""
    symbols = {}
    for step in result.steps:
        terms = (step.symbol_query or [k.term for k in step.keywords])[:4] or [step.sentence[:12]]
        symbols[step.sentence] = {"keywords": terms,
                                  "result": map_symbols(terms, _symbol_context(raw, job, step)).model_dump()}
    return {"raw_input": raw, "decompose": result.model_dump(), "map_symbols": symbols}


def test_fixed_sentence_six_auto_high():
    rec = run_rule_engine()
    steps = rec["decompose"]["steps"]
    assert len(steps) == 6
    for step in steps:
        sym = rec["map_symbols"][step["sentence"]]["result"]["symbols"][0]
        assert sym["reason"] == "accepted" and sym["needs_fallback"] is False and sym["image_url"], step
        assert sym["decided_by"] == "rule"
    assert "칼" in steps[0]["sentence"]


def test_recorded_fixture_is_current():
    """백엔드 시험이 쓰는 기록이 지금 규칙 엔진 결과와 같다(규칙이 바뀌면 다시 기록)."""
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert recorded == json.loads(json.dumps(run_rule_engine(), ensure_ascii=False))


if __name__ == "__main__":
    FIXTURE.write_text(json.dumps(run_rule_engine(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"기록함: {FIXTURE}")
