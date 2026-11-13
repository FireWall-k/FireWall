"""GPT 사용량 기록(gpt_usage.py)과 GET /ai/usage. HTTP 층(llm._http.post)만 가짜 — 실제 API는 부르지 않는다."""
import sqlite3
import threading
import types
from datetime import datetime

import pytest

import gpt_usage
import llm


@pytest.fixture
def usage_db(tmp_path, monkeypatch):
    path = tmp_path / "gpt_usage.sqlite3"
    monkeypatch.setenv("GPT_USAGE_DB", str(path))
    monkeypatch.setattr(gpt_usage, "_last_purge", 0.0)
    return path


def _rows(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT kind, model, prompt_tokens, completion_tokens, usd, estimated FROM usage").fetchall()
    finally:
        conn.close()


class _Resp:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


def _fake_http(monkeypatch, body):
    sent = []
    monkeypatch.setattr(llm, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "_http", types.SimpleNamespace(
        post=lambda url, headers=None, json=None, timeout=None: sent.append(json) or _Resp(body)))
    return sent


_CHAT = {"model": "gpt-4o-mini-2024-07-18",
         "usage": {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200},
         "choices": [{"message": {"content": '{"ok": true}'}}]}


# ---------- 단가 ----------
def test_price_by_model_prefix():
    assert gpt_usage.price_for("gpt-4o-mini-2024-07-18") == (0.15, 0.60, False)
    assert gpt_usage.price_for("text-embedding-3-small") == (0.02, 0.0, False)
    # 모르는 모델은 gpt-4o-mini 값으로 셈하고 추정 표시.
    assert gpt_usage.price_for("o9-super") == (0.15, 0.60, True)
    usd, est = gpt_usage.cost_usd("gpt-4o-mini", 1_000_000, 1_000_000)
    assert usd == pytest.approx(0.75) and est is False


# ---------- chat_json·embed_texts가 기록한다 ----------
def test_chat_json_records_usage_without_content(usage_db, monkeypatch):
    _fake_http(monkeypatch, _CHAT)
    assert llm.chat_json("비밀 시스템 문장", "홍길동 근로자 지시문", purpose="rerank") == {"ok": True}
    rows = _rows(usage_db)
    assert len(rows) == 1
    kind, model, p, c, usd, est = rows[0]
    assert (kind, model, p, c, est) == ("rerank", "gpt-4o-mini-2024-07-18", 1000, 200, 0)
    assert usd == pytest.approx((1000 * 0.15 + 200 * 0.60) / 1e6)
    # 개인정보: 파일 어디에도 문장이 없다.
    raw = usage_db.read_bytes()
    assert "홍길동".encode() not in raw and "지시문".encode() not in raw


def test_decompose_and_coaching_pass_their_kind(usage_db, monkeypatch):
    body = dict(_CHAT, choices=[{"message": {"content":
                                             '{"task_title":"t","steps":[{"sentence":"컵을 닦아요.","action_type":"clean"}],'
                                             '"suggestions":[]}'}}])
    _fake_http(monkeypatch, body)
    llm.llm_decompose("컵을 닦아요.", {})
    llm.llm_coaching("t", [{"order": 1, "sentence": "컵을 닦아요."}])
    llm.chat_json("s", "u")  # purpose 없이 부르면 other
    assert [r[0] for r in _rows(usage_db)] == ["decompose", "coaching", "other"]


def test_embed_texts_records_embed_kind(usage_db, monkeypatch):
    _fake_http(monkeypatch, {"model": "text-embedding-3-small", "usage": {"prompt_tokens": 50, "total_tokens": 50},
                             "data": [{"embedding": [1.0, 0.0]}]})
    assert llm.embed_texts(["의자"]) == [[1.0, 0.0]]
    assert _rows(usage_db) == [("embed", "text-embedding-3-small", 50, 0, pytest.approx(50 * 0.02 / 1e6), 0)]


def test_missing_usage_and_model_fall_back(usage_db, monkeypatch):
    """응답에 usage·model이 없어도(가짜 서버 등) 깨지지 않고 0 토큰·설정 모델로 남긴다."""
    _fake_http(monkeypatch, {"choices": [{"message": {"content": "{}"}}]})
    assert llm.chat_json("s", "u", purpose="weird-kind") == {}
    assert _rows(usage_db) == [("other", llm.OPENAI_MODEL, 0, 0, 0.0, 0)]


def test_disabled_when_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("GPT_USAGE_DB", raising=False)
    _fake_http(monkeypatch, _CHAT)
    assert llm.chat_json("s", "u") == {"ok": True}
    assert list(tmp_path.iterdir()) == []
    s = gpt_usage.summary()
    assert s["enabled"] is False and s["calls"] == 0 and len(s["last_7_days"]) == 7


def test_record_failure_never_breaks_request(monkeypatch, tmp_path):
    # 디렉터리를 파일 경로로 주면 sqlite가 열지 못한다 — 요청은 그대로 성공해야 한다.
    monkeypatch.setenv("GPT_USAGE_DB", str(tmp_path))
    _fake_http(monkeypatch, _CHAT)
    assert llm.chat_json("s", "u") == {"ok": True}
    assert gpt_usage.summary()["error"] is True


def test_thread_safe_concurrent_records(usage_db):
    threads = [threading.Thread(target=lambda: [gpt_usage.record("rerank", "gpt-4o-mini", 10, 1) for _ in range(10)])
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(_rows(usage_db)) == 80


# ---------- 합계 ----------
def _ts(y, m, d, h=12):
    return datetime(y, m, d, h, tzinfo=gpt_usage.KST).timestamp()


def test_summary_month_boundary_is_seoul_time(usage_db):
    # 11월 1일 00:30 KST = 10월 31일 15:30 UTC — 한국 시간으로는 11월이다.
    gpt_usage.record("decompose", "gpt-4o-mini", 1000, 100, now=_ts(2026, 11, 1, 0) + 1800)
    gpt_usage.record("decompose", "gpt-4o-mini", 1000, 100, now=_ts(2026, 10, 31, 23))  # 10월
    gpt_usage.record("embed", "text-embedding-3-small", 500, 0, now=_ts(2026, 11, 14, 9))
    s = gpt_usage.summary(now=_ts(2026, 11, 14, 10))
    assert s["month"] == "2026-11"
    assert s["calls"] == 2
    assert s["prompt_tokens"] == 1500 and s["completion_tokens"] == 100
    assert set(s["by_kind"]) == {"decompose", "embed"}
    assert s["by_kind"]["decompose"]["calls"] == 1
    assert s["alert_usd"] == 5.0 and s["over_alert"] is False
    days = s["last_7_days"]
    assert [d["date"] for d in days][0] == "2026-11-08" and days[-1]["date"] == "2026-11-14"
    assert days[-1]["calls"] == 1 and days[0]["calls"] == 0


def test_over_alert_uses_env_threshold(usage_db, monkeypatch):
    monkeypatch.setenv("GPT_MONTHLY_ALERT_USD", "0.5")
    gpt_usage.record("rerank", "gpt-4o-mini", 4_000_000, 0, now=_ts(2026, 11, 3))  # $0.60
    s = gpt_usage.summary(now=_ts(2026, 11, 14))
    assert s["alert_usd"] == 0.5 and s["over_alert"] is True
    assert s["usd"] == pytest.approx(0.6)


def test_retention_deletes_rows_older_than_400_days(usage_db):
    now = _ts(2026, 11, 14)
    gpt_usage.record("other", "gpt-4o-mini", 1, 1, now=now - 401 * 86400)
    gpt_usage._last_purge = 0.0
    gpt_usage.record("other", "gpt-4o-mini", 1, 1, now=now)
    assert len(_rows(usage_db)) == 1


def test_usage_endpoint(usage_db):
    from fastapi.testclient import TestClient

    import main as ai_main

    gpt_usage.record("coaching", "gpt-4o-mini", 100, 10)
    r = TestClient(ai_main.app).get("/ai/usage")
    assert r.status_code == 200
    body = r.json()
    assert body["calls"] == 1 and body["by_kind"]["coaching"]["calls"] == 1
    assert {"month", "usd", "alert_usd", "over_alert", "last_7_days"} <= set(body)
