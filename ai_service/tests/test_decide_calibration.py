"""P5 재보정: 쌍둥이 그림 묶음, 상대 여유 옵션, 임베딩 없는 경로의 기본 임계값.

decide()는 1·2위의 점수 차로 "고를 수 있는가"를 판단한다. 그런데 2위가 1위와 사실상 같은
그림이면 그 차는 위험 신호가 아니다 — 어느 쪽이 나와도 같은 카드다. 그런 쌍은 한 묶음으로 보고,
여유는 묶음 밖의 첫 경쟁자와 잰다.
"""
import pytest

from local_aac import decide


def _r(asset_id: str, score: float, job: str, label: str) -> dict:
    return {"asset_id": asset_id, "score": score, "job": job, "label": label}


@pytest.fixture(autouse=True)
def _plain_defaults(monkeypatch):
    # 개발자 셸의 값이 기본값 검증을 흐리지 않게 한다.
    for key in ("AAC_MATCH_THRESHOLD", "AAC_MATCH_MIN_MARGIN", "AAC_MATCH_MARGIN_MODE",
                "AAC_MATCH_MIN_REL_MARGIN", "AAC_MATCH_CROSS_JOB_TWINS"):
        monkeypatch.delenv(key, raising=False)


# ---------- 쌍둥이 묶음 ----------

_CROSS_JOB_PAIR = [
    _r("ASSEMBLY_AUX_011", 0.40, "assembly", "안전화를 신는다"),
    _r("DELIVERY_038", 0.399, "delivery", "안전화를 신는다"),
    _r("CAFE_002", 0.30, "cafe", "앞치마를 착용한다"),
]


def test_cross_job_twins_are_not_grouped_by_default():
    """직무가 다른 그림은 기본으로 묶지 않는다 — 복장·배경이 달라 사람이 골라야 할 수 있다
    (2026-09-22 사용자 결정, eval/README.md)."""
    assert decide(_CROSS_JOB_PAIR)["reason"] == "low_margin"


def test_cross_job_twin_with_same_label_and_frame_does_not_block(monkeypatch):
    """옵션을 켜면 직무만 다르고 라벨·frame이 같은 그림(안전화를 신는다)은 서로 여유를 깎지 않는다."""
    monkeypatch.setenv("AAC_MATCH_CROSS_JOB_TWINS", "on")
    results = [
        _r("ASSEMBLY_AUX_011", 0.40, "assembly", "안전화를 신는다"),
        _r("DELIVERY_038", 0.399, "delivery", "안전화를 신는다"),
        _r("CAFE_002", 0.30, "cafe", "앞치마를 착용한다"),
    ]
    d = decide(results)
    assert d["reason"] == "accepted"
    assert d["match"]["asset_id"] == "ASSEMBLY_AUX_011"
    # 보고하는 여유도 묶음 밖 첫 경쟁자 기준이다.
    assert d["margin"] == pytest.approx(0.10)


def test_cross_job_same_frame_but_different_label_is_not_a_twin(monkeypatch):
    """frame만 같고 라벨이 다르면(밀대로 바닥 닦기) 직무가 다른 그림을 같다고 보지 않는다.

    다른 직무 그림은 복장·배경이 다르다. 라벨까지 같아야 '같은 그림을 직무별로 다시 등록'한
    경우라고 볼 수 있다.
    """
    monkeypatch.setenv("AAC_MATCH_CROSS_JOB_TWINS", "on")
    results = [
        _r("CAFE_081", 0.40, "cafe", "바닥을 밀대로 닦는다"),
        _r("CLEANING_018", 0.399, "cleaning", "밀대로 바닥을 닦는다"),
    ]
    assert decide(results)["reason"] == "low_margin"


def test_cross_job_object_cards_with_same_label_are_twins(monkeypatch):
    """동사 없는 사물 카드도 라벨·frame이 같으면 같은 그림이다(앞치마 카드)."""
    monkeypatch.setenv("AAC_MATCH_CROSS_JOB_TWINS", "on")
    results = [
        _r("CAFE_TOOL_012", 0.40, "cafe", "앞치마"),
        _r("DISPLAY_TOOL_005", 0.40, "display", "앞치마"),
        _r("CAFE_002", 0.30, "cafe", "앞치마를 착용한다"),
    ]
    assert decide(results)["reason"] == "accepted"


def test_twin_does_not_hide_a_close_third_candidate():
    """쌍둥이를 건너뛰고도 다음 경쟁자가 바짝 붙어 있으면 여전히 고를 수 없다.

    예전 규칙은 2위가 쌍둥이면 3위를 보지 않고 채택했다 — 진짜 경합을 놓친다.
    """
    results = [
        _r("SERVING_020", 0.40, "serving", "빈 접시를 쟁반에 담는다"),
        _r("SERVING_021", 0.399, "serving", "빈 접시들을 쟁반에 담는다"),
        _r("SERVING_010", 0.395, "serving", "테이블을 행주로 닦는다"),
    ]
    assert decide(results)["reason"] == "low_margin"


def test_only_twins_left_means_no_competitor():
    """후보가 쌍둥이뿐이면 경쟁자가 없다 — 후보 하나일 때와 같다."""
    results = [
        _r("SERVING_020", 0.40, "serving", "빈 접시를 쟁반에 담는다"),
        _r("SERVING_021", 0.399, "serving", "빈 접시들을 쟁반에 담는다"),
    ]
    assert decide(results)["reason"] == "accepted"


# ---------- 상대 여유 옵션 ----------

def test_relative_margin_mode_scales_with_top_score(monkeypatch):
    """상대 여유 (s1−s2)/s1: 점수가 높을수록 같은 절대 차가 덜 확실하다."""
    monkeypatch.setenv("AAC_MATCH_MARGIN_MODE", "relative")
    monkeypatch.setenv("AAC_MATCH_MIN_REL_MARGIN", "0.05")

    high = [{"asset_id": "A", "score": 0.50}, {"asset_id": "B", "score": 0.48}]  # 절대 0.02, 상대 0.04
    assert decide(high)["reason"] == "low_margin"
    low = [{"asset_id": "A", "score": 0.25}, {"asset_id": "B", "score": 0.237}]  # 절대 0.013, 상대 0.052
    assert decide(low)["reason"] == "accepted"


def test_unknown_margin_mode_falls_back_to_absolute(monkeypatch):
    """오타 난 설정값 하나로 요청이 실패하면 안 된다 — 기본(절대 여유)으로 판정한다."""
    monkeypatch.setenv("AAC_MATCH_MARGIN_MODE", "relativ")
    close = [{"asset_id": "A", "score": 0.50}, {"asset_id": "B", "score": 0.49}]
    assert decide(close)["reason"] == "low_margin"
    wide = [{"asset_id": "A", "score": 0.50}, {"asset_id": "B", "score": 0.47}]
    assert decide(wide)["reason"] == "accepted"


# ---------- 임베딩 없는 경로 기본값(P5 스윕 결과 0.215 / 0.018) ----------

def test_plain_defaults_after_recalibration():
    just_above = [{"asset_id": "A", "score": 0.216}, {"asset_id": "B", "score": 0.10}]
    assert decide(just_above)["reason"] == "accepted"
    below = [{"asset_id": "A", "score": 0.214}, {"asset_id": "B", "score": 0.10}]
    assert decide(below)["reason"] == "low_score"

    m018 = [{"asset_id": "A", "score": 0.50}, {"asset_id": "B", "score": 0.4815}]  # 여유 0.0185
    assert decide(m018)["reason"] == "accepted"
    m017 = [{"asset_id": "A", "score": 0.50}, {"asset_id": "B", "score": 0.483}]  # 여유 0.017
    assert decide(m017)["reason"] == "low_margin"


def test_embedding_thresholds_unchanged():
    """임베딩 경로는 키 없는 환경에서 잴 수 없으므로 이번 재보정 범위 밖이다(0.35 / 0.02)."""
    assert decide([{"asset_id": "A", "score": 0.34}, {"asset_id": "B", "score": 0.1}],
                  embedding=True)["reason"] == "low_score"
    assert decide([{"asset_id": "A", "score": 0.50}, {"asset_id": "B", "score": 0.4815}],
                  embedding=True)["reason"] == "low_margin"
