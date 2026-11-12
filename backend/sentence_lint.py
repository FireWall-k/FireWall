"""단계 문장 점검(2b-1, contract §3.3). 막지 않는 힌트다(편집기 SentenceLint 칩, 보내기 시트 경고).

code는 StepOut.lint와 보내기 점검표(send-check warnings)가 같이 쓴다. 화면 문구는 사업주 화면 copy.ts가 만든다.
- too_long: 공백을 뺀 글자가 20자를 넘음(명세 §6.7 '20자 안팎') → '20자가 넘어요'
- hard_word{from,to}: 어려운 말 사전(hard_words.txt) → '어려운 말: 적재 → 쌓기'
- command_tone: '~하세요'·'~하십시오' 체로 끝남 → '~해요 체로 바꾸기'
'동작이 2개'는 만들지 않는다(편집기는 저장하는 순간 나누고 [되돌리기]를 보여 준다).
규칙만 쓴다(네트워크 호출 없음). 이 모듈은 main을 import하지 않는다.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

MAX_CHARS = 20
_WORDS_FILE = Path(__file__).resolve().parent / "hard_words.txt"
# 끝의 문장 부호·공백을 떼고 본다.
_TAIL_PUNCT_RE = re.compile(r"[\s.!?~…。·,]+$")
_COMMAND_ENDINGS = ("세요", "십시오", "하시오", "시오")


@lru_cache(maxsize=1)
def hard_words() -> tuple[tuple[str, str], ...]:
    """(어려운 말, 쉬운 말) 목록. 파일이 없으면 빈 목록(점검만 빠진다)."""
    try:
        lines = _WORDS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    out = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "→" not in line:
            continue
        src, dst = (part.strip() for part in line.split("→", 1))
        if src and dst:
            out.append((src, dst))
    return tuple(out)


def char_count(sentence: str) -> int:
    return len(re.sub(r"\s+", "", sentence or ""))


def is_too_long(sentence: str) -> bool:
    return char_count(sentence) > MAX_CHARS


def is_command_tone(sentence: str) -> bool:
    tail = _TAIL_PUNCT_RE.sub("", sentence or "")
    return tail.endswith(_COMMAND_ENDINGS)


def lint(sentence: str) -> list[dict]:
    """[{code, from?, to?}] — 문장 순서대로 too_long, hard_word(사전 순서), command_tone."""
    out: list[dict] = []
    if is_too_long(sentence):
        out.append({"code": "too_long"})
    for src, dst in hard_words():
        if src in (sentence or ""):
            out.append({"code": "hard_word", "from": src, "to": dst})
    if is_command_tone(sentence):
        out.append({"code": "command_tone"})
    return out
