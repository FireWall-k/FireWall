"""ARASAAC 검색 품질 개선 테스트 (네트워크는 _fetch 목으로 대체).

검증: bestsearch 우선 사용 / exact 키워드 우선 선택 / search 폴백 / 다국어 정렬.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import arasaac  # noqa: E402


def test_bestsearch_is_tried_first(monkeypatch):
    calls = []

    def fake_fetch(url, timeout):
        calls.append(url)
        if "bestsearch" in url:
            return [{"_id": 111, "keywords": [{"keyword": "box"}]}]
        return [{"_id": 999, "keywords": [{"keyword": "other"}]}]

    monkeypatch.setattr(arasaac, "_fetch", fake_fetch)
    res = arasaac.search_term("box", langs=["en"])
    assert res[0]["pictogram_id"] == "111"      # bestsearch 결과 사용
    assert "bestsearch" in calls[0]              # bestsearch를 먼저 호출


def test_exact_keyword_preferred_over_first_item(monkeypatch):
    # 첫 항목은 관련 없는 'package', 두 번째가 정확히 'box' → box를 골라야 함
    def fake_fetch(url, timeout):
        return [
            {"_id": 1, "keywords": [{"keyword": "package"}]},
            {"_id": 2, "keywords": [{"keyword": "box"}]},
        ]
    monkeypatch.setattr(arasaac, "_fetch", fake_fetch)
    res = arasaac.search_term("box", langs=["en"])
    assert res[0]["pictogram_id"] == "2"
    assert res[0]["exact"] is True
    assert res[0]["matched_keyword"] == "box"


def test_falls_back_to_search_when_bestsearch_empty(monkeypatch):
    def fake_fetch(url, timeout):
        if "bestsearch" in url:
            return None  # bestsearch 결과 없음
        return [{"_id": 7, "keywords": [{"keyword": "box"}]}]
    monkeypatch.setattr(arasaac, "_fetch", fake_fetch)
    res = arasaac.search_term("box", langs=["en"])
    assert res[0]["pictogram_id"] == "7"


def test_exact_results_ordered_before_fuzzy_across_langs(monkeypatch):
    # ko: fuzzy, en: exact → en(exact)이 앞에 와야 함
    def fake_fetch(url, timeout):
        if "/ko/" in url:
            return [{"_id": 10, "keywords": [{"keyword": "상자류"}]}]   # 포함(fuzzy)
        if "/en/" in url:
            return [{"_id": 20, "keywords": [{"keyword": "box"}]}]      # exact
        return None
    monkeypatch.setattr(arasaac, "_fetch", fake_fetch)
    res = arasaac.search_term("box", langs=["ko", "en"])
    assert res[0]["pictogram_id"] == "20"
    assert res[0]["exact"] is True


def test_no_results_returns_empty(monkeypatch):
    monkeypatch.setattr(arasaac, "_fetch", lambda url, timeout: None)
    assert arasaac.search_term("nothing", langs=["en"]) == []
