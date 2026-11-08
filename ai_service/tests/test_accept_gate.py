"""P2 채택 게이트 — 명사에서 동사 뽑기 중지, 반대말 확대, 대상 불일치 시 자동 채택 보류."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import symbols  # noqa: E402
from local_aac import (  # noqa: E402
    _object_conflict, _verb_antonym_penalty, _verb_lemmas, decide, load_assets,
)


def _by_id():
    return {a["id"]: a for a in load_assets()}


def test_noun_with_particle_is_not_a_verb():
    # '쓰레기를'의 '쓰'는 동사 어간이 아니다 — 조사로 끝나는 어절은 명사다.
    lemmas = _verb_lemmas("쓰레기를 버리세요")
    assert "버리다" in lemmas
    assert "쓰다" not in lemmas and "쓸다" not in lemmas
    # 진짜 활용형은 그대로 뽑는다.
    assert "갈다" in _verb_lemmas("원두를 갈아주세요")
    assert "쓸다" in _verb_lemmas("빗자루로 바닥을 쓰세요") or "쓰다" in _verb_lemmas("빗자루로 바닥을 쓰세요")


def test_extended_antonyms():
    def asset(verb):
        return {"_frame": {"verb": verb}}
    assert _verb_antonym_penalty(asset("벗다"), {"끼다"}) < 1.0
    assert _verb_antonym_penalty(asset("입다"), {"벗다"}) < 1.0
    assert _verb_antonym_penalty(asset("빼다"), {"끼우다"}) < 1.0
    assert _verb_antonym_penalty(asset("비우다"), {"채우다"}) < 1.0
    assert _verb_antonym_penalty(asset("뽑다"), {"꽂다"}) < 1.0
    assert _verb_antonym_penalty(asset("내리다"), {"싣다"}) < 1.0
    # 동의어·무관한 동사는 깎지 않는다.
    assert _verb_antonym_penalty(asset("착용하다"), {"입다"}) == 1.0


def test_object_conflict_detects_different_target():
    by = _by_id()
    # CAFE_033 '컵에 뚜껑을 닫는다'(대상 뚜껑) — 문장이 '문을' 닫으라면 다른 대상이다.
    assert _object_conflict(by["CAFE_033"], "문을 닫으세요", "문을 닫으세요") is True
    assert _object_conflict(by["CAFE_033"], "컵 뚜껑을 닫으세요", "컵 뚜껑을 닫으세요") is False


def test_object_conflict_uses_synonyms():
    by = _by_id()
    # PACKAGING_047 '박스 덮개를 닫는다' — 뚜껑과 덮개는 같은 대상이다.
    assert _object_conflict(by["PACKAGING_047"], "박스 뚜껑을 닫으세요", "박스 뚜껑을 닫으세요") is False
    # CLEANING_015 '화장지를 채운다' — 휴지는 화장지다.
    assert _object_conflict(by["CLEANING_015"], "휴지를 채우세요", "휴지를 채우세요") is False
    # SERVING_043 '테이블 수저함을 확인한다' — 수저통은 수저함이다.
    assert _object_conflict(by["SERVING_043"], "수저통을 확인하세요", "수저통을 확인하세요") is False


def test_generic_asset_object_never_conflicts():
    # 그림 대상이 '상품/제품' 같은 일반 명사면 문장의 구체 대상(쿠키, 빵)을 포함할 수 있다.
    generic = {"id": "X", "label": "상품을 봉투에 넣는다", "_norm": "상품을 봉투에 넣는다",
               "_kw_norm": "", "_frame": {"object": "상품"}}
    assert _object_conflict(generic, "쿠키를 봉투에 넣으세요", "쿠키를 봉투에 넣으세요") is False


def test_no_query_object_means_no_conflict():
    by = _by_id()
    assert _object_conflict(by["CAFE_033"], "닫으세요", "닫으세요") is False


def test_decide_blocks_accept_on_object_mismatch_but_keeps_candidates():
    results = [{"asset_id": "CAFE_033", "score": 0.50, "job": "cafe"},
               {"asset_id": "CAFE_TOOL_019", "score": 0.20, "job": "cafe"}]
    plain = decide(results)
    assert plain["reason"] == "accepted"
    gated = decide(results, sentence="문을 닫으세요", query="문을 닫으세요")
    assert gated["reason"] == "frame_mismatch"
    assert gated["match"] is None
    assert [c["asset_id"] for c in gated["candidates"]] == ["CAFE_033", "CAFE_TOOL_019"]
    ok = decide(results, sentence="컵 뚜껑을 닫으세요", query="컵 뚜껑을 닫으세요")
    assert ok["reason"] == "accepted"


def test_frame_mismatch_reaches_api_as_candidate_choice():
    # 서비스 계약(backend·frontend)의 reason 값은 그대로 둔다 — '후보를 보여 주고 사람이 고름'
    # 이라는 화면 동작이 low_margin과 같으므로 그 값으로 내보낸다.
    from unittest import mock
    fake = {"match": None, "reason": "frame_mismatch", "margin": 0.3, "embedding": False,
            "candidates": [{"asset_id": "CAFE_033", "group_id": "CAFE_033", "job": "cafe",
                            "asset_type": "action", "label": "컵에 뚜껑을 닫는다",
                            "image_url": "/api/aac/images/x.png", "score": 0.5}]}
    with mock.patch("symbols.search_for_step_detailed", return_value=fake):
        s = symbols.map_symbols(["문"], {"sentence": "문을 닫으세요"}).symbols[0]
    assert s.reason == "low_margin"
    assert s.needs_fallback is True
    assert [c.asset_id for c in s.candidates] == ["CAFE_033"]
