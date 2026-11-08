"""P6 한 문장 두 동작 — 근로자가 할 '주 동작'을 고른다(규칙 폴백 경로).

여기 문장들은 시험지 문장이 아니라 각 언어 현상의 대표 예다.

- 끝 서술어가 이동·자세 동사(가다·오다·서다·타다·이동하다)면 그 앞 절 동작이 할 일이다.
  "상자를 싣고 엘리베이터를 타세요"의 일은 싣기이고, 타기는 그다음 이동이다.
- '-어 달라고 (말)하다'의 앞 동사는 상대(손님)에게 바라는 동작이라 근로자의 할 일이 아니다.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from local_aac import _QueryFeatures, _verb_analyzer  # noqa: E402


@pytest.mark.parametrize("text,task,motion", [
    ("카트에 상자를 싣고 엘리베이터를 타세요", "싣다", "타다"),
    ("빈 카트를 창고 앞까지 밀고 가세요", "밀다", "가다"),
    ("위생모를 쓰고 계산대 앞에 서세요", "쓰다", "서다"),
    ("쟁반을 들고 주방으로 이동하세요", "들다", "이동하다"),
])
def test_motion_head_hands_head_role_to_task_verb(text, task, motion):
    roles = _verb_analyzer().lemma_roles(text)
    assert roles.get(task) == "head"
    assert roles.get(motion) == "side"


def test_motion_only_sentence_keeps_its_head():
    # 할 일이 이동뿐이면 그대로 둔다(그림이 있으면 이동 그림이 맞다).
    assert _verb_analyzer().lemma_roles("창고에 가세요") == {"가다": "head"}


def test_motion_in_earlier_clause_stays_side():
    # 이동이 앞 절이면 원래 규칙 그대로 — 끝 서술어가 할 일이다.
    roles = _verb_analyzer().lemma_roles("휴게실에 가서 물을 마셔요")
    assert roles.get("가다") == "side"
    assert roles.get("마시다") == "head"


def test_non_motion_head_is_unchanged():
    roles = _verb_analyzer().lemma_roles("책상 위를 정리하고 닦으세요")
    assert roles == {"정리하다": "side", "닦다": "head"}


def test_query_features_follow_reassigned_head():
    qf = _QueryFeatures("카트에 상자를 싣고 엘리베이터를 타세요")
    assert qf.head_lemmas == {"싣다"}
    assert "타다" in qf.lemmas
    assert "싣다" in qf.tokens and "타다" not in qf.tokens


@pytest.mark.parametrize("text,excluded,kept", [
    ("손님께 창문을 닫아 달라고 말해요", "닫다", "말하다"),
    ("손님에게 카드를 꽂아 달라고 부탁하세요", "꽂다", "부탁하다"),
])
def test_requested_action_of_listener_is_not_a_task(text, excluded, kept):
    roles = _verb_analyzer().lemma_roles(text)
    assert excluded not in roles
    assert roles.get(kept) == "head"
