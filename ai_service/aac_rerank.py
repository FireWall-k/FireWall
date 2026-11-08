"""단계 그림 고르기에 GPT 재순위를 더한다(규칙 상위 10장 → GPT가 한 장 고르기).

흐름(symbols.map_symbols에서 부른다):
  1) 규칙 검색(local_aac.search_for_step_detailed)은 그대로 돈다. 후보 순서·점수는 바꾸지 않는다.
  2) GPT에 단계 문장 + 업종 + 규칙 상위 10장 이름을 보내고 {"choice": n|0, "confident": bool}을 받는다.
  3) 정책(AAC_LLM_RERANK_POLICY)으로 자동 채택 여부를 정한다.
     - top1(기본): GPT가 확신하고 고른 카드가 규칙 1순위와 같을 때만 자동 채택한다.
       규칙이 채택했어도 GPT가 확인해 주지 않으면(다른 카드·0·확신 없음) 사람에게 넘긴다.
     - top3: GPT가 확신하고 고른 카드가 규칙 상위 3장 안이면 그 카드를 자동 채택한다.
  4) 자동 채택하지 않을 때, GPT가 고른 카드가 상위 3장 안이면 사업주에게 보여 줄 후보 맨 앞에 둔다.
  5) 키 없음·꺼짐·시간 초과·오류·이상한 응답이면 규칙 판정을 그대로 돌려준다(지금과 같은 동작).
     시간 제한(AAC_LLM_RERANK_TIMEOUT)은 호출 전체의 마감이다 — httpx timeout은 연결·읽기 단계마다 따로
     세므로, 응답이 조금씩 흘러들어오면 넘을 수 있어 호출을 작업 스레드에서 돌리고 결과를 마감까지만 기다린다.
     마감은 작업 스레드가 호출을 **시작한 때부터** 센다(줄에서 기다린 시간은 넣지 않는다). 작업 스레드 수
     (AAC_LLM_RERANK_WORKERS, 기본 16)는 백엔드가 동시에 준비하는 단계 수(STEP_PREP_WORKERS=8, 직무 둘이면 16)
     이상으로 둔다. 마감 안에 빈 작업 스레드를 얻지 못하면 요청 없이 규칙 판정으로 가되 쉬는 시간은 걸지 않는다
     (GPT가 느린 것이 아니라 이 프로세스가 바쁜 것이다).
  6) 연결·HTTP 오류·시간 초과 뒤, 그리고 이상한 응답이 연달아 _BAD_STREAK_LIMIT번 오면 잠시 GPT를 쉰다
     (장애 중에 단계마다 돈을 내고도 규칙 판정으로 떨어지지 않게).

정책 근거(2026-11-08, gpt-4o-mini, 임베딩 꺼짐, eval/README.md의 표):
  블라인드1(90)·봉인 시험지2(89)에서 top1 정책은 규칙만 쓸 때보다 틀린 자동 채택이 줄고(3→2, 9→3)
  맞은 자동 채택이 늘었다(39→45, 24→37). "규칙 채택은 유지하고 GPT가 다른 카드를 고를 때만 취소"하는
  변형은 두 셋에서 top1과 결과가 똑같았다(규칙이 채택한 문항에서 GPT가 1순위를 고르면 언제나 확신했다).
  같은 결과라면 판정 기준이 하나인 top1을 기본으로 둔다. "규칙 채택 + GPT 확신 일치 추가"는 틀린
  채택이 3→5, 9→12로 늘었고, top3는 블라인드1에서 틀린 채택을 하나 더 만들었다(3→4).

비용: 단계 하나에 한 번(입력 약 254토큰, 출력 약 12토큰) — gpt-4o-mini 기준 단계 100개에 약 $0.0045.
같은 (문장, 검색어, 업종, 후보) 조합은 다시 부르지 않는다: 프로세스 안 LRU 캐시(AAC_LLM_RERANK_CACHE)와,
AAC_LLM_RERANK_CACHE_DB를 주면 재시작해도 남는 SQLite 파일(Docker 기본 /app/cache, 이름 있는 볼륨). 파일에는
조합의 sha256(모델·프롬프트 포함)과 판정(choice, confident)만 남기고 문장은 남기지 않는다. 그래서 검토 화면이 후보를
다시 불러도 같은 조합이면 직무 생성 때와 같은 판정이 나온다(temperature 0.2라 다시 물으면 달라질 수 있다).

개인정보: 보내는 것은 단계 문장(백엔드가 실명을 별칭으로 바꾼 것)·업종·카드 이름뿐이다 — 직무 분해가
이미 보내는 것과 같은 범위다. 로그에는 문장을 남기지 않고 판정·선택 번호·지연만 남긴다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sqlite3
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeout

import httpx

import llm

logger = logging.getLogger("ai_harness.aac_rerank")

# GPT에 보여 줄 규칙 후보 수. 실측(블라인드1·2)에서 이 값으로 쟀다.
TOP_N = 10
# 사업주 검토 화면에 보여 주는 후보 수(symbols._SHORTLIST와 같다). GPT가 고른 카드를 앞으로 올리는 범위.
SHORTLIST = 3

# 실측에 쓴 프롬프트 그대로다(scratchpad gptexp.py RERANK_SYS). 바꾸면 eval/run_rerank_eval.py로 다시 잰다.
RERANK_SYSTEM = (
    "You help pick an AAC picture card for a Korean work instruction for workers with developmental disabilities. "
    "Given the instruction and numbered candidate card labels, choose the ONE card that shows exactly the same action "
    "on the same kind of object. If the instruction has two actions, prefer the main (last) action. If none of the cards "
    "shows it, answer 0. Reply JSON {\"choice\": <number>, \"confident\": true|false}."
)
MAX_TOKENS = 30
# 이상한 응답(JSON 깨짐·번호 범위 밖 등)이 이만큼 연달아 오면 쉬는 시간을 건다.
_BAD_STREAK_LIMIT = 3

_OFF_VALUES = frozenset({"off", "0", "false", "no"})
_POLICIES = frozenset({"top1", "top3"})


def mode() -> str:
    """AAC_LLM_RERANK: 'auto'(기본, 키가 있으면 켠다) | 'off'."""
    value = (os.getenv("AAC_LLM_RERANK") or "auto").strip().lower()
    return "off" if value in _OFF_VALUES else "auto"


def policy() -> str:
    """AAC_LLM_RERANK_POLICY: 'top1'(기본) | 'top3'. 모르는 값은 top1."""
    value = (os.getenv("AAC_LLM_RERANK_POLICY") or "top1").strip().lower()
    return value if value in _POLICIES else "top1"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def timeout() -> float:
    """AAC_LLM_RERANK_TIMEOUT(초, 기본 4). 넘으면 규칙 판정으로 간다."""
    return _env_float("AAC_LLM_RERANK_TIMEOUT", 4.0)


def _cooldown_sec() -> float:
    """연결·HTTP 오류·마감 초과·연속된 이상한 응답 뒤 GPT를 쉬는 시간(초, 기본 60). 직무 하나에 단계가 여럿이라, 장애 중에 단계마다
    시간 초과를 기다리면 직무 생성이 그만큼 늦어진다(임베딩 질의의 쉬는 시간과 같은 이유)."""
    return _env_float("AAC_LLM_RERANK_COOLDOWN", 60.0)


def _cache_size() -> int:
    return max(0, int(_env_float("AAC_LLM_RERANK_CACHE", 1024)))


def _workers() -> int:
    """AAC_LLM_RERANK_WORKERS(기본 16). 백엔드 STEP_PREP_WORKERS(8) × 동시에 만드는 직무 수 이상으로 둔다."""
    return max(1, int(_env_float("AAC_LLM_RERANK_WORKERS", 16)))


def _cache_db() -> str:
    """AAC_LLM_RERANK_CACHE_DB: 판정을 재시작 뒤에도 남길 SQLite 파일 경로. 비우면(코드 기본) 프로세스 안에만 둔다."""
    return (os.getenv("AAC_LLM_RERANK_CACHE_DB") or "").strip()


class _Busy(Exception):
    """마감 안에 빈 작업 스레드를 얻지 못했다(요청은 보내지 않았다). 쉬는 시간을 걸지 않는다."""


_lock = threading.Lock()
_cache: OrderedDict[tuple, tuple[int, bool]] = OrderedDict()
_down_until = 0.0
_bad_streak = 0
# 호출 전체 마감을 지키려고 GPT 호출을 여기서 돌린다. 마감을 넘긴 호출은 버리고(스레드는 httpx 단계별
# timeout으로 곧 끝난다) 쉬는 시간을 걸어, 장애 중에 멈춘 호출이 쌓이지 않는다. 크기는 백엔드 동시 단계 수 이상
# (예전 4개는 직무 하나의 8단계 중 5~8번째가 줄에서 기다린 시간까지 마감에 들어가 거짓 시간 초과가 났다).
_pool = ThreadPoolExecutor(max_workers=_workers(), thread_name_prefix="aac-rerank")


def reset_state() -> None:
    """캐시·쉬는 시간·연속 실패 수를 비운다(테스트용)."""
    global _down_until, _bad_streak
    with _lock:
        _cache.clear()
        _down_until = 0.0
        _bad_streak = 0


def _cool_down() -> None:
    global _down_until
    with _lock:
        _down_until = time.monotonic() + _cooldown_sec()


def available() -> bool:
    """재순위를 시도할 수 있는가: 꺼지지 않았고, 키가 있고, 오류 뒤 쉬는 중이 아니다."""
    if mode() == "off" or not llm.llm_available():
        return False
    with _lock:
        return time.monotonic() >= _down_until


def build_user_prompt(sentence: str, business_type: str, candidates: list[dict]) -> str:
    """GPT에 보낼 사용자 메시지. 실측 때와 같은 모양이어야 캐시·평가가 맞는다."""
    lines = [f"{i + 1}. {c.get('label', '')}" for i, c in enumerate(candidates)]
    return f"지시문: {sentence}\n업종: {business_type}\n후보:\n" + "\n".join(lines)


def parse_verdict(raw: dict, n_candidates: int) -> tuple[int, bool]:
    """GPT 응답을 (choice, confident)로 검증한다. 형식이 어긋나면 ValueError(→ 규칙 판정)."""
    if not isinstance(raw, dict):
        raise ValueError("응답이 객체가 아님")
    choice = raw.get("choice")
    if isinstance(choice, bool) or choice is None:
        raise ValueError("choice 없음")
    if isinstance(choice, float) and not (math.isfinite(choice) and choice.is_integer()):
        # 1.7을 1로 자르지 않는다 — 형식이 어긋난 답은 규칙 판정으로 간다.
        raise ValueError("choice가 정수가 아님")
    try:
        choice = int(choice)
    except (TypeError, ValueError, OverflowError) as e:
        raise ValueError("choice가 숫자가 아님") from e
    if not 0 <= choice <= n_candidates:
        raise ValueError("choice 범위 밖")
    conf = raw.get("confident")
    if isinstance(conf, str):
        conf = conf.strip().lower() == "true"
    return choice, conf is True


def _db_key(key: tuple) -> str:
    """디스크에 남기는 키: 모델·프롬프트·조합의 sha256. 문장 자체는 남기지 않는다."""
    sentence, keywords, business_type, ids = key
    raw = json.dumps([llm.OPENAI_MODEL, RERANK_SYSTEM, sentence, list(keywords), business_type, list(ids)],
                     ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _db_open(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=2.0)
    conn.execute("CREATE TABLE IF NOT EXISTS verdict (k TEXT PRIMARY KEY, choice INTEGER NOT NULL, "
                 "confident INTEGER NOT NULL, t REAL NOT NULL)")
    return conn


def _db_get(key: tuple) -> tuple[int, bool] | None:
    path = _cache_db()
    if not path:
        return None
    try:
        conn = _db_open(path)
        try:
            row = conn.execute("SELECT choice, confident FROM verdict WHERE k = ?", (_db_key(key),)).fetchone()
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as e:
        logger.warning("aac rerank 판정 파일 읽기 실패: %s", type(e).__name__)
        return None
    return (int(row[0]), bool(row[1])) if row else None


def _db_put(key: tuple, value: tuple[int, bool]) -> None:
    path = _cache_db()
    if not path:
        return
    try:
        conn = _db_open(path)
        try:
            with conn:
                conn.execute("INSERT OR REPLACE INTO verdict (k, choice, confident, t) VALUES (?, ?, ?, ?)",
                             (_db_key(key), int(value[0]), int(bool(value[1])), time.time()))
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as e:
        logger.warning("aac rerank 판정 파일 쓰기 실패: %s", type(e).__name__)


def _mem_put(key: tuple, value: tuple[int, bool]) -> None:
    size = _cache_size()
    if size <= 0:
        return
    with _lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > size:
            _cache.popitem(last=False)


def _cache_get(key: tuple) -> tuple[int, bool] | None:
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit
    hit = _db_get(key)
    if hit is not None:
        _mem_put(key, hit)
    return hit


def _cache_put(key: tuple, value: tuple[int, bool]) -> None:
    _mem_put(key, value)
    _db_put(key, value)


def _run_with_deadline(fn, deadline: float):
    """fn을 작업 스레드에서 돌리고 결과를 기다린다. 마감은 작업 스레드가 fn을 시작한 때부터 센다.

    마감 안에 시작하지 못하면 취소하고 _Busy(요청을 보내지 않았다). 시작한 뒤 마감을 넘기면 _FutureTimeout.
    """
    started = threading.Event()
    begun = [0.0]

    def run():
        begun[0] = time.monotonic()
        started.set()
        return fn()

    future = _pool.submit(run)
    if not started.wait(timeout=deadline):
        if future.cancel():
            raise _Busy("빈 작업 스레드 없음")
        started.wait()  # 취소 직전에 시작했다 — 시작 시각은 곧 기록된다
    remaining = deadline - (time.monotonic() - begun[0])
    try:
        return future.result(timeout=max(0.0, remaining))
    except _FutureTimeout:
        future.cancel()
        raise


def _ask(sentence: str, business_type: str, keywords: list[str], top: list[dict]) -> tuple[tuple[int, bool], bool]:
    """((choice, confident), 캐시 적중 여부). 실패하면 예외."""
    global _bad_streak
    key = (sentence, tuple(keywords), business_type, tuple(c.get("asset_id", "") for c in top))
    hit = _cache_get(key)
    if hit is not None:
        return hit, True
    user = build_user_prompt(sentence, business_type, top)
    deadline = timeout()
    try:
        raw = _run_with_deadline(
            lambda: llm.chat_json(RERANK_SYSTEM, user, max_tokens=MAX_TOKENS, timeout=deadline), deadline)
        verdict = parse_verdict(raw, len(top))
    except _Busy:
        # 요청을 보내지 않았다 — GPT 장애가 아니므로 쉬는 시간·연속 실패 수를 건드리지 않는다.
        raise
    except (httpx.HTTPError, _FutureTimeout):
        # 연결 실패·시간 초과(전체 마감 포함)·4xx/5xx(키 오류, 한도 초과 포함). 잠시 쉬어 다음 단계들이
        # 기다리지 않게 한다.
        _cool_down()
        raise
    except Exception:
        # JSON 깨짐·choices 없음·번호 범위 밖 등. 한두 번은 넘기고, 연달아 오면 쉰다.
        with _lock:
            _bad_streak += 1
            trip = _bad_streak >= _BAD_STREAK_LIMIT
            if trip:
                _bad_streak = 0
        if trip:
            _cool_down()
        raise
    with _lock:
        _bad_streak = 0
    _cache_put(key, verdict)
    return verdict, False


def apply_policy(decision: dict, choice: int, confident: bool, rule_policy: str = "top1") -> dict:
    """규칙 판정(decision)에 GPT 답을 적용한 새 판정을 돌려준다. decision은 바꾸지 않는다.

    choice는 decision["candidates"] 상위 TOP_N 안의 1부터 센 번호(0 = 맞는 카드 없음).
    """
    cands = list(decision.get("candidates") or [])
    out = dict(decision)
    out["decided_by"] = "llm"
    out["llm"] = {"choice": choice, "confident": confident, "policy": rule_policy}
    idx = choice - 1 if 1 <= choice <= min(len(cands), TOP_N) else None

    if rule_policy == "top3":
        accept = confident and idx is not None and idx < SHORTLIST
    else:
        accept = confident and idx == 0

    # GPT가 고른 카드가 보여 줄 후보 안에 있으면 맨 앞으로 올린다(나머지 순서는 그대로).
    if idx is not None and 0 < idx < SHORTLIST:
        cands = [cands[idx]] + cands[:idx] + cands[idx + 1:]
    out["candidates"] = cands

    if accept:
        out["match"] = cands[0]
        out["reason"] = "accepted"
        return out
    out["match"] = None
    if decision.get("match") is not None:
        # 규칙은 채택했지만 GPT가 확인해 주지 않았다 → 후보를 보여 주고 사람이 고른다.
        out["reason"] = "llm_disagree"
    return out


def rerank(decision: dict, *, keywords: list[str], context: dict | None, enabled: bool | None = None) -> dict:
    """규칙 판정에 GPT 재순위를 적용한다. 못 쓰면 규칙 판정 그대로(decided_by='rule').

    enabled: 부르는 쪽이 검색 limit을 고를 때 이미 본 available() 값. False면 그 사이 쉬는 시간이 끝났어도
    부르지 않는다 — 후보를 기본 개수만 받았으므로 실측(10장)과 다른 입력을 GPT에 보내지 않기 위해서다.
    """
    out = dict(decision)
    out["decided_by"] = "rule"
    cands = decision.get("candidates") or []
    if not cands or enabled is False or not available():
        return out
    ctx = context or {}
    sentence = str(ctx.get("sentence") or "").strip() or " ".join(str(k) for k in keywords).strip()
    business_type = str(ctx.get("business_type") or "").strip()
    top = cands[:TOP_N]
    started = time.monotonic()
    try:
        (choice, confident), cached = _ask(sentence, business_type, [str(k) for k in keywords], top)
    except Exception as e:  # noqa: BLE001 - 어떤 실패든 규칙 판정으로 간다
        logger.warning("aac rerank 실패 → 규칙 판정: %s", type(e).__name__)
        return out
    result = apply_policy(decision, choice, confident, policy())
    # 관측: 문장·검색어는 남기지 않는다(근로자 관련 내용이 들어갈 수 있다).
    logger.info(
        "aac rerank rule=%s final=%s choice=%s confident=%s cached=%s ms=%d",
        decision.get("reason"), result["reason"], choice, confident, cached,
        (time.monotonic() - started) * 1000,
    )
    return result
