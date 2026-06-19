"""map_symbols 관련성 선택 테스트 (search_term 목)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import symbols  # noqa: E402


def test_prefers_exact_match_term(monkeypatch):
    # 첫 후보는 fuzzy, 두 번째 후보는 exact → exact 선택 + 높은 confidence
    def fake_search(term, langs=None, timeout=None):
        if term == "box":
            return [{"language": "en", "term": "box", "pictogram_id": "2",
                     "image_url": "http://img/2", "exact": True, "matched_keyword": "box"}]
        return [{"language": "en", "term": term, "pictogram_id": "9",
                 "image_url": "http://img/9", "exact": False, "matched_keyword": "x"}]
    monkeypatch.setattr(symbols, "search_term", fake_search)
    monkeypatch.setattr(symbols, "ARASAAC_KEYWORD_SEARCH_LIMIT", 4)
    monkeypatch.setattr(symbols, "ARASAAC_TERM_SEARCH_LIMIT", 3)

    res = symbols.map_symbols(["box"], {})
    s = res.symbols[0]
    assert s.source == "ARASAAC"
    assert s.external_id == "2"
    assert s.confidence == 0.95
    assert s.needs_fallback is False


def test_fallback_when_no_match(monkeypatch):
    monkeypatch.setattr(symbols, "search_term", lambda *a, **k: [])
    monkeypatch.setattr(symbols, "ARASAAC_KEYWORD_SEARCH_LIMIT", 4)
    res = symbols.map_symbols(["unknownthing"], {})
    s = res.symbols[0]
    assert s.needs_fallback is True
    assert s.source == "fallback"


def test_search_limit_caps_network_calls(monkeypatch):
    calls = {"n": 0}
    def fake_search(term, langs=None, timeout=None):
        calls["n"] += 1
        return [{"language": "en", "term": term, "pictogram_id": "1",
                 "image_url": "u", "exact": True, "matched_keyword": term}]
    monkeypatch.setattr(symbols, "search_term", fake_search)
    monkeypatch.setattr(symbols, "ARASAAC_KEYWORD_SEARCH_LIMIT", 1)  # 1개만 검색
    res = symbols.map_symbols(["box", "size", "count"], {})
    # 첫 키워드만 검색, 나머지는 폴백
    assert res.symbols[0].needs_fallback is False
    assert res.symbols[1].needs_fallback is True
    assert res.symbols[2].needs_fallback is True
