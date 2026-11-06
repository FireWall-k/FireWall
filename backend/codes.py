"""사업장 코드(workplace_code) 생성·정규화.

근로자 로그인은 "사업장 코드 + 접속 코드"다. 접속 코드는 사업장 안에서만 unique이므로 사업장을
먼저 정해야 근로자를 찾을 수 있다. 사업장 코드는 기기에 한 번 저장해 두고(프론트 localStorage)
근로자는 자기 접속 코드만 누른다. 그래서 사업주가 근로자 기기에 한 번 옮겨 적기 쉬워야 한다.
- 대문자 + 숫자 6자리. 0/O, 1/I는 옮겨 적다 헷갈리므로 생성에 쓰지 않는다(32문자 → 약 10억 가지).
- 서버가 만든다. 사업주가 직접 정하게 하면 "이 코드는 이미 있음"이 다른 사업장의 존재를 알려 준다.
"""
from __future__ import annotations

import re
import secrets

WORKPLACE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
WORKPLACE_CODE_LENGTH = 6


def new_workplace_code() -> str:
    # 충돌 확률은 사업장 수천 개 기준으로도 무시할 만하고, 겹치면 DB unique 제약이 막는다.
    return "".join(secrets.choice(WORKPLACE_CODE_ALPHABET) for _ in range(WORKPLACE_CODE_LENGTH))


def normalize_workplace_code(raw: str) -> str:
    """입력 정규화: 앞뒤·중간 공백과 하이픈을 빼고 대문자로. 'demo-01', ' demo01 '도 같은 코드다."""
    return re.sub(r"[\s-]+", "", raw or "").upper()
