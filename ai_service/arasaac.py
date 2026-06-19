"""ARASAAC API helper.

품질 개선(평가 반영):
1) /search 대신 /bestsearch를 우선 사용(의미적 관련성↑). 실패 시 /search로 폴백.
2) data[0]을 무조건 쓰지 않고, 검색어와 키워드가 일치하는 픽토그램을 우선 선택.
   exact 일치를 fuzzy보다 앞에 둬서 search_term 결과의 첫 항목이 '최선'이 되게 한다.
3) 다국어 검색(ko, en, es). 한국어 객체어는 ko에서, 영어어는 en/es에서 매칭.
"""
from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger("ai_harness.arasaac")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def get_api_base() -> str:
    return _env("ARASAAC_API_BASE", "https://api.arasaac.org")


def get_langs() -> list[str]:
    raw = _env("ARASAAC_LANGS", "ko,en,es")
    return [lang.strip() for lang in raw.split(",") if lang.strip()]


def get_timeout() -> float:
    return float(_env("ARASAAC_SEARCH_TIMEOUT", "1.5"))


def get_image_url_template() -> str:
    return _env(
        "ARASAAC_IMAGE_URL_TEMPLATE",
        "https://api.arasaac.org/v1/pictograms/{id}?download=false",
    )


def extract_picto_id(item: Any) -> str | None:
    if isinstance(item, int):
        return str(item)
    if isinstance(item, str) and item.isdigit():
        return item
    if not isinstance(item, dict):
        return None
    for key in ("_id", "id", "pictoId", "pictogramId"):
        value = item.get(key)
        if value is not None:
            return str(value)
    return None


def build_image_url(picto_id: str) -> str:
    return get_image_url_template().format(id=picto_id)


def _fetch(url: str, timeout: float) -> Any | None:
    """단일 GET → JSON. 404/오류는 None(상위에서 폴백)."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("ARASAAC fetch 실패 url=%s error=%s", url, exc)
        return None


def _search_lang(term: str, lang: str, timeout: float) -> list:
    """한 언어에 대해 bestsearch → search 순으로 시도."""
    base = get_api_base()
    for kind in ("bestsearch", "search"):
        url = f"{base}/api/pictograms/{quote(lang)}/{kind}/{quote(term)}"
        data = _fetch(url, timeout)
        if isinstance(data, list) and data:
            return data
    return []


def _pick_relevant(data: list, term: str) -> tuple[dict, bool, str | None]:
    """검색 결과에서 가장 관련 높은 항목을 고른다.

    1순위: keyword가 검색어와 정확히 일치 → exact
    2순위: keyword가 검색어를 포함/피포함 → fuzzy
    3순위: 첫 항목
    """
    term_l = term.strip().lower()
    for item in data:
        for kw in (item.get("keywords") or []):
            if str(kw.get("keyword", "")).strip().lower() == term_l:
                return item, True, kw.get("keyword")
    for item in data:
        for kw in (item.get("keywords") or []):
            k = str(kw.get("keyword", "")).strip().lower()
            if term_l and k and (term_l in k or k in term_l):
                return item, False, kw.get("keyword")
    return data[0], False, None


def search_term(term: str, langs: list[str] | None = None,
                timeout: float | None = None) -> list[dict[str, str]]:
    """ARASAAC 픽토그램 검색. exact 매칭을 앞쪽에 둔 결과 리스트를 돌려준다.

    반환 각 항목: language, term, pictogram_id, image_url, exact, matched_keyword
    첫 항목이 곧 '최선'이므로 호출부는 matches[0]을 그대로 쓰면 된다.
    """
    search_langs = langs or get_langs()
    search_timeout = timeout if timeout is not None else get_timeout()

    exact_results: list[dict[str, str]] = []
    fuzzy_results: list[dict[str, str]] = []

    for lang in search_langs:
        data = _search_lang(term, lang, search_timeout)
        if not data:
            continue
        item, is_exact, matched_kw = _pick_relevant(data, term)
        picto_id = extract_picto_id(item)
        if not picto_id:
            continue
        record = {
            "language": lang,
            "term": term,
            "pictogram_id": picto_id,
            "image_url": build_image_url(picto_id),
            "exact": is_exact,
            "matched_keyword": matched_kw or "",
        }
        (exact_results if is_exact else fuzzy_results).append(record)

    return exact_results + fuzzy_results
