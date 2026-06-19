"""AI 분해기 단위 테스트 — 특히 쉼표 분할 회귀를 막는다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decompose import decompose  # noqa: E402


def _sentences(raw: str) -> list[str]:
    return [s.sentence for s in decompose(raw, {}).steps]


def test_sample_task_splits_into_four_clean_steps():
    raw = ("택배 상자를 크기별로 분류하고, 큰 상자는 A구역으로 옮겨주세요. "
           "그리고 5개씩 쌓아주세요. 마지막에 수량을 확인하세요.")
    steps = _sentences(raw)
    assert len(steps) == 4, steps
    assert "분류" in steps[0]
    assert "옮겨" in steps[1] or "옮기" in steps[1]
    assert "쌓" in steps[2]
    assert "확인" in steps[3]
    # '그리고'가 단계 문장 안에 남으면 안 된다.
    assert all("그리고" not in s for s in steps)


def test_list_commas_are_not_split():
    # 나열형 쉼표는 한 단계로 유지되어야 한다(기존 버그: 3조각으로 깨짐).
    steps = _sentences("사과, 배, 귤을 담으세요.")
    assert len(steps) == 1, steps
    assert "사과" in steps[0] and "배" in steps[0] and "귤" in steps[0]


def test_sequential_hago_comma_splits():
    steps = _sentences("재료를 씻고, 그릇에 담으세요.")
    # "씻고," 는 순차 연결어미+쉼표 → 분할
    assert len(steps) == 2, steps


def test_order_is_sequential_and_starts_at_one():
    result = decompose("문을 열고, 불을 켜세요. 그리고 청소를 하세요.", {})
    orders = [s.order for s in result.steps]
    assert orders == list(range(1, len(orders) + 1))


def test_action_type_detected():
    result = decompose("상자를 옮겨주세요.", {})
    assert result.steps[0].action_type == "move"


def test_single_sentence_no_connective():
    steps = _sentences("바닥을 깨끗하게 닦으세요")
    assert len(steps) == 1, steps


def test_adjective_go_is_not_split():
    # 형용사 연결 '~하고,'는 나열로 보고 한 단계로 유지(과분할 회귀 방지).
    steps = _sentences("작업대를 깨끗하고, 안전하게 정리하세요.")
    assert len(steps) == 1, steps


def test_verb_go_still_splits_after_adjective_fix():
    # 동작 동사 '~하고,'는 여전히 분할되어야 한다.
    steps = _sentences("상자를 분류하고, 선반에 올리세요.")
    assert len(steps) == 2, steps


def test_mixed_adjective_and_verb():
    steps = _sentences("그릇을 깨끗하고, 빠르게 씻고, 선반에 두세요.")
    # '깨끗하고,'(형용사)는 유지, '씻고,'(동사)는 분할 → 2단계
    assert len(steps) == 2, steps
    assert "씻" in steps[0]
    assert "선반" in steps[1]
