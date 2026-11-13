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
import re

import httpx

from secret_env import read_secret

logger = logging.getLogger("ai_harness.llm")

# 운영은 OPENAI_API_KEY_FILE(/run/secrets/openai_api_key)로 받는다 — 환경변수 키는 docker inspect 등에
# 그대로 보이기 때문이다. OPENAI_API_KEY 직접 값은 로컬 개발 하위호환(secret_env.py의 우선순위 참고).
OPENAI_API_KEY = read_secret("OPENAI_API_KEY").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "20"))
# 직무 단계 나누기는 temperature 0(2026-11-14 3a) — 같은 지시문을 다시 넣으면 같은 단계·말투가 나오게.
DECOMPOSE_TEMPERATURE = 0.0

# AAC 매칭의 임베딩 가산 항(local_aac.py, embeddings.py)에서 쓴다.
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-large")
EMBED_DIMS = int(os.getenv("OPENAI_EMBED_DIMS", "256"))

# OpenAI 연결을 재사용하는 공용 클라이언트(스레드 안전). httpx.post()는 호출마다 SSL 설정을 새로
# 읽고 TLS 연결을 새로 맺어, 질의 임베딩(짧은 타임아웃)처럼 잦은 호출에서 지연이 컸다.
# 타임아웃은 호출마다 따로 준다(임베딩 3초, 채팅 LLM_TIMEOUT).
_http = httpx.Client(limits=httpx.Limits(max_connections=16, max_keepalive_connections=8))


def llm_available() -> bool:
    return bool(OPENAI_API_KEY)


def embed_texts(texts: list[str], *, timeout: float = 20.0) -> list[list[float]]:
    """텍스트 목록을 임베딩 벡터로 바꾼다. 실패 시 예외(호출부가 폴백 처리)."""
    resp = _http.post(
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


def chat_json(system: str, user: str, *, max_tokens: int = 1200,
              timeout: float | None = None, temperature: float = 0.2) -> dict:
    """OpenAI Chat Completions(JSON 모드) 호출 후 dict로 반환. 실패 시 예외.

    timeout을 주면 그 값(초)을 쓴다. 그림 재순위(aac_rerank.py)처럼 늦으면 규칙 결과로 바로
    넘어가야 하는 호출이 기본값(LLM_TIMEOUT, 20초)을 기다리지 않게 하려는 것이다.
    temperature: 직무 단계 나누기(llm_decompose)는 0을 준다 — 같은 지시문이면 같은 단계가 나와야 한다.
    재순위·코칭은 예전 값(0.2) 그대로다.
    """
    resp = _http.post(
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
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=LLM_TIMEOUT if timeout is None else timeout,
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

    # 2026-11-09 입력 화면 단계 나누기: GPT가 동작 하나짜리 문장을 나누는 과분할(정답 1단계 92문장 중 30)이
    # 문제였다. 물건별로 나누라던 지시를 빼고, '동작 하나'의 기준과 대비 예시를 넣었다. 예시 문장은 정답셋
    # (scratchpad split/gold) 문장을 쓰지 않았다 — 측정이 부풀지 않게.
    "1) 단계 나누기: 한 단계 = 동작 하나 = AAC 그림 한 장입니다. "
    "사용자가 원문에서 실제로 언급한 행동만 단계로 만듭니다.\n"
    "- 일반적인 직무 절차를 추론하여 다음 작업을 임의로 추가하지 않습니다.\n"
    "- 원문에 없는 준비, 확인, 이동, 포장, 정리, 마무리, 주의('~하지 마세요') 등의 단계를 추가하지 않습니다.\n"
    "- 원문의 마지막 행동 이후에 일반적으로 이어질 것 같은 작업도 추가하지 않습니다.\n"
    "- 손이 하는 일이 바뀌어 그림 장면이 달라지는 동작이 이어지면 나눕니다.\n"
    "  예: '컵을 씻어서 건조대에 올리세요' → 컵 씻기 / 건조대에 올리기 (2단계)\n"
    "  예: '떨어진 영수증을 주워서 버리세요' → 줍기 / 버리기 (2단계)\n"
    "  예: '뚜껑을 열고 설탕을 넣으세요' → 열기 / 넣기 (2단계)\n"
    "  예: '재고가 남았는지 보고 모자라면 채우세요' → 확인하기 / 채우기 (2단계)\n"
    "  예: '기계를 켜고 불이 들어올 때까지 기다리세요' → 켜기 / 기다리기 (2단계)\n"
    "- 다음은 동작 하나입니다. 나누지 않습니다.\n"
    "  a) 대상 나열: 같은 동작을 여러 물건에 하면 물건별로 나누지 않습니다. "
    "'자와 가위를 서랍에 넣으세요' → 1단계. '컵, 접시, 쟁반을 닦으세요' → 1단계.\n"
    "  b) 방법·도구·모양을 말하는 앞 동사: '수세미로 박박 밀어 씻으세요', '병에 물을 따라 채우세요', "
    "'크기별로 골라 담으세요', '포개서 쌓으세요', '꾹 눌러서 붙이세요' → 각각 1단계.\n"
    "  c) 함께 하는 동작 '-며/-면서': '난간을 닦으며 올라가세요' → 1단계.\n"
    "  d) 이동·방향: '창고에 가서 우유를 가져오세요', '손수레로 날라 오세요', '물을 손님께 갖다 드리세요' → 1단계 "
    "(가다·오다·갖다는 따로 세지 않습니다).\n"
    "  e) 나르기에 딸린 들기·잡기: '상자를 들어서 옮기세요' → 1단계.\n"
    "  f) 보조 동사: '넣어 두세요', '빼 놓으세요', '확인해 보세요', '닫아 주세요' → 1단계.\n"
    "  g) 조건·때·이유: '~하면', '~할 때', '~하기 전에'는 단계가 아닙니다. "
    "'벨이 울리면 문 앞으로 가세요' → 1단계(가기).\n"
    "  h) 금지는 그 동작 하나: '젖은 손으로 플러그를 만지지 마세요' → 1단계.\n"
    "- 헷갈리면 덜 나눕니다. 단계 수를 늘리기 위해 원문에 없는 행동을 만들어내면 안 됩니다.\n"
    "- 사용자 메시지에 '원문 조각' 번호 목록이 있으면, 각 단계의 src에 그 단계가 나온 조각 번호를 적습니다.\n"

    # 2026-11-14 3a(M2·M3): 실제 GPT 시험(직무 3개 12단계)에서 11단계가 '~세요' 명령조로 바뀌었고(보내기 점검의
    # command_tone 경고), '행주로'·'빗자루로' 같은 도구 낱말이 문장에서 빠졌다. 말투·도구·동작 하나 규칙을 적었다.
    # 2026-11-13 수정안 1은 '국자로 떠서 담아요 → 2단계' 같은 나누기 예시를 더해 1단계 문장을 더 나눴다(과분할 6→7) —
    # 그래서 여기에는 나누기 예시를 더하지 않고, 도구 예시도 한 단계 문장만 쓴다. 예시는 정답셋·realsmoke 문장이 아니다.
    "2) sentence는 근로자에게 실제로 보여줄 짧고 명확한 한국어 지시문입니다. "
    "가능하면 20자 안팎으로 유지합니다.\n"
    "- 말투: 사업주가 쓰는 '~해요/~어요/~아요' 말투로 씁니다(예: '닦아요', '넣어요', '정리해요'). "
    "'~하세요', '~하십시오', '~해라', '~해' 같은 명령조로 바꾸지 않습니다. "
    "원문이 '~세요'로 쓰였어도 sentence는 '~해요' 말투로 씁니다.\n"
    "- 불규칙 동사는 바르게 활용합니다: '줍다' → '주워요'('줍어요'는 틀림), '붓다' → '부어요', '돕다' → '도와요', "
    "'듣다' → '들어요'.\n"
    "- 도구 낱말: 원문에 도구·수단 낱말('행주로', '빗자루로', '집게로', '수세미로'처럼 '~로/~으로')이 있으면 "
    "그 동작의 sentence에 그대로 남깁니다. 짧게 만들려고 도구 낱말을 빼지 않습니다.\n"
    "  예: '집게로 빵을 집어 주세요' → '집게로 빵을 집어요.' ('빵을 집어요.'는 도구가 빠져 안 됩니다)\n"
    "- 동작 하나: sentence 하나에는 그림 한 장으로 그릴 동작 하나만 씁니다. "
    "규칙 1에서 나눈 두 동작을 '~하고', '~해서', '~한 뒤'로 한 sentence에 다시 잇지 않습니다. "
    "규칙 1에서 한 단계로 둔 문장(대상 나열, 방법·도구 앞 동사, '-며', 이동·방향, 조건, 금지)은 그대로 한 sentence입니다.\n"
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
    "'물건을 정리해요'로 바꾸면 안 됩니다. "
    "'물건의 방향을 맞춰요'처럼 핵심 조건을 유지합니다.\n"

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
    "  sentence: '큰 부품과 작은 부품을 나눠요.'\n"
    "  symbol_query: ['큰 부품과 작은 부품을 나누다']\n"
    "- 원문: '드라이버로 나사를 조여주세요'\n"
    "  sentence: '드라이버로 나사를 조여요.'\n"
    "  symbol_query: ['드라이버로 나사를 조이다']\n"
    "- 원문: '전선과 커넥터를 연결해주세요'\n"
    "  sentence: '전선과 커넥터를 연결해요.'\n"
    "  symbol_query: ['전선과 커넥터를 연결하다']\n"
    "- 원문: '작업대 위에 남은 부품을 한곳에 모아주세요'\n"
    "  sentence: '남은 부품을 한곳에 모아요.'\n"
    "  symbol_query: ['작업대 위 남은 부품을 한곳에 모으다']\n"
    "- 원문: '상품이 올바른 위치에 있는지 확인해주세요'\n"
    "  sentence: '상품 위치를 확인해요.'\n"
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
    "- 금지 sentence도 '~해요' 말투로 씁니다: '~하면 안 돼요', '~지 않아요'. 금지를 빼고 동작만 남기지 않습니다.\n"
    "- 조건('~하면', '~할 때', '~이 없으면', '~가 아니면')은 sentence에 남기고, 조건과 동작의 짝·뜻을 "
    "뒤집지 않습니다. 예: '컵에 금이 갔으면 쓰지 않아요'를 '컵을 써요'로, '불이 켜지면 문을 열어요'를 "
    "'불을 켜요'로 바꾸면 안 됩니다.\n"

    "7) 위험 요소가 있으면 safety_flags에 한국어로 적고, 없으면 빈 배열입니다.\n"
    "- 원문이나 작업 맥락에서 확인할 수 없는 위험 요소를 임의로 추가하지 않습니다.\n"
    "- 위험한 도구도 sentence의 도구 낱말은 그대로 남깁니다. 위험은 safety_flags에 따로 적습니다. "
    "예: '칼로 포장 끈을 잘라요' → sentence '칼로 포장 끈을 잘라요.', safety_flags ['칼 조심'].\n"

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
    "- sentence가 '~해요' 말투인지('~세요'·'~십시오'·'~해라'로 끝나지 않는지) 확인합니다.\n"
    "- 원문의 도구 낱말('~로/~으로')이 그 동작의 sentence에 남았는지 확인합니다.\n"
    "- sentence 하나에 동작이 하나뿐인지, 금지·조건의 뜻이 원문과 같은지 확인합니다.\n"
    "- task_title이 모든 일 묶음을 담았는지 확인합니다(규칙 10).\n"
    "위 조건을 만족하지 않는 단계는 출력 전에 수정하거나 제거합니다.\n"

    # 2026-11-14 3a(N9): 실제 GPT 시험에서 제목이 첫 묶음만 담았다(뜨거운 물 붓기 + 테이블 닦기 → '테이블 청소').
    # 2026-11-14 run1·run2(temperature 0): 단계 6개 직무 제목이 두 묶음만 담았다('상자 열기와 상품 정리' — 테이블·바닥
    # 청소와 손 씻기 빠짐). 원인으로 본 것: 예시가 모두 'A와 B' 두 부분이었고(셋 묶음 예시도 동사 둘로 줄임), '20자 안팎'과
    # '묶음'의 뜻이 정해지지 않았다. 묶음을 정의하고, 세 부분 예시를 '·'로 잇고, 마지막 문장까지 넣으라고 적었다(25자 이내).
    # run3: 이번엔 단계 6개를 모두 묶음으로 써 35자가 됐다 — 묶음은 '작은 목표 하나를 향한 이어진 단계들'이고 보통 2~4개,
    # 단계 수보다 적다고 적었다. 코드 가드(decompose.guard_title)가 25자·부분 수를 넘는 제목을 줄인다.
    "10) task_title은 이 직무 전체를 부르는 짧은 이름입니다.\n"
    "- 일 묶음: 작은 목표 하나(예: 진열, 청소, 설거지, 포장)를 향해 이어지는 단계들입니다. 단계 하나하나가 묶음이 아닙니다. "
    "보통 2~4묶음이고, 묶음 수는 단계 수의 절반 이하입니다. "
    "원문의 모든 문장은 어느 묶음엔가 들어갑니다. 첫 문장부터 마지막 문장까지 빠지는 묶음이 없어야 합니다.\n"
    "- 제목에는 모든 묶음의 이름이 들어갑니다. 묶음마다 2~5글자 이름을 쓰고 '·'로 잇습니다.\n"
    "  예(단계 5개, 3묶음): 박스를 뜯고, 컵을 꺼내 진열대에 놓고, 바닥을 쓸고 쓰레기를 버리는 지시 → "
    "'박스 뜯기·컵 진열·청소' ('박스 뜯기·컵 꺼내기·컵 놓기·바닥 쓸기·쓰레기 버리기'는 단계를 늘어놓은 것이라 안 됩니다)\n"
    "  예(2묶음): 창문을 닦고 화분에 물을 주는 지시 → '창문 닦기·화분 물 주기'\n"
    "- 제목은 25자 이내로 짧게 쓰되, 짧게 하려고 묶음을 빼지 않습니다. 원문에 없는 일을 넣지 않습니다.\n"

    "출력은 반드시 JSON 하나입니다. 형식:\n"
    "{"
    "\"task_title\":\"모든 묶음 이름을 · 로 이은 짧은 제목\","
    "\"job\":\"assembly | cafe | cleaning | packaging | retail | serving | display | delivery | gas | unknown\","
    "\"steps\":["
    "{"
    "\"sentence\":\"'~해요' 말투의 동작 하나 문장\","
    "\"symbol_query\":[\"대상+구체적 행동\"],"
    "\"action_type\":\"observe|move|sort|stack|pack|clean|wear|operate|assemble|other\","
    "\"safety_flags\":[],"
    "\"src\":1"
    "}"
    "]"
    "}\n"

    "예시 입력: "
    "'조립대에서 큰 부품과 작은 부품을 나누고, 전선과 커넥터를 연결해주세요.' "
    "(원문 조각: 1) 조립대에서 큰 부품과 작은 부품을 나누고 2) 전선과 커넥터를 연결해주세요)\n"
    "예시 출력:\n"
    "{"
    "\"task_title\":\"부품 나누기·커넥터 연결\","
    "\"job\":\"assembly\","
    "\"steps\":["
    "{"
    "\"sentence\":\"큰 부품과 작은 부품을 나눠요.\","
    "\"symbol_query\":[\"큰 부품과 작은 부품을 나누다\"],"
    "\"action_type\":\"sort\","
    "\"safety_flags\":[],"
    "\"src\":1"
    "},"
    "{"
    "\"sentence\":\"전선과 커넥터를 연결해요.\","
    "\"symbol_query\":[\"전선과 커넥터를 연결하다\"],"
    "\"action_type\":\"assemble\","
    "\"safety_flags\":[],"
    "\"src\":2"
    "}"
    "]"
    "}"
)


def llm_decompose(raw_input: str, context: dict | None = None,
                  clauses: list[str] | None = None) -> dict:
    """clauses: 규칙이 자른 원문 조각(decompose.clauses_of). 주면 GPT가 단계마다 조각 번호(src)를 단다 —
    규칙 동작 세기와 조각 단위로 맞춰 보기 위해서다(decompose._reconcile)."""
    ctx = context or {}
    parts = [f"직무 지시문:\n{raw_input.strip()}"]
    if clauses:
        parts.append("원문 조각:\n" + "\n".join(f"{i}) {c}" for i, c in enumerate(clauses, start=1)))
    if ctx.get("business_type"):
        parts.append(f"업종: {ctx['business_type']}")
    if ctx.get("work_environment"):
        parts.append(f"작업 환경: {ctx['work_environment']}")
    if ctx.get("worker_note"):
        parts.append(f"근로자 특성(개별화 참고): {ctx['worker_note']}")
    raw = chat_json(_DECOMPOSE_SYSTEM, "\n".join(parts), temperature=DECOMPOSE_TEMPERATURE)
    check_negation(raw_input, raw)
    return raw


# 금지·부정 표현 보존 검사. '만지지 말고 선생님을 부르세요'가 '선생님을 부르세요'만 남으면 근로자는 '만지지 마'를
# 듣지 못한다(2026-11-08 분해 프롬프트 수정안에서 실제로 일어났다 — eval/README.md). 반대로 원문에 없는
# '수저통에 넣지 마세요'를 덧붙이면 앞 단계와 정반대 지시가 된다(지금 프롬프트 170문장 중 1건).
#
# 표현마다 '무엇을 하지 말라는가'(동사 어간 또는 '~ 금지' 앞말)를 뽑아 원문과 단계 문장을 맞춘다 — 원문의 금지가
# 모두 단계 문장에 남아야 하고, 단계 문장의 금지는 모두 원문에 있어야 한다. 그래서 '만지면 안 됩니다'를
# '만지지 마세요'로 바꿔 쓴 것은 통과하고, '닫지 말고'를 '닦지 마세요'로 옮긴 것(다른 동사)은 걸린다.
# 패턴 순서가 중요하다: 앞 패턴이 잡은 부분은 지우고 다음 패턴을 본다('만지면 안 됩니다'를 '안 됩'으로 또 세지 않게).
_NEG_PATTERNS = (
    # ~지 마(세요/십시오/요/라) · ~지 말(고/아/라/것/기/도록/자) · ~지 않. '가지마다'·'엄지마디'는 '마' 뒤가
    # 한글이라 걸리지 않는다.
    re.compile(r"([가-힣]+)지\s?(?:마(?:세요|십시오|시오|요|라)?(?![가-힣])"
               r"|말(?:아요|아야|아|고|라|것|기|도록|자)?(?![가-힣])|않)"),
    # ~(으)면 안 돼요/됩니다/된다/되 — '만지면'·'넣으면'·'하면'.
    re.compile(r"([가-힣]+?)으?면\s?안\s?(?:돼|됩|된|되)"),
    # ~ 금지 — '사용 금지', '출입금지'. 어간 대신 앞말을 쓴다.
    re.compile(r"([가-힣]*?)\s?금지"),
    # 짧은 부정 '안 + 동사': '콘센트를 안 만져요'. '상자 안에'·'상자 안 물건'은 뒤가 동사 어미가 아니라 걸리지 않는다.
    # '안 됩니다'의 '됩'은 동사로 보지 않는다(아래 패턴이 센다).
    re.compile(r"(?<![가-힣])안\s(?![돼되됩된])([가-힣]+?)(?:아요|어요|여요|해요|요|습니다|니다|고|게|도록)(?![가-힣])"),
    # 위에서 어간을 못 뽑은 '안 돼/안 됩니다'('만져서는 안 됩니다' 등). 어간 없이 '어떤 금지'로 센다.
    re.compile(r"()안\s?(?:돼|됩|된다|되[요니어고는])"),
)


def negation_keys(text: str) -> list[str]:
    """문장 속 금지·부정 표현마다 '무엇을'에 해당하는 말(어간·앞말)을 돌려준다. 못 뽑으면 빈 문자열."""
    keys: list[str] = []
    rest = text or ""
    for pat in _NEG_PATTERNS:
        def take(m: re.Match) -> str:
            keys.append(m.group(1) or "")
            return " " * (m.end() - m.start())
        rest = pat.sub(take, rest)
    return keys


def _has_negation(text: str) -> bool:
    return bool(negation_keys(text))


def _same_target(a: str, b: str) -> bool:
    """두 금지가 같은 동작을 가리키는가. 활용형 차이('만지'·'만져', '사용'·'사용하')는 같다고 본다."""
    if not a or not b:
        return True  # 어간을 못 뽑은 쪽은 '어떤 금지든'으로 본다
    return a == b or a.startswith(b) or b.startswith(a) or a[0] == b[0]


def check_negation(raw_input: str, raw: dict) -> None:
    """분해 결과가 원문의 금지·부정을 잃었거나, 원문에 없는(또는 다른 동작에 붙은) 금지를 만들었으면
    ValueError(→ 규칙 분해로 폴백).

    단계 문장(sentence)만 본다 — 근로자가 듣는 것은 단계 문장이다.
    """
    steps = raw.get("steps") if isinstance(raw, dict) else None
    sentences = [str(s.get("sentence") or "") for s in (steps if isinstance(steps, list) else [])
                 if isinstance(s, dict)]
    src = negation_keys(raw_input or "")
    out = [k for s in sentences for k in negation_keys(s)]
    for k in src:
        if not any(_same_target(k, o) for o in out):
            raise ValueError("분해 결과에서 원문의 금지·부정 표현이 사라짐")
    for o in out:
        if not any(_same_target(o, k) for k in src):
            raise ValueError("분해 결과에 원문에 없는 금지·부정 표현이 생김")


# --- 2) 사업주용 AI 코칭 가이드 ---------------------------------------------
_COACHING_SYSTEM = (
    "당신은 발달장애인 직업 코치입니다. 근로자의 단계별 수행 데이터(막힘 여부, "
    "다시듣기 횟수, 소요시간, 완료 여부, 동작 유형)와 이 직무의 업종·작업 환경을 보고, "
    "어려움이 보이는 단계에 대해 사업주가 오늘 바로 적용할 구체적 개선책을 제안합니다. 규칙:\n"
    "1) 막힘=true, 다시듣기≥3, 소요≥120초 중 하나라도 해당하는 단계는 예외 없이 전부 "
    "제안을 답니다. 하나라도 빠뜨리면 안 됩니다(서버가 누락 여부를 검사합니다).\n"
    "2) 그 밖에 수치는 애매해도 문장 자체가 근로자에게 어려워 보이는 단계(추상적 표현, "
    "긴 문장, 여러 동작이 한 문장에 들어있음)가 있으면 함께 짚어 주세요.\n"
    "3) issue는 왜 어려운지를 그 단계의 실제 문장·수치를 근거로 구체적으로 씁니다"
    "('2단계에서 어려움 징후'처럼 번호만 반복하는 문장 금지 — 예: "
    "'\"수량을 확인하세요\"는 무엇을 어떻게 세는지가 없어 다시듣기가 5회 발생').\n"
    "4) suggestion은 이 업종·환경과 이 단계의 동작 유형(action_type)에 맞게 구체적으로 씁니다.\n"
    "   - action_type이 assemble/operate: 손동작이 복잡할 수 있음 → 세부 동작으로 분할(split) 우선.\n"
    "   - observe: 무엇을 어떻게 확인하는지가 문장에 없을 때가 많음 → 기준을 명시하도록 rephrase.\n"
    "   - 그림이 실물과 다르거나 다시듣기가 반복되면 → 실제 현장 사진으로 교체(photo).\n"
    "5) action은 다음 중 하나: 'rephrase'(문장 더 쉽게/구체적으로), "
    "'photo'(그림→실제 현장 사진 교체), 'split'(한 단계를 둘로 분할), 'ok'(양호).\n"
    "6) 어려움 징후가 여럿이면 issue에 원인 조합을(예: '다시듣기 5회+소요 140초') 함께 적어 "
    "가장 시급한 단계를 사업주가 한눈에 알 수 있게 합니다.\n"
    "7) 과장 없이, 오늘 현장에서 바로 실행 가능한 한국어 지시문으로.\n"
    "출력은 반드시 JSON 한 개. 형식:\n"
    '{"summary": "한 줄 요약", "suggestions": [{"order": 2, "issue": "...", '
    '"suggestion": "...", "action": "rephrase|photo|split|ok"}]}'
)


# 코칭 프롬프트에 넣는 맥락 필드. 스키마(CoachingContext)가 이미 거르지만, 이 함수를 직접 부르는 코드가
# 생겨도 이름 같은 필드가 프롬프트로 새지 않게 여기서 한 번 더 고른다. 빈 값은 넣지 않는다.
_COACHING_CONTEXT_KEYS = ("business_type", "work_environment", "job", "worker_note")
_COACHING_STEP_KEYS = ("order", "sentence", "completed", "stuck", "replay_count", "duration_sec",
                       "action_type")


def llm_coaching(task_title: str, steps: list[dict], context: dict | None = None) -> dict:
    ctx = {k: (context or {})[k] for k in _COACHING_CONTEXT_KEYS if (context or {}).get(k)}
    steps = [{k: s[k] for k in _COACHING_STEP_KEYS if k in s} for s in steps]
    payload = {"task_title": task_title, "context": ctx, "steps": steps}
    user = "다음 수행 데이터를 분석해 제안하세요:\n" + json.dumps(payload, ensure_ascii=False)
    return chat_json(_COACHING_SYSTEM, user, max_tokens=1200)
