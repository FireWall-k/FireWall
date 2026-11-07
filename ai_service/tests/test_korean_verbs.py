"""P3 동사 원형 추출 — 보조 용언·구어/연결 어미·문장 끝 동사 우선·불규칙 활용·인덱스 원형 보정.

형태소 분석기 없이 '닫힌 사전 + 활용 규칙'(korean_verbs)으로 푼다. 여기 문장들은 특정 시험지
문장이 아니라 각 언어 현상의 대표 예다.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import korean_verbs as K  # noqa: E402
from local_aac import (  # noqa: E402
    _is_verb_word, _normalize_lemma, _verb_analyzer, _verb_lemmas, load_assets,
)

_EVAL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval")


# ---- 활용형 몸통(-아/-어) -----------------------------------------------------------

@pytest.mark.parametrize("stem,form", [
    ("닦", "닦아"), ("꺼내", "꺼내"), ("채우", "채워"), ("쓰", "써"), ("모으", "모아"),
    ("문지르", "문질러"), ("자르", "잘라"), ("싣", "실어"), ("줍", "주워"), ("붓", "부어"),
    ("놓", "놔"), ("내리", "내려"), ("하", "해"), ("보", "봐"), ("되", "돼"), ("빼", "빼"),
])
def test_a_forms_cover_irregular_conjugation(stem, form):
    assert form in K.a_forms(stem)


# ---- 보조 용언: '-어 주다/드리다/두다/오다/놓다/보다'는 본동사만 남긴다 ------------------

@pytest.mark.parametrize("text,expected", [
    ("원두를 갈아주세요", {"갈다"}),
    ("욕조 안을 샤워기로 헹궈 주세요", {"헹구다"}),
    ("고객 쿠폰에 도장을 하나 찍어 주세요", {"찍다"}),
    ("케이크 상자를 미리 접어 두세요", {"접다"}),
    ("시럽이 비었으면 가득 채워 두세요", {"채우다"}),
    ("선반에서 상품을 꺼내 오세요", {"꺼내다"}),
    ("엘리베이터 버튼을 티슈로 훔쳐 주세요", {"훔치다"}),
])
def test_auxiliary_verbs_do_not_replace_main_verb(text, expected):
    lemmas = _verb_lemmas(text)
    assert expected <= lemmas
    # '주세요'의 '주다', '두세요'의 '두다', '오세요'의 '오다'는 할 일이 아니다.
    assert not lemmas & {"주다", "두다", "오다"}


def test_attached_aux_compound_also_yields_main_verb():
    # 사전에 붙여 쓴 '눌러주다'가 있어도 다른 그림의 원형 '누르다'와 만나야 한다.
    assert "누르다" in _verb_lemmas("탬퍼로 원두를 눌러주세요")


# ---- '드려요/드리세요': 들다(ㄹ탈락 '드-')가 아니라 주다의 높임 ----------------------

@pytest.mark.parametrize("text", ["손님에게 음료를 드리세요", "사장님께 서류를 드려요"])
def test_deurida_is_honorific_give_not_lift(text):
    lemmas = _verb_lemmas(text)
    assert "주다" in lemmas
    assert "들다" not in lemmas


def test_carry_and_give_means_deliver():
    # '가져다 드리다'는 한 낱말 '가져다주다'(옮겨다 주다) — 할 일은 전달이다.
    lemmas = _verb_lemmas("주문한 음식을 자리에 가져다 드려요")
    assert "전달하다" in lemmas
    assert not lemmas & {"주다", "가지다"}


def test_carry_before_other_verb_is_adverbial():
    # '갖다 놓다'의 할 일은 놓는 것이다.
    assert _verb_lemmas("통을 작업대 위로 가져다 놓으세요") == {"놓다"}


# ---- 해요체·연결 어미(-요/-고/-서/-면서/-어) ---------------------------------------

@pytest.mark.parametrize("text,lemma", [
    ("휴지통을 봉투에 모아요", "모으다"),
    ("바퀴를 솔로 박박 문질러요", "문지르다"),
    ("상자를 카트에 실어요", "싣다"),
    ("셔터를 내려요", "내리다"),
    ("도시락을 앞으로 빼요", "빼다"),
    ("이불을 개세요", "개다"),
    ("수레에 택배를 싣고 가세요", "싣다"),
    ("휴지통을 비워서 봉투에 모아요", "비우다"),
    ("물을 뿌리면서 닦으세요", "뿌리다"),
    ("집게로 빵을 집어 봉투에 담아요", "집다"),
])
def test_colloquial_and_connective_endings(text, lemma):
    assert lemma in _verb_lemmas(text)


# ---- 문장 끝 서술어가 중심, 조건·관형·과거·피동은 할 일이 아니다 ----------------------

def test_final_predicate_is_head_and_earlier_clause_is_side():
    roles = _verb_analyzer().lemma_roles("위 뚜껑을 덮고 꾹 눌러 맞추세요")
    assert roles["맞추다"] == "head"
    assert roles["누르다"] == "head"  # 연결 어미 없이 이어진 '-어'는 뒤 동사와 한 동작
    assert roles["덮다"] == "side"


@pytest.mark.parametrize("text,excluded,kept", [
    ("손님이 찾으면 그 코너로 안내하세요", "찾다", "안내하다"),       # -면 조건절
    ("다 붙인 박스를 팔레트 위에 쌓아요", "붙이다", "쌓다"),          # -ㄴ 관형절
    ("바닥에 떨어진 쓰레기를 주우세요", "떨다", "줍다"),             # -어지다 상태 변화
    ("화장지가 떨어졌으면 새로 채우세요", "떨어지다", "채우다"),       # 과거형 조건
    ("들어온 물건 상자를 창고로 옮겨요", "들다", "옮기다"),           # 사전 밖 합성어 보호
    ("점심 먹고 오면 손을 씻으세요", "먹다", "씻다"),                # -고가 뒤 조건절을 따름
])
def test_subordinate_clause_verbs_are_not_tasks(text, excluded, kept):
    lemmas = _verb_lemmas(text)
    assert kept in lemmas
    assert excluded not in lemmas


# ---- 명사·부사·수사는 동사가 아니다 ----------------------------------------------

@pytest.mark.parametrize("text,wrong", [
    ("진열대에 가지런히 놓으세요", "가지다"),    # 부사
    ("가벼운 상자를 선반에 놓으세요", "가다"),   # 형용사 관형형의 첫 글자
    ("세탁기 시작 버튼을 누르세요", "세다"),     # '누르세요'를 '누르+세요'로만 읽는다
    ("영수증을 세 장 뽑으세요", "세다"),         # 수사 '세'
])
def test_non_verb_words_do_not_yield_lemmas(text, wrong):
    assert wrong not in _verb_lemmas(text)


@pytest.mark.parametrize("word,is_verb", [
    ("쓰레기를", False), ("가지런히", False), ("청소하세요", True), ("쌓으세요", True),
])
def test_is_verb_word(word, is_verb):
    assert _is_verb_word(word) is is_verb


# ---- 사전 밖 'X하다' ---------------------------------------------------------------

@pytest.mark.parametrize("text,lemma", [
    ("작업 지시서를 복사하세요", "복사하다"),
    ("컵을 깨끗이 설거지하세요", "설거지하다"),
])
def test_generic_hada_verbs(text, lemma):
    assert lemma in _verb_lemmas(text)


def test_light_verb_hada_alone_is_not_a_task():
    # "체크를 해요"의 '하다'는 동작을 가르지 못한다.
    assert "하다" not in _verb_lemmas("출근 체크를 해요")


# ---- 인덱스 원형 보정(데이터는 그대로, 읽을 때 맞춘다) ------------------------------

@pytest.mark.parametrize("raw,lemma", [
    ("갠다", "개다"), ("건다", "걸다"), ("빤다", "빨다"), ("놓는다", "놓다"), ("실다", "싣다"),
])
def test_index_conjugated_forms_normalize_to_lemma(raw, lemma):
    assert _normalize_lemma(raw) == lemma


def test_lemma_like_shin_da_is_kept():
    # '신다'는 '-ㄴ다' 평서형처럼 보이지만 원형이다.
    assert _normalize_lemma("신다") == "신다"


def test_frame_verb_deutda_is_reconciled_to_label_verb():
    """인덱스가 '든다'(들다)를 '듣다'로 적은 그림 — 두 동사는 '들어'가 같다(ㄷ 불규칙)."""
    by_id = {a["id"]: a for a in load_assets()}
    lifts = [a for a in by_id.values() if a["label"].endswith(" 든다")]
    assert lifts, "라벨이 '…든다'인 그림이 있어야 이 보정을 시험할 수 있다"
    for asset in lifts:
        assert asset["_frame"].get("verb") != "듣다", asset["id"]
        assert "들다" in asset["_lemmas"], asset["id"]


def test_frame_verb_kept_when_not_a_shared_conjugation():
    # 라벨 동사와 활용형이 겹치지 않는 불일치(동의어로 적은 경우)는 건드리지 않는다.
    from local_aac import _reconcile_frame_verb
    assert _reconcile_frame_verb("착용하다", "앞치마를 입는다") == "착용하다"
    assert _reconcile_frame_verb("듣다", "상자를 양손으로 든다") == "들다"


# ---- 개발셋 전체 회귀 가드: 보조 용언만 남는 문장·동사 없는 문장 ----------------------

def _dev_sentences():
    with open(os.path.join(_EVAL_DIR, "dev_set.json"), encoding="utf-8") as f:
        return [c["sentence"] for c in json.load(f)["cases"]]


def test_no_sentence_yields_only_polite_juda():
    # 예전 방식은 '…해 주세요' 류 15문장에서 '주다'만 뽑았다. 실제로 주는 동작('드려요')은 뺀다.
    only_give = [s for s in _dev_sentences()
                 if _verb_lemmas(s) == {"주다"} and not any(w in s for w in ("드리", "드려"))]
    assert only_give == []


def test_sentences_without_any_lemma_are_rare():
    # 예전 방식은 개발셋 19문장에서 동사를 하나도 못 찾았다(모아요·문질러요·실어 등).
    empty = [s for s in _dev_sentences() if not _verb_lemmas(s)]
    assert len(empty) <= 6, empty
