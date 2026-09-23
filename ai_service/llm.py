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
    "현장 작업 지시문을 인지부하가 낮은 단계로 나누고, "
    "각 단계에 적합한 AAC 그림을 검색할 수 있는 검색 표현도 만듭니다.\n"
    "\n"

    "규칙:\n"

    "1) 각 단계는 하나의 구체적 동작만 담습니다. "
    "원문에 없는 준비, 확인, 이동, 정리 등의 행동을 임의로 추가하지 않습니다.\n"

    "2) sentence는 근로자에게 실제로 보여줄 짧고 명확한 한국어 명령형입니다. "
    "가능하면 20자 안팎으로 유지합니다.\n"

    "3) 전체 작업의 직무 job을 반드시 하나 고릅니다.\n"
    "- assembly: 부품 조립, 체결, 전선 연결, 제조 조립 작업\n"
    "- cafe: 음료 제조, 커피, 카페 작업\n"
    "- cleaning: 청소, 세탁, 세차, 환경미화\n"
    "- packaging: 포장, 소포장, 박스 포장\n"
    "- retail: 상품 진열, 피킹, 매장 정리, 계산\n"
    "- unknown: 위 직무 중 확실히 판단할 수 없음\n"
    "출력값은 반드시 assembly|cafe|cleaning|packaging|retail|unknown 중 하나입니다. "
    "업종과 작업환경 정보가 있으면 우선 참고하되, 근거가 부족하면 unknown으로 둡니다.\n"

    "4) symbol_query는 AAC 그림 검색을 위한 표현입니다. "
    "sentence를 단순 반복하지 말고, 원문의 작업 맥락을 보존한 '대상 + 구체적 행동' 형태로 만듭니다.\n"
    "- 명사만 나열하지 않습니다.\n"
    "- 반드시 행동을 나타내는 동사를 포함합니다.\n"
    "- 원문에 대상, 도구, 위치, 방향, 상태, 수량, 순서 등의 정보가 있으면 "
    "검색에 필요한 범위에서 유지합니다.\n"
    "- sentence를 짧게 만들면서 생략한 중요한 맥락은 symbol_query에 다시 포함할 수 있습니다.\n"
    "- 단, 원문이나 주어진 작업 맥락에 없는 물건, 도구, 수량, 상태, 목적을 만들어내면 안 됩니다.\n"
    "- AAC 데이터셋에 어떤 이미지가 있는지 추측하거나 특정 카드 문구를 억지로 만들어내지 않습니다.\n"
    "- 보통 1개를 만들고, 의미가 같은 자연스러운 표현이 검색에 도움이 될 때만 최대 2개까지 만듭니다.\n"
    "\n"
    "좋은 예:\n"
    "- 원문: '큰 부품과 작은 부품을 나눠주세요'\n"
    "  sentence: '큰 부품과 작은 부품을 나누세요.'\n"
    "  symbol_query: ['큰 부품과 작은 부품을 나누다']\n"
    "- 원문: '드라이버로 나사를 조여주세요'\n"
    "  sentence: '나사를 조이세요.'\n"
    "  symbol_query: ['드라이버로 나사를 조이다']\n"
    "- 원문: '전선과 커넥터를 연결해주세요'\n"
    "  sentence: '커넥터를 연결하세요.'\n"
    "  symbol_query: ['전선과 커넥터를 연결하다']\n"
    "- 원문: '작업대 위에 남은 부품을 한곳에 모아주세요'\n"
    "  sentence: '남은 부품을 모으세요.'\n"
    "  symbol_query: ['작업대 위 남은 부품을 한곳에 모으다']\n"
    "\n"
    "나쁜 예:\n"
    "- ['부품'] : 행동이 없음\n"
    "- ['준비하기'] : 대상이 없음\n"
    "- ['부품을 처리하다'] : 행동이 지나치게 추상적임\n"
    "- 원문에 드라이버가 없는데 ['드라이버로 나사를 조이다'] : 원문에 없는 정보 추가\n"

    "5) action_type은 모든 직무가 공유하는 상위 행동군입니다. "
    "세부 행동 차이는 sentence와 symbol_query의 동사가 담당합니다.\n"
    "- observe: 보다, 확인하다, 검사하다, 비교하다, 세다\n"
    "- move: 가져오다, 옮기다, 놓다, 꺼내다, 전달하다\n"
    "- sort: 분류하다, 나누다, 구분하다, 정리하다\n"
    "- stack: 쌓다, 적재하다\n"
    "- pack: 담다, 포장하다, 밀봉하다, 접다\n"
    "- clean: 닦다, 씻다, 쓸다, 치우다, 버리다\n"
    "- wear: 사람이 작업복이나 보호구를 입거나 착용하거나 벗다\n"
    "- operate: 버튼, 스위치, 기계 또는 일반 도구를 조작하다\n"
    "- assemble: 부품을 결합, 끼움, 연결, 체결, 맞춤, 부착, 분리, 교체, 재조립하다\n"
    "- other: 위 분류에 확실히 해당하지 않는 동작\n"
    "주의: '장갑을 끼다'는 wear이고, '부품을 홈에 끼우다'는 assemble입니다. "
    "'나사를 구멍에 넣다' 또는 '나사를 조이다'도 조립 과정이면 assemble입니다.\n"

    "6) 금지 지시는 긍정 행동으로 바꾸지 않습니다.\n"
    "예: '나사를 너무 세게 조이지 마세요'는 "
    "sentence와 symbol_query 모두 금지 의미를 유지합니다.\n"

    "7) 위험 요소가 있으면 safety_flags에 한국어로 적고, 없으면 빈 배열입니다.\n"

    "8) 단계는 최대 10개입니다.\n"

    "출력은 반드시 JSON 하나입니다. 형식:\n"
    "{"
    "\"task_title\":\"짧은 제목\","
    "\"job\":\"assembly | cafe | cleaning | packaging | retail | serving | display | delivery | gas | unknown\","
    "\"steps\":["
    "{"
    "\"sentence\":\"명령형 문장\","
    "\"symbol_query\":[\"대상+구체적 행동\"],"
    "\"action_type\":\"observe|move|sort|stack|pack|clean|wear|operate|assemble|other\","
    "\"safety_flags\":[]"
    "}"
    "]"
    "}\n"

    "예시 입력: "
    "'조립대에서 큰 부품과 작은 부품을 나누고, 전선과 커넥터를 연결해주세요.'\n"
    "예시 출력:\n"
    "{"
    "\"task_title\":\"부품 조립\","
    "\"job\":\"assembly\","
    "\"steps\":["
    "{"
    "\"sentence\":\"큰 부품과 작은 부품을 나누세요.\","
    "\"symbol_query\":[\"큰 부품과 작은 부품을 나누다\"],"
    "\"action_type\":\"sort\","
    "\"safety_flags\":[]"
    "},"
    "{"
    "\"sentence\":\"커넥터를 연결하세요.\","
    "\"symbol_query\":[\"전선과 커넥터를 연결하다\"],"
    "\"action_type\":\"assemble\","
    "\"safety_flags\":[]"
    "}"
    "]"
    "}"
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
