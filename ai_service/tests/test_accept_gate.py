"""P2 채택 게이트 — 명사에서 동사 뽑기 중지, 반대말 확대, 대상 불일치 시 자동 채택 보류."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import symbols  # noqa: E402
from local_aac import (  # noqa: E402
    _object_conflict, _query_objects, _query_topics, _verb_antonym_penalty, _verb_lemmas,
    decide, infer_job, load_assets,
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
    # 채우다(빈 곳에 넣는다)와 꺼내다(밖으로 뺀다)는 넣다/꺼내다와 같은 방향 쌍이다.
    assert _verb_antonym_penalty(asset("꺼내다"), {"채우다"}) < 1.0
    assert _verb_antonym_penalty(asset("채우다"), {"꺼내다"}) < 1.0
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


def test_generic_asset_object_covers_only_same_job():
    # 그림 대상이 '상품/제품' 같은 일반 명사면 같은 직무 문장의 구체 대상(쿠키, 빵)을 포함할 수 있다.
    generic = {"id": "X", "job": "packaging", "label": "상품을 봉투에 넣는다",
               "_norm": "상품을 봉투에 넣는다", "_kw_norm": "", "_frame": {"object": "상품"}}
    q = "쿠키를 봉투에 넣으세요"
    assert _object_conflict(generic, q, q, job="packaging") is False
    # 다른 직무의 일반 명사는 '그 일터의 물건'이라 이 문장의 대상을 덮지 않는다
    # (조립 그림의 '부품'이 주유 노즐을 대신하지 않는다). 직무를 모르면 덮는다고 볼 근거가 없다.
    assert _object_conflict(generic, q, q, job="assembly") is True
    assert _object_conflict(generic, q, q) is True
    # 그래도 문장 대상이 그림 라벨에 나오면 일치다.
    assert _object_conflict(generic, "상품을 봉투에 넣으세요", "상품을 봉투에 넣으세요",
                            job="assembly") is False


def test_cross_job_generic_card_is_not_auto_accepted():
    by = _by_id()
    asm = next(a for a in by.values() if a.get("job") == "assembly"
               and (a.get("_frame") or {}).get("object") == "부품"
               and "넣" in a.get("label", ""))
    q = "주유기 노즐을 끝까지 넣어요"
    assert _object_conflict(asm, q, q, job="gas") is True
    assert _object_conflict(asm, q, q, job="assembly") is False


def test_position_noun_is_not_the_object():
    # '책상 위를'에서 을/를이 붙은 '위'는 자리일 뿐이고 대상은 '책상'이다.
    assert _query_objects("책상 위를 마른 걸레로 닦으세요.") == {"책상"}
    assert _query_objects("선반의 안쪽을 닦아요") == {"선반"}
    assert _query_objects("컵을 씻으세요") == {"컵"}
    # 앞 명사가 없으면 대상을 모른다 — 위치 명사를 대상으로 쓰지 않는다.
    assert _query_objects("위를 닦으세요") == set()


def test_position_noun_does_not_satisfy_object_gate():
    # 예전에는 문장 대상 '위'가 그림의 '매대 위'에 나와 일치로 통과했다.
    by = _by_id()
    shelf = next(a for a in by.values()
                 if (a.get("_frame") or {}).get("object") == "먼지" and "매대 위" in a["label"])
    q = "책상 위를 마른 걸레로 닦으세요."
    assert _object_conflict(shelf, q, q) is True
    q2 = "매대 위를 마른 걸레로 닦으세요."
    assert _object_conflict(shelf, q2, q2) is False


def test_topic_marked_object_is_used_when_no_object_particle():
    assert _query_topics("계란은 깨지지 않게 맨 위에 올려요.") == {"계란"}
    # 때·순서를 가리키는 말, 부사격 조사 뒤의 '는', 관형형 용언('모르는 것')은 대상이 아니다.
    assert _query_topics("오늘은 바닥을 닦아요") == set()
    assert _query_topics("냉장고에는 넣지 마세요") == set()
    assert _query_topics("모르는 것이 생기면 물어보세요") == set()
    assert _query_topics("넣지는 마세요") == set()
    # 일반 명사('상품은')는 대상으로 쓰지 않는다 — 어느 그림의 대상과도 겹칠 수 있다.
    assert _query_topics("떨어진 상품은 주워 주세요") == set()
    box = {"id": "Y", "job": "delivery", "label": "깨지기 쉬운 상자를 맨 위에 올린다",
           "_norm": "깨지기 쉬운 상자를 맨 위에 올린다", "_kw_norm": "",
           "_frame": {"object": "상자"}}
    q = "계란은 깨지지 않게 맨 위에 올려요."
    assert _object_conflict(box, q, q) is True
    # 을/를 목적어가 있으면 그것이 우선이다.
    q2 = "상자를 맨 위에 올려요. 계란은 조심하세요."
    assert _object_conflict(box, q2, q2) is False


def test_business_type_names_infer_job():
    assert infer_job({"business_type": "비즈니스 호텔(객실 정비)"}) == "cleaning"
    assert infer_job({"business_type": "오피스 빌딩 관리"}) == "cleaning"
    assert infer_job({"business_type": "고깃집"}) == "serving"
    assert infer_job({"business_type": "동네 슈퍼마켓"}) == "retail"
    assert infer_job({"business_type": "옷가게"}) == "display"


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
