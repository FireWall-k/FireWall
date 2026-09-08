"""Project-owned AAC mapping tests (no external network/API)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import symbols  # noqa: E402
from local_aac import search_assets  # noqa: E402


def test_local_aac_retail_exact_action():
    res = symbols.map_symbols(
        ["상품", "선반", "놓기"],
        {
            "business_type": "대형마트",
            "sentence": "상품을 선반에 놓으세요",
            "action_type": "move",
        },
    )

    s = res.symbols[0]

    assert s.source == "LOCAL_AAC"
    assert s.external_id == "RETAIL_029"
    assert s.needs_fallback is False
    assert s.image_url
    assert s.image_url.startswith("/api/aac/images/retail/")


def test_job_context_disambiguates_same_action():
    result = search_assets(
        "같은 상품끼리 모으세요",
        {
            "business_type": "마트",
            "action_type": "sort",
        },
        3,
    )

    assert result[0]["asset_id"] == "RETAIL_017"
    assert result[0]["job"] == "retail"


def test_fallback_when_no_relevant_match(monkeypatch):
    monkeypatch.setenv("AAC_MATCH_THRESHOLD", "0.95")

    res = symbols.map_symbols(
        ["완전히없는검색어zzqx"],
        {
            "sentence": "완전히없는검색어zzqx"
        },
    )

    s = res.symbols[0]

    assert s.needs_fallback is True
    assert s.source == "fallback"