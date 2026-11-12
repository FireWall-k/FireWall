"""한 줄 이름(직무 제목·사업장 이름)을 정리하는 공용 규칙.

- 제어 문자(C0·DEL·C1, 줄·문단 구분자)는 공백 하나로 바꾼다(목록·근로자 화면 이름은 한 줄이다).
- 화면에 보이지 않는 글자(폭 없는 공백, 글자 방향 바꾸기, BOM, 한글 채움 문자 등)는 지운다.
- 보이는 글자가 하나도 없으면 빈 이름으로 본다(has_visible).
"""
from __future__ import annotations

import re
import unicodedata

# 줄바꿈·탭 같은 제어 문자(유니코드 Cc 전부: C0·DEL·C1, 그리고 줄·문단 구분자. 연달아 있으면 한 덩어리)를 찾는다.
CONTROL_RUN = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]+")
# 화면에 보이지 않는 글자(폭 없는 공백, 글자 방향 바꾸기, BOM, 한글 채움 문자 등)는 지운다.
# 이모지 등에 필요한 폭 없는 이음(U+200C·U+200D)은 남기되, 그것만 남은 이름은 아래 has_visible이 막는다.
INVISIBLE = re.compile(
    r"[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b\u200e\u200f\u202a-\u202e"
    r"\u2060-\u206f\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff0-\ufff8]+"
)
# 범주가 기호(So)라 형식 문자로 걸리지 않지만 화면에서 빈칸으로 보이는 글자(점자 빈칸 U+2800).
BLANK_LOOKING = frozenset("\u2800")


def clean_one_line(raw: str) -> str:
    """제어 문자는 공백 하나로, 보이지 않는 글자는 지우고 앞뒤 공백을 뗀다."""
    return INVISIBLE.sub("", CONTROL_RUN.sub(" ", raw)).strip()


def has_visible(text: str) -> bool:
    """공백·형식 문자(Cf, 폭 없는 이음 포함)·빈칸처럼 보이는 글자(점자 빈칸)만으로 된 글이 아닌지 본다."""
    return any(not ch.isspace() and ch not in BLANK_LOOKING and unicodedata.category(ch) != "Cf"
               for ch in text)
