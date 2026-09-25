"""AAC 검색에서 공통으로 사용하는 직무/행동 분류 체계.

LLM 질의 분해(action_type)와 aac_index.json의 verb_class가 반드시 같은 축을
사용하도록 한 곳에서 정의한다. 세부 행동 차이는 frame.verb가 담당하고,
ActionType은 직무 전체에서 공유할 수 있는 넓은 행동군만 유지한다.
"""
from __future__ import annotations

from typing import Literal, get_args

JobType = Literal[
    "assembly",
    "cafe",
    "cleaning",
    "packaging",
    "retail",
    "serving",
    "display",
    "delivery",
    "gas",
    "unknown",
]

ActionType = Literal[
    "observe",   # 보다/확인/검사/비교/세다
    "move",      # 가져오다/옮기다/놓다/꺼내다/전달하다
    "sort",      # 분류/나누다/구분/정리
    "stack",     # 쌓다/적재하다
    "pack",      # 담다/포장/밀봉/접다
    "clean",     # 닦다/씻다/쓸다/치우다/버리다
    "wear",      # 사람이 보호구/복장을 착용하거나 벗는 동작
    "operate",   # 버튼/스위치/기계/일반 도구 조작
    "assemble",  # 부품 결합/끼움/연결/체결/정렬/부착/분리/재조립
    "other",
]

VALID_JOBS: set[str] = set(get_args(JobType))
VALID_ACTION_TYPES: set[str] = set(get_args(ActionType))

JOB_ALIASES: dict[str, tuple[str, ...]] = {
    "assembly": (
        "assembly",
        "조립",
        "제조",
        "부품",
        "생산",
    ),
    "cafe": (
        "cafe",
        "카페",
        "커피",
        "음료",
        "바리스타",
    ),
    "cleaning": (
        "cleaning",
        "청소",
        "세탁",
        "환경미화",
        "미화",
    ),
    "packaging": (
        "packaging",
        "포장",
        "패킹",
        "박스포장",
    ),
    "retail": (
        "retail",
        "리테일",
        "마트",
        "매장",
        "소매",
        "피킹",
        "계산",
        "편의점",
    ),
    "serving": (
        "serving",
        "서빙",
        "배식",
        "식당",
        "음식점",
        "홀서빙",
    ),
    "display": (
        "display",
        "진열",
        "상품진열",
        "매대",
        "진열대",
    ),
    "delivery": (
        "delivery",
        "배송",
        "배달",
        "택배",
        "배송원",
        "배달원",
    ),
    "gas": (
        "gas",
        "주유",
        "주유소",
        "주유원",
        "주유작업",
        # 세차 그림(차체 물 뿌리기·타이어 세척 등)은 gas 직무에 있다. 예전에는 "세차"가
        # cleaning 별칭이라 "주유소 세차장"이 청소로 분류되어 세탁기 그림이 채택됐다.
        "세차",
        "세차장",
    ),
}

# 여러 직무에 두루 쓰이는 말은 절반만 센다. "매장 상품 진열"이 마트(매장) 1점, 진열 1점으로
# 동점이 되어 이름순으로 마트가 되던 문제 — 진열 그림이 있는데도 마트로만 잡혔다.
ALIAS_WEIGHT = {"매장": 0.5}


def infer_job_text(text: str) -> str:
    """업종/환경 텍스트에서 canonical job을 보수적으로 추정한다."""
    norm = str(text or "").lower()
    scored: list[tuple[float, str]] = []
    for job, aliases in JOB_ALIASES.items():
        count = sum(ALIAS_WEIGHT.get(alias, 1.0) for alias in aliases if alias.lower() in norm)
        if count:
            scored.append((count, job))
    if not scored:
        return "unknown"
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[0][1]
