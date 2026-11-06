"""개인정보 방어 테스트 (Phase 0.2).

백엔드는 근로자 실명을 별칭으로 바꾸고 메모는 허용·동의가 있을 때만 보낸다. 그래도 하네스 쪽에서
한 번 더 막는다 — 호출하는 쪽이 실수로 이름 필드를 넣어도 해외 LLM 프롬프트에는 들어가지 않아야 한다.
OpenAI 호출(chat_json)은 목으로 대체해 실제 프롬프트 문자열을 스냅샷으로 확인한다.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import llm  # noqa: E402
import main as ai_main  # noqa: E402

_NAME = "김민지"
_NOTE = "소리에 민감함"


@pytest.fixture()
def prompts(monkeypatch):
    sent: list[tuple[str, str]] = []

    def fake_chat_json(system, user, **kw):
        sent.append((system, user))
        if "수행 데이터" in user:
            return {"summary": "요약", "suggestions": []}
        return {"task_title": "직무", "steps": [{"sentence": "상자를 옮기세요.", "action_type": "move"}]}

    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", fake_chat_json)
    return sent


def _coaching_body(**extra):
    body = {
        "task_title": "근로자 A 분류 작업",
        "steps": [{"order": 1, "sentence": "근로자 A 씨는 상자를 옮기세요.", "stuck": True,
                   "replay_count": 4, "duration_sec": 150, "action_type": "move",
                   # 스키마에 없는 이름 필드 — 버려져야 한다
                   "worker_name": _NAME}],
        "context": {"business_type": "물류", "worker_name": _NAME, "display_name": _NAME,
                    "name": _NAME, "worker": {"name": _NAME}},
    }
    body.update(extra)
    return body


def test_coaching_prompt_snapshot_drops_name_fields(prompts):
    r = TestClient(ai_main.app).post("/ai/coaching", json=_coaching_body())
    assert r.status_code == 200, r.text
    (_, user), = prompts
    assert _NAME not in user
    payload = json.loads(user.split("\n", 1)[1])
    assert payload == {
        "task_title": "근로자 A 분류 작업",
        "context": {"business_type": "물류"},
        "steps": [{"order": 1, "sentence": "근로자 A 씨는 상자를 옮기세요.", "completed": False,
                   "stuck": True, "replay_count": 4, "duration_sec": 150.0, "action_type": "move"}],
    }


def test_coaching_note_only_when_backend_sends_it(prompts):
    client = TestClient(ai_main.app)
    client.post("/ai/coaching", json=_coaching_body())
    assert _NOTE not in prompts[-1][1]
    body = _coaching_body()
    body["context"]["worker_note"] = _NOTE
    client.post("/ai/coaching", json=body)
    assert json.loads(prompts[-1][1].split("\n", 1)[1])["context"]["worker_note"] == _NOTE


def test_coaching_allow_llm_false_never_calls_llm(prompts):
    r = TestClient(ai_main.app).post("/ai/coaching", json=_coaching_body(allow_llm=False))
    assert r.status_code == 200
    assert prompts == []
    # 규칙 기반 폴백은 그대로 동작한다(막힘 단계 제안).
    assert [s["order"] for s in r.json()["suggestions"]] == [1]


def test_llm_coaching_filters_fields_even_when_called_directly(prompts):
    llm.llm_coaching("t", [{"order": 1, "sentence": "s", "worker_name": _NAME}],
                     {"display_name": _NAME, "job": "logistics"})
    (_, user), = prompts
    assert _NAME not in user


def test_decompose_prompt_snapshot_drops_name_fields(prompts):
    r = TestClient(ai_main.app).post("/ai/decompose", json={
        "raw_input": "근로자 A 씨는 상자를 옮기세요.",
        "context": {"business_type": "물류", "work_environment": "창고",
                    "worker_name": _NAME, "display_name": _NAME},
    })
    assert r.status_code == 200, r.text
    (_, user), = prompts
    assert user == "직무 지시문:\n근로자 A 씨는 상자를 옮기세요.\n업종: 물류\n작업 환경: 창고"


def test_decompose_note_appears_only_when_sent(prompts):
    TestClient(ai_main.app).post("/ai/decompose", json={
        "raw_input": "상자를 옮기세요.", "context": {"worker_note": _NOTE}})
    assert prompts[-1][1].endswith(f"근로자 특성(개별화 참고): {_NOTE}")


def test_decompose_log_does_not_contain_raw_input(prompts, caplog):
    caplog.set_level("INFO", logger="ai_harness")
    TestClient(ai_main.app).post("/ai/decompose", json={"raw_input": f"{_NAME} 씨는 상자를 옮기세요."})
    assert _NAME not in caplog.text
