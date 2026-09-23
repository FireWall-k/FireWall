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

# AAC 매칭의 임베딩 가산 항(local_aac.py, embeddings.py)에서 쓴다.
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-large")
EMBED_DIMS = int(os.getenv("OPENAI_EMBED_DIMS", "256"))


def llm_available() -> bool:
    return bool(OPENAI_API_KEY)


def embed_texts(texts: list[str], *, timeout: float = 20.0) -> list[list[float]]:
    """텍스트 목록을 임베딩 벡터로 바꾼다. 실패 시 예외(호출부가 폴백 처리)."""
    resp = httpx.post(
        f"{OPENAI_BASE_URL}/embeddings",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"model": EMBED_MODEL, "input": texts, "dimensions": EMBED_DIMS},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return [row["embedding"] for row in data]


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
    "사용자가 원문에서 실제로 언급한 행동만 단계로 만듭니다.\n"
    "- 일반적인 직무 절차를 추론하여 다음 작업을 임의로 추가하지 않습니다.\n"
    "- 원문에 없는 준비, 확인, 이동, 포장, 정리, 마무리 등의 행동을 추가하지 않습니다.\n"
    "- 원문의 마지막 행동 이후에 일반적으로 이어질 것 같은 작업도 추가하지 않습니다.\n"
    "- 서로 다른 행동이 한 문장에 함께 있으면 각각의 단계로 나눕니다.\n"
    "- 같은 행동이 여러 대상에 적용되더라도, 각 대상을 서로 독립적으로 조작하거나 "
    "각 대상에 대해 행동을 따로 완료할 수 있으면 각각의 단계로 나눕니다.\n"
    "- 특히 여러 개의 독립된 물건을 각각 준비하거나 가져오거나 놓는 작업은 "
    "물건별 단계로 나눕니다.\n"
    "- 반대로 여러 대상 사이의 비교, 분류, 연결, 조립처럼 "
    "여러 대상이 동시에 있어야 하나의 행동이 성립하는 경우에는 한 단계로 유지합니다.\n"
    "- 한 단계는 가능한 한 하나의 AAC 그림에서 하나의 시각적 초점으로 표현할 수 있어야 합니다.\n"
    "- 단계 수를 늘리기 위해 원문에 없는 행동을 만들어내면 안 됩니다.\n"

    "2) sentence는 근로자에게 실제로 보여줄 짧고 명확한 한국어 명령형입니다. "
    "가능하면 20자 안팎으로 유지합니다.\n"
    "- 문장을 쉽게 바꾸더라도 원문의 핵심 의미는 유지합니다.\n"
    "- 대상, 동작, 방향, 위치, 상태, 수량, 순서, 비교 조건, 긍정·부정 의미 중 "
    "작업을 구분하는 데 필요한 정보는 삭제하지 않습니다.\n"
    "- 구체적인 행동을 더 추상적인 표현으로 바꾸지 않습니다.\n"
    "- 서로 의미가 다른 행동을 같은 행동처럼 바꾸지 않습니다.\n"
    "예: '불량 제품이 있는지 확인한다'와 '불량 제품을 골라낸다'는 서로 다른 행동입니다.\n"
    "예: '물건을 가져온다'와 '물건을 놓는다'도 서로 다른 행동입니다.\n"
    "- sentence를 짧게 만들기 위해 정보를 생략할 때, "
    "그 정보를 제거하면 예상되는 AAC 그림의 장면이 달라지는 경우에는 생략하면 안 됩니다.\n"
    "- 방향, 위치, 상태, 비교 기준처럼 행동의 결과를 결정하는 조건은 "
    "sentence에도 가능한 한 유지합니다.\n"
    "- 원문의 조건을 단순한 '정리하다', '처리하다', '준비하다' 같은 "
    "포괄적인 표현으로 축약하지 않습니다.\n"
    "예: '물건의 방향을 같은 쪽으로 맞춘다'를 "
    "'물건을 정리하세요'로 바꾸면 안 됩니다. "
    "'물건의 방향을 맞추세요'처럼 핵심 조건을 유지합니다.\n"

    "3) 전체 작업의 직무 job을 반드시 하나 고릅니다.\n"
    "- assembly: 부품 조립, 체결, 전선 연결, 제조 조립 작업\n"
    "- cafe: 음료 제조, 커피, 카페 작업\n"
    "- cleaning: 청소, 세탁, 세차, 환경미화\n"
    "- packaging: 포장, 소포장, 박스 포장\n"
    "- retail: 매장 피킹, 상품 이동, 매장 정리, 계산 등 일반 매장 작업\n"
    "- serving: 음식점 서빙, 배식, 음식 전달, 식기 수거\n"
    "- display: 상품 진열, 매대 관리, 상품 보충\n"
    "- delivery: 배송, 배달, 택배 전달, 배송 확인\n"
    "- gas: 주유소 업무, 차량 주유, 주유 관련 고객 응대\n"
    "- unknown: 위 직무 중 확실히 판단할 수 없음\n"
    "출력값은 반드시 "
    "assembly|cafe|cleaning|packaging|retail|serving|display|delivery|gas|unknown "
    "중 하나입니다. "
    "업종과 작업환경 정보가 있으면 우선 참고하되, 근거가 부족하면 unknown으로 둡니다.\n"

    "4) symbol_query는 AAC 그림 검색을 위한 표현입니다. "
    "sentence를 단순 반복하지 말고, 원문의 작업 맥락을 보존한 '대상 + 구체적 행동' 형태로 만듭니다.\n"
    "- 명사만 나열하지 않습니다.\n"
    "- 반드시 행동을 나타내는 동사를 포함합니다.\n"
    "- sentence에 남아 있는 핵심 행동과 symbol_query의 행동이 서로 달라지면 안 됩니다.\n"
    "- 원문에 대상, 도구, 위치, 방향, 상태, 수량, 순서 등의 정보가 있으면 "
    "그림을 구분하는 데 필요한 범위에서 유지합니다.\n"
    "- sentence를 짧게 만들면서 생략한 중요한 맥락은 symbol_query에 다시 포함할 수 있습니다.\n"
    "- 원문이나 주어진 작업 맥락에 없는 물건, 도구, 위치, 수량, 상태, 목적을 만들어내면 안 됩니다.\n"
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
    "- 원문: '상품이 올바른 위치에 있는지 확인해주세요'\n"
    "  sentence: '상품 위치를 확인하세요.'\n"
    "  symbol_query: ['상품이 올바른 위치에 있는지 확인하다']\n"
    "\n"
    "나쁜 예:\n"
    "- ['부품'] : 행동이 없음\n"
    "- ['준비하기'] : 대상이 없음\n"
    "- ['부품을 처리하다'] : 행동이 지나치게 추상적임\n"
    "- 원문에 드라이버가 없는데 ['드라이버로 나사를 조이다'] : 원문에 없는 정보 추가\n"
    "- 원문이 '확인하다'인데 ['골라내다'] : 원문의 행동을 다른 행동으로 변경\n"

    "5) action_type은 모든 직무가 공유하는 상위 행동군입니다. "
    "세부 행동 차이는 sentence와 symbol_query의 동사가 담당합니다.\n"
    "- observe: 보다, 확인하다, 검사하다, 비교하다, 세다\n"
    "- move: 가져오다, 옮기다, 이동하다, 놓다, 꺼내다, 전달하다\n"
    "- sort: 분류하다, 나누다, 구분하다, 정렬하다, 골라내다\n"
    "- stack: 쌓다, 적재하다\n"
    "- pack: 담다, 포장하다, 밀봉하다, 접다, 감싸다\n"
    "- clean: 닦다, 씻다, 쓸다, 치우다, 버리다\n"
    "- wear: 사람이 작업복이나 보호구를 입거나 착용하거나 벗다\n"
    "- operate: 버튼, 스위치, 기계 또는 일반 도구를 조작하다\n"
    "- assemble: 부품을 결합, 끼움, 연결, 체결, 맞춤, 부착, 분리, 교체, 재조립하다\n"
    "- other: 위 분류에 확실히 해당하지 않는 동작\n"
    "주의: action_type은 원문의 실제 행동을 기준으로 선택합니다. "
    "비슷한 대상이 등장한다는 이유로 행동군을 바꾸지 않습니다.\n"
    "주의: '장갑을 끼다'는 wear이고, '부품을 홈에 끼우다'는 assemble입니다. "
    "'나사를 구멍에 넣다' 또는 '나사를 조이다'도 조립 과정이면 assemble입니다.\n"
    "주의: '확인하다'는 observe이고, 확인 후 실제로 골라내는 행동은 sort입니다.\n"
    "주의: '준비하다', '기다리다', '서 있다'처럼 위 분류에 명확히 해당하지 않으면 other를 사용합니다.\n"

    "6) 금지 지시와 부정 의미는 긍정 행동으로 바꾸지 않습니다.\n"
    "예: '나사를 너무 세게 조이지 마세요'는 "
    "sentence와 symbol_query 모두 금지 의미를 유지합니다.\n"
    "- '사용하지 않는다', '섞지 않는다', '넘지 않는다', '놓지 않는다' 같은 부정 조건도 유지합니다.\n"

    "7) 위험 요소가 있으면 safety_flags에 한국어로 적고, 없으면 빈 배열입니다.\n"
    "- 원문이나 작업 맥락에서 확인할 수 없는 위험 요소를 임의로 추가하지 않습니다.\n"

    "8) 단계는 최대 10개입니다.\n"
    "- 원문에 실제 행동이 적으면 10개를 채울 필요가 없습니다.\n"
    "- 10개를 넘는 경우 핵심 행동을 누락하지 않는 범위에서 가까운 행동을 적절히 묶습니다.\n"

    "9) 출력하기 전에 각 단계를 다시 검토합니다.\n"
    "- 해당 행동이 원문에 실제로 존재하는지 확인합니다.\n"
    "- 원문에 없는 다음 작업을 추가하지 않았는지 확인합니다.\n"
    "- 핵심 대상과 행동이 유지되었는지 확인합니다.\n"
    "- 방향, 위치, 상태, 수량, 순서, 부정 의미 등 중요한 조건이 사라지지 않았는지 확인합니다.\n"
    "- 확인, 이동, 분류, 조립 등 서로 다른 행동으로 의미가 바뀌지 않았는지 확인합니다.\n"
    "- symbol_query에 대상과 구체적인 행동이 모두 포함되어 있는지 확인합니다.\n"
    "위 조건을 만족하지 않는 단계는 출력 전에 수정하거나 제거합니다.\n"

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
