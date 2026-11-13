"""설정 화면 'AI 사용량 (이번 달)' — GET /api/workplace/ai-usage.

지키는 것: 사업주만 본다, 하네스 응답을 같은 모양으로 옮긴다, 하네스에 닿지 못하면 500이 아니라 available=False.
실제 AI 하네스·OpenAI는 부르지 않는다(ai_client.ai_usage를 가짜로 바꾼다).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

import ai_client  # noqa: E402
from conftest import auth  # noqa: E402

PATH = "/api/workplace/ai-usage"
# conftest의 autouse 가짜는 시험마다 붙는다 — 모듈을 읽을 때는 아직 원래 함수다.
_REAL_AI_USAGE = ai_client.ai_usage

_USAGE = {
    "enabled": True, "month": "2026-11", "calls": 12, "prompt_tokens": 9000, "completion_tokens": 800,
    "usd": 6.25, "by_kind": {"decompose": {"calls": 2, "usd": 0.001}, "rerank": {"calls": 10, "usd": 6.249}},
    "alert_usd": 5.0, "over_alert": True,
    "last_7_days": [{"date": f"2026-11-{d:02d}", "calls": 0, "usd": 0.0} for d in range(8, 15)],
}


def test_requires_employer(client, worker_token):
    assert client.get(PATH).status_code == 401
    assert client.get(PATH, headers=auth(worker_token)).status_code == 403


def test_passes_through_harness_summary(client, employer_token, monkeypatch):
    monkeypatch.setattr(ai_client, "ai_usage", lambda: dict(_USAGE))
    r = client.get(PATH, headers=auth(employer_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True
    assert body["month"] == "2026-11" and body["calls"] == 12 and body["usd"] == 6.25
    assert body["over_alert"] is True and body["alert_usd"] == 5.0
    assert body["by_kind"]["rerank"] == {"calls": 10, "usd": 6.249}
    assert len(body["last_7_days"]) == 7


def test_unavailable_when_harness_down(client, employer_token):
    # conftest 기본: ai_usage → None(하네스에 닿지 못함).
    r = client.get(PATH, headers=auth(employer_token))
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False and body["calls"] == 0 and body["over_alert"] is False


def test_unavailable_when_harness_returns_garbage(client, employer_token, monkeypatch):
    monkeypatch.setattr(ai_client, "ai_usage", lambda: {"calls": "많이", "last_7_days": "x"})
    body = client.get(PATH, headers=auth(employer_token)).json()
    assert body["available"] is False


def test_ai_client_returns_none_on_connection_error(monkeypatch):
    """실제 ai_client.ai_usage: 연결 실패·오류 응답이면 예외 대신 None."""
    real = _REAL_AI_USAGE

    def boom(*a, **kw):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(ai_client._http, "get", boom)
    assert real() is None

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return dict(_USAGE)

    monkeypatch.setattr(ai_client._http, "get", lambda url, timeout=None: _Resp())
    assert real()["calls"] == 12
