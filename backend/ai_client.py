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


def decompose(raw_input: str, context: dict | None = None) -> dict:
    """원문 -> {task_title, steps[]}. 실패 시 예외를 올린다(상위에서 처리)."""
    resp = httpx.post(
        f"{AI_BASE_URL}/ai/decompose",
        json={"raw_input": raw_input, "context": context or {}},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def map_symbols(keywords: list[str], context: dict | None = None) -> dict:
    """키워드 -> {symbols[]}. 실패하면 모두 폴백으로 처리한 결과를 돌려준다."""
    try:
        resp = httpx.post(
            f"{AI_BASE_URL}/ai/map-symbols",
            json={"keywords": keywords, "context": context or {}},
            timeout=TIMEOUT,
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


def search_arasaac(term: str, langs: list[str] | None = None, limit: int = 1) -> dict:
    """ARASAAC 단어 검색 결과를 돌려준다.

    AI 하네스가 죽어 있거나 네트워크가 막히면 빈 결과로 안전하게 떨어진다.
    """
    try:
        resp = httpx.post(
            f"{AI_BASE_URL}/ai/arasaac/search",
            json={"term": term, "langs": langs or [], "limit": limit},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("search_arasaac fallback: %s", e)
        return {"term": term, "matches": []}


def coaching(task_title: str, steps: list[dict], context: dict | None = None) -> dict:
    """단계별 수행 데이터 -> {summary, suggestions[]}.

    AI 하네스가 죽어 있거나 실패하면 빈 제안으로 안전하게 떨어진다.
    """
    try:
        resp = httpx.post(
            f"{AI_BASE_URL}/ai/coaching",
            json={"task_title": task_title, "steps": steps, "context": context or {}},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("coaching fallback: %s", e)
        return {"summary": "AI 코칭을 불러오지 못했습니다.", "suggestions": []}
