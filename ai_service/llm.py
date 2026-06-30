"""LLM 연동 (OpenAI). 추가 의존성 없이 httpx로 직접 호출한다.

설계 원칙(하네스 4원칙과 일치):
- 격리: LLM 호출은 이 파일에만 존재. 교체/제거가 한 곳에서 끝난다.
- 폴백: 키가 없거나 호출이 실패하면 호출부가 규칙 기반으로 떨어진다.
- 검증: 출력(JSON)은 호출부에서 Pydantic 스키마로 반드시 통과시킨다.
- 관측: 호출/실패를 로깅한다.

테스트 이음새: 모든 LLM 호출은 chat_json() 하나를 거친다. 테스트는 이 함수만
목으로 바꾸면 파싱·검증·폴백 로직 전체를 실 네트워크 없이 검증할 수 있다.
"""
from __future__ import annotations

import json
import logging
import os

import httpx

logger = logging.getLogger("ai_harness.llm")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "20"))


def llm_available() -> bool:
    return bool(OPENAI_API_KEY)


def chat_json(system: str, user: str, *, max_tokens: int = 1200) -> dict:
    """OpenAI Chat Completions(JSON 모드) 호출 후 dict로 반환. 실패 시 예외."""
    resp = httpx.post(
        f"{OPENAI_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": max_tokens,
        },
        timeout=LLM_TIMEOUT,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)


# --- 1) 맥락적응 직무 분해 ---------------------------------------------------
_DECOMPOSE_SYSTEM = (
    "당신은 발달장애인 근로자를 위한 직무 분해 전문가입니다. "
    "현장 작업 지시문을 인지부하가 낮은 단계로 나눕니다. 규칙:\n"
    "1) 각 단계는 '하나의 구체적 동작'만 담습니다. 한 문장에 동작이 둘 이상이면 "
    "('담고 부은 다음 닫아') 반드시 단계를 나눕니다.\n"
    "1-1) 원문에 없는 동작을 새로 만들지 마세요. 특히 '보다/확인하다'나 "
    "'가져오다/준비하다' 같은 준비 동작을 임의로 추가하지 않습니다. 지시문에 적힌 "
    "동작만 단계로 만듭니다(예: '테이블을 닦고'는 '테이블을 닦으세요' 한 단계이며, "
    "'테이블을 보세요'·'걸레를 가져오세요'를 덧붙이지 않습니다).\n"
    "2) 문장은 짧고 명확한 한국어 명령형('~하세요/~주세요')으로 씁니다. "
    "**20자 이내**를 지킵니다(길면 더 쪼갭니다).\n"
    "3) 추상 표현 대신 눈에 보이는 대상을 가리킵니다.\n"
    "4) 각 단계에 AAC 그림 검색용 'symbol_query'를 제공합니다. 그 단계에서 "
    "'가장 중요한 대상/동작'을 가리키는 1~3개의 구체적 명사로, **반드시 한국어와 영어를 "
    "함께** 넣습니다(예: ['상자','box'] 또는 ['크기','size']). 추상 동사는 피하고, 단계마다 "
    "초점이 다르면 symbol_query도 다르게 합니다(예: '확인' 단계는 ['확인','check']).\n"
    "5) action_type은 동작에 맞게 고릅니다(가능하면 'other'를 피함): "
    "observe(보다/확인), move(옮기다/넣다/꺼내다), stack(쌓다/적재), "
    "sort(분류/나누다), pack(담다/포장), clean(닦다/청소).\n"
    "6) 위험 요소가 있으면 safety_flags에 한국어로 적습니다(없으면 빈 배열).\n"
    "7) 단계는 최대 10개.\n"
    "출력은 반드시 JSON 한 개. 형식:\n"
    '{"task_title": "짧은 제목", "steps": [{"sentence": "명령형 문장", '
    '"symbol_query": ["상자","box"], "action_type": '
    '"observe|move|stack|sort|pack|clean|other", "safety_flags": []}]}\n'
    "\n예시1 — 입력: '마감 시간에 테이블을 닦고, 컵을 정리한 뒤 쓰레기를 버려주세요.'\n"
    '출력: {"task_title": "마감 정리", "steps": ['
    '{"sentence": "테이블을 닦으세요.", "symbol_query": ["테이블","table"], "action_type": "clean", "safety_flags": []}, '
    '{"sentence": "컵을 정리하세요.", "symbol_query": ["컵","cup"], "action_type": "sort", "safety_flags": []}, '
    '{"sentence": "쓰레기를 버리세요.", "symbol_query": ["쓰레기","trash"], "action_type": "clean", "safety_flags": []}]}\n'
    "\n예시2 — 입력: '서류를 복사기에 넣고 10장씩 복사한 뒤, 클립으로 묶어 책상에 정리해주세요.'\n"
    '출력: {"task_title": "서류 복사", "steps": ['
    '{"sentence": "서류를 복사기에 넣으세요.", "symbol_query": ["서류","document"], "action_type": "move", "safety_flags": []}, '
    '{"sentence": "10장씩 복사하세요.", "symbol_query": ["복사","copy"], "action_type": "observe", "safety_flags": []}, '
    '{"sentence": "클립으로 묶으세요.", "symbol_query": ["클립","clip"], "action_type": "pack", "safety_flags": []}, '
    '{"sentence": "책상에 정리하세요.", "symbol_query": ["책상","desk"], "action_type": "sort", "safety_flags": []}]}'
)


def llm_decompose(raw_input: str, context: dict | None = None) -> dict:
    ctx = context or {}
    parts = [f"직무 지시문:\n{raw_input.strip()}"]
    if ctx.get("business_type"):
        parts.append(f"업종: {ctx['business_type']}")
    if ctx.get("work_environment"):
        parts.append(f"작업 환경: {ctx['work_environment']}")
    if ctx.get("worker_note"):
        parts.append(f"근로자 특성(개별화 참고): {ctx['worker_note']}")
    return chat_json(_DECOMPOSE_SYSTEM, "\n".join(parts))


# --- 2) 사업주용 AI 코칭 가이드 ---------------------------------------------
_COACHING_SYSTEM = (
    "당신은 발달장애인 직업 코치입니다. 근로자의 단계별 수행 데이터(막힘 여부, "
    "다시듣기 횟수, 소요시간, 완료 여부)를 보고, 어려움이 보이는 단계에 대해 "
    "사업주가 바로 적용할 구체적 개선책을 제안합니다. 규칙:\n"
    "1) 어려움 징후가 있는 단계만 제안합니다(막힘=true, 다시듣기≥3, 소요≥120초 등).\n"
    "2) 각 제안은 원인 추정(issue)과 구체적 조치(suggestion), 그리고 action을 포함합니다.\n"
    "3) action은 다음 중 하나: 'rephrase'(문장 더 쉽게), 'photo'(그림→실제 현장 사진 교체), "
    "'split'(한 단계를 둘로 분할), 'ok'(양호).\n"
    "4) 과장 없이, 현장에서 실행 가능한 한국어로.\n"
    "출력은 반드시 JSON 한 개. 형식:\n"
    '{"summary": "한 줄 요약", "suggestions": [{"order": 2, "issue": "...", '
    '"suggestion": "...", "action": "rephrase|photo|split|ok"}]}'
)


def llm_coaching(task_title: str, steps: list[dict], context: dict | None = None) -> dict:
    payload = {"task_title": task_title, "context": context or {}, "steps": steps}
    user = "다음 수행 데이터를 분석해 제안하세요:\n" + json.dumps(payload, ensure_ascii=False)
    return chat_json(_COACHING_SYSTEM, user, max_tokens=800)
