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
    "assembly": ("assembly", "조립", "제조", "부품", "생산", "조립원"),
    "cafe": ("cafe", "카페", "커피", "음료", "바리스타"),
    "cleaning": ("cleaning", "청소", "세탁", "세차", "환경미화", "미화"),
    "packaging": ("packaging", "포장", "패킹", "박스포장", "포장원"),
    "retail": ("retail", "리테일", "마트", "대형마트", "매장", "소매", "진열", "피킹", "계산", "편의점"),
}


def infer_job_text(text: str) -> str:
    """업종/환경 텍스트에서 canonical job을 보수적으로 추정한다."""
    norm = str(text or "").lower()
    scored: list[tuple[int, str]] = []
    for job, aliases in JOB_ALIASES.items():
        count = sum(1 for alias in aliases if alias.lower() in norm)
        if count:
            scored.append((count, job))
    if not scored:
        return "unknown"
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[0][1]
