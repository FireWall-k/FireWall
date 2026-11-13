"""GPT 사용량 기록(운영 비용 보기).

llm.py의 chat_json()·embed_texts()가 OpenAI 응답을 받을 때마다 한 줄씩 남긴다. 사업주 화면(설정)의
'AI 사용량 (이번 달)' 카드와 GET /ai/usage가 이 기록을 모아 보여 준다.

- 개인정보: 지시문·문장·사람 이름 등 내용은 남기지 않는다. 시각, 종류(decompose/rerank/coaching/embed/other),
  모델 이름, 토큰 수, 추정 요금만 남긴다.
- 실패해도 요청을 막지 않는다: 기록·조회 오류는 경고 로그만 남기고 삼킨다.
- 스레드 안전: 그림 재순위(aac_rerank.py)가 작업 스레드 여러 개에서 동시에 부른다 — 잠금 하나로 줄 세운다.
- 저장 위치: GPT_USAGE_DB(SQLite 파일). 비우면(코드 기본) 기록하지 않는다 — aac_rerank의 AAC_LLM_RERANK_CACHE_DB와
  같은 방식. Docker는 /app/cache/gpt_usage.sqlite3(ai-cache 볼륨)을 준다.
- 요금은 추정이다. 실제 청구 금액은 OpenAI 사용량 화면이 정확하다.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("ai_harness.gpt_usage")

KINDS = ("decompose", "rerank", "coaching", "embed", "other")

# 100만 토큰당 달러(입력, 출력). 모델 이름 앞부분으로 찾는다 — 응답 모델은 'gpt-4o-mini-2024-07-18'처럼 날짜가 붙는다.
# 긴 이름을 먼저 본다. 모르는 모델은 gpt-4o-mini 값으로 셈하고 '추정'으로 표시한다.
PRICES: tuple[tuple[str, float, float], ...] = (
    ("gpt-4o-mini", 0.15, 0.60),
    ("text-embedding-3-small", 0.02, 0.0),
    # 코드 기본 임베딩 모델(llm.EMBED_MODEL)이 large라 따로 둔다(2026-11 OpenAI 공시 $0.13/1M).
    ("text-embedding-3-large", 0.13, 0.0),
)
_FALLBACK = (0.15, 0.60)

# 기록을 400일만 둔다. 지우기는 프로세스마다 한 시간에 한 번만 한다(t 색인이 있어 가볍다).
RETENTION_DAYS = 400
_PURGE_EVERY_SEC = 3600.0

# 한국 시간(서머타임 없음). 월 경계·날짜는 이 시간대로 자른다. zoneinfo는 Windows에 tzdata가 없어 쓰지 않는다.
KST = timezone(timedelta(hours=9))

_lock = threading.Lock()
_last_purge = 0.0


def db_path() -> str:
    return (os.getenv("GPT_USAGE_DB") or "").strip()


def alert_usd() -> float:
    try:
        return float(os.getenv("GPT_MONTHLY_ALERT_USD", "5"))
    except ValueError:
        return 5.0


def price_for(model: str) -> tuple[float, float, bool]:
    """(입력 단가, 출력 단가, 추정 여부). 단가는 100만 토큰당 달러."""
    name = (model or "").strip().lower()
    for prefix, p_in, p_out in PRICES:
        if name.startswith(prefix):
            return p_in, p_out, False
    return _FALLBACK[0], _FALLBACK[1], True


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> tuple[float, bool]:
    p_in, p_out, estimated = price_for(model)
    return (prompt_tokens * p_in + completion_tokens * p_out) / 1_000_000, estimated


def _open(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=2.0)
    conn.execute("CREATE TABLE IF NOT EXISTS usage (t REAL NOT NULL, kind TEXT NOT NULL, model TEXT NOT NULL, "
                 "prompt_tokens INTEGER NOT NULL, completion_tokens INTEGER NOT NULL, usd REAL NOT NULL, "
                 "estimated INTEGER NOT NULL)")
    conn.execute("CREATE INDEX IF NOT EXISTS usage_t ON usage (t)")
    return conn


def _int(v) -> int:
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


def record(kind: str, model: str, prompt_tokens: int, completion_tokens: int, *, now: float | None = None) -> None:
    """한 번의 OpenAI 응답을 남긴다. 절대 예외를 내지 않는다."""
    global _last_purge
    path = db_path()
    if not path:
        return
    try:
        kind = kind if kind in KINDS else "other"
        model = (model or "unknown")[:80]
        p, c = _int(prompt_tokens), _int(completion_tokens)
        usd, estimated = cost_usd(model, p, c)
        t = time.time() if now is None else now
        # 잠금을 오래 기다리지 않는다 — 기록 하나 때문에 요청이 늦어지면 안 된다.
        if not _lock.acquire(timeout=1.0):
            logger.warning("GPT 사용량 기록 건너뜀: 잠금 대기 초과")
            return
        try:
            conn = _open(path)
            try:
                with conn:
                    conn.execute("INSERT INTO usage (t, kind, model, prompt_tokens, completion_tokens, usd, estimated) "
                                 "VALUES (?, ?, ?, ?, ?, ?, ?)", (t, kind, model, p, c, usd, int(estimated)))
                    if t - _last_purge >= _PURGE_EVERY_SEC:
                        conn.execute("DELETE FROM usage WHERE t < ?", (t - RETENTION_DAYS * 86400,))
                        _last_purge = t
            finally:
                conn.close()
        finally:
            _lock.release()
    except Exception as e:  # noqa: BLE001 - 기록 실패가 요청을 깨면 안 된다
        logger.warning("GPT 사용량 기록 실패: %s", type(e).__name__)


def record_response(kind: str, data, fallback_model: str) -> None:
    """OpenAI 응답 본문(dict)에서 모델·토큰 수만 꺼내 남긴다. 본문의 내용(문장·벡터)은 보지 않는다."""
    try:
        data = data if isinstance(data, dict) else {}
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        model = data.get("model") if isinstance(data.get("model"), str) and data.get("model") else fallback_model
        record(kind, model, usage.get("prompt_tokens"), usage.get("completion_tokens"))
    except Exception as e:  # noqa: BLE001
        logger.warning("GPT 사용량 기록 실패: %s", type(e).__name__)


def _empty_summary(month: str, days: list[str], limit: float, enabled: bool) -> dict:
    return {
        "enabled": enabled,
        "month": month,
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "usd": 0.0,
        "by_kind": {},
        "alert_usd": limit,
        "over_alert": False,
        "last_7_days": [{"date": d, "calls": 0, "usd": 0.0} for d in days],
    }


def summary(*, now: float | None = None) -> dict:
    """이번 달(한국 시간) 합계와 최근 7일. 기록이 꺼져 있거나 읽기에 실패하면 0으로 채워 돌려준다."""
    t = time.time() if now is None else now
    local_now = datetime.fromtimestamp(t, KST)
    month_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    today = local_now.date()
    days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    week_start = datetime(today.year, today.month, today.day, tzinfo=KST) - timedelta(days=6)
    limit = alert_usd()
    out = _empty_summary(local_now.strftime("%Y-%m"), days, limit, bool(db_path()))
    path = db_path()
    if not path:
        return out
    try:
        with _lock:
            conn = _open(path)
            try:
                rows = conn.execute(
                    "SELECT kind, COUNT(*), SUM(prompt_tokens), SUM(completion_tokens), SUM(usd) FROM usage "
                    "WHERE t >= ? GROUP BY kind", (month_start.timestamp(),)).fetchall()
                # 날짜별 묶음은 한국 시간 기준(+9시간)으로 자른다.
                day_rows = conn.execute(
                    "SELECT date(t + 32400, 'unixepoch'), COUNT(*), SUM(usd) FROM usage WHERE t >= ? "
                    "GROUP BY 1", (week_start.timestamp(),)).fetchall()
            finally:
                conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("GPT 사용량 읽기 실패: %s", type(e).__name__)
        out["error"] = True
        return out
    for kind, n, p, c, usd in rows:
        out["calls"] += int(n)
        out["prompt_tokens"] += int(p or 0)
        out["completion_tokens"] += int(c or 0)
        out["usd"] += float(usd or 0.0)
        out["by_kind"][kind] = {"calls": int(n), "usd": round(float(usd or 0.0), 6)}
    out["usd"] = round(out["usd"], 6)
    out["over_alert"] = out["usd"] > limit
    per_day = {d: (int(n), float(u or 0.0)) for d, n, u in day_rows}
    out["last_7_days"] = [{"date": d, "calls": per_day.get(d, (0, 0.0))[0],
                           "usd": round(per_day.get(d, (0, 0.0))[1], 6)} for d in days]
    return out
