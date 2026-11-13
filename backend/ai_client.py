"""AI 하네스 HTTP 클라이언트.

이 파일이 '백엔드 <-> AI 하네스' 경계의 전부다 (명세서 4-2).
AI 담당자는 이 계약만 지키면 내부를 자유롭게 바꿀 수 있다.
AI 서비스가 떠 있지 않으면 안전하게 빈/폴백 결과로 떨어진다.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("ai_client")

AI_BASE_URL = os.getenv("AI_BASE_URL", "http://localhost:8001")
TIMEOUT = float(os.getenv("AI_TIMEOUT", "15"))

# 연결을 재사용하는 공용 클라이언트(스레드 안전). httpx.post()는 호출마다 클라이언트를 새로 만들어
# SSL 설정을 읽고 TCP 연결을 새로 맺는다 — 실측 호출당 약 1초(재사용 시 18ms). 직무 하나에
# 단계마다 호출하므로 이 비용이 직무 생성 지연의 대부분이었다.
_http = httpx.Client(
    timeout=TIMEOUT,
    limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
)


def decompose(raw_input: str, context: dict | None = None, *, timeout: float | None = None) -> dict:
    """원문 -> {task_title, steps[]}. 실패 시 예외를 올린다(상위에서 처리).
    timeout: 이 호출만 짧게 기다릴 때(편집기 저장 시 나누기 확인). 없으면 AI_TIMEOUT."""
    resp = _http.post(
        f"{AI_BASE_URL}/ai/decompose",
        json={"raw_input": raw_input, "context": context or {}},
        **({"timeout": timeout} if timeout is not None else {}),
    )
    resp.raise_for_status()
    return resp.json()


def classify_action(sentence: str) -> str:
    """단계 문장 -> 동작 계열(action_type). AI 하네스가 죽어 있거나 실패하면 'other'(꼬리표 숨김·그림 벌점 없음).

    하네스는 규칙 분류만 한다(LLM·외부 API 호출 없음).
    """
    try:
        resp = _http.post(f"{AI_BASE_URL}/ai/classify-action", json={"sentence": sentence})
        resp.raise_for_status()
        return str(resp.json().get("action_type") or "other")
    except Exception as e:  # noqa: BLE001
        logger.warning("classify_action fallback: %s", e)
        return "other"


def split_hint(sentence: str) -> bool | None:
    """고친 단계 문장 하나에 동작이 둘 이상일 수 있는가(AI 하네스의 규칙 동작 세기, LLM 없음).
    하네스가 답하지 못하면(장애·옛 버전) None — 부르는 쪽이 겉모양 검사로 대신한다."""
    try:
        resp = _http.post(f"{AI_BASE_URL}/ai/split-hint", json={"sentence": sentence}, timeout=3)
        resp.raise_for_status()
        value = resp.json().get("may_split")
        return value if isinstance(value, bool) else None
    except Exception as e:  # noqa: BLE001
        logger.warning("split_hint fallback: %s", e)
        return None


def map_symbols(keywords: list[str], context: dict | None = None) -> dict:
    """키워드 -> {symbols[]}. 실패하면 모두 폴백으로 처리한 결과를 돌려준다."""
    try:
        resp = _http.post(
            f"{AI_BASE_URL}/ai/map-symbols",
            json={"keywords": keywords, "context": context or {}},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("map_symbols fallback: %s", e)
        return {"symbols": [
            {"keyword": k, "image_url": None, "source": "fallback",
             "confidence": 0.0, "needs_fallback": True}
            for k in keywords
        ]}


def search_aac(
    query: str,
    context: dict | None = None,
    limit: int = 5,
) -> dict:
    """자체 AAC 데이터셋에서 검색한다.

    AI 하네스가 죽어 있거나 요청에 실패하면 빈 결과로 안전하게 떨어진다.
    """
    try:
        resp = _http.post(
            f"{AI_BASE_URL}/ai/aac/search",
            json={
                "query": query,
                "context": context or {},
                "limit": limit,
            },
        )
        resp.raise_for_status()
        return resp.json()

    except Exception as e:  # noqa: BLE001
        logger.warning("search_aac fallback: %s", e)

        return {
            "query": query,
            "matches": [],
        }
    
def coaching(task_title: str, steps: list[dict], context: dict | None = None,
             allow_llm: bool = True) -> dict:
    """단계별 수행 데이터 -> {summary, suggestions[]}.

    allow_llm=False면 AI 하네스가 LLM(해외 전송)을 쓰지 않고 규칙 기반 제안만 만든다 — AI 처리 동의가
    없는 근로자의 기록이 들어 있을 때 백엔드가 끈다. 하네스 자체는 같은 내부망의 자체 서비스다.
    AI 하네스가 죽어 있거나 실패하면 빈 제안으로 안전하게 떨어진다.
    """
    try:
        resp = _http.post(
            f"{AI_BASE_URL}/ai/coaching",
            json={"task_title": task_title, "steps": steps, "context": context or {},
                  "allow_llm": allow_llm},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("coaching fallback: %s", e)
        return {"summary": "AI 코칭을 불러오지 못했습니다.", "suggestions": []}


def ai_usage() -> dict | None:
    """이번 달 GPT 사용량(AI 하네스 GET /ai/usage). 하네스에 닿지 못하거나 응답이 이상하면 None."""
    try:
        resp = _http.get(f"{AI_BASE_URL}/ai/usage", timeout=3)
        resp.raise_for_status()
        body = resp.json()
        return body if isinstance(body, dict) else None
    except Exception as e:  # noqa: BLE001
        logger.warning("ai_usage unavailable: %s", type(e).__name__)
        return None
