"""ai_service 실제 분해 응답을 기록한 고정값으로 백엔드 나누기 미리보기를 확인한다(네트워크 없음).

fixtures/ai_decompose_recorded.json은 실제 ai_service(/ai/decompose)가 돌려준 JSON 그대로다 — GPT 단계는
기록된 gpt-4o-mini 응답(새 분해 프롬프트), 규칙 단계는 GPT가 실패해 규칙으로 떨어진 경우다. 손으로 만든 목이
아니라 진짜 응답 모양에서 split_group·split_check·source_text가 사라지지 않고 화면까지 가는지 본다.
"""
import json
from pathlib import Path

import pytest

import ai_client
from conftest import auth

_RECORDED = json.loads((Path(__file__).parent / "fixtures" / "ai_decompose_recorded.json")
                       .read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(_RECORDED))
def test_split_preview_passes_real_ai_fields_through(name, client, employer_token, monkeypatch):
    case = _RECORDED[name]
    monkeypatch.setattr(ai_client, "decompose", lambda raw_input, context=None: case["response"])
    r = client.post("/api/tasks/split-preview", headers=auth(employer_token),
                    json={"raw_input": case["raw_input"]})
    assert r.status_code == 200, r.text
    got = r.json()["steps"]
    want = case["response"]["steps"]
    assert [s["sentence"] for s in got] == [s["sentence"] for s in want]
    for g, w in zip(got, want):
        assert g["split_group"] == w["split_group"]
        assert g["split_check"] == w["split_check"]
        assert g["source_text"] == w["source_text"]


def test_recorded_cases_cover_the_contract():
    # 고정값이 세 칸의 모든 경우(나눔·확실, 나눔·애매, 안 나눔)를 담고 있어야 위 테스트가 뜻이 있다.
    steps = [s for c in _RECORDED.values() for s in c["response"]["steps"]]
    assert any(s["split_group"] is not None and not s["split_check"] for s in steps)
    assert any(s["split_group"] is not None and s["split_check"] for s in steps)
    assert any(s["split_group"] is None and s["source_text"] is None for s in steps)
    three = _RECORDED["gpt_three_actions"]["response"]["steps"]
    assert len(three) == 3 and len({s["source_text"] for s in three}) == 1
