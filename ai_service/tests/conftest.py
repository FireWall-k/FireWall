"""ai_service 테스트 공통 설정.

임베딩 가산 항은 OpenAI 호출이 필요하다. 개발자 환경에 키가 있어도 테스트가 네트워크를 타거나
결과가 흔들리지 않도록 기본은 끄고, 임베딩을 검증하는 테스트만 가짜 벡터로 켠다.
"""
import os
import sys

os.environ["AAC_EMBEDDINGS"] = "off"
# GPT 그림 재순위(aac_rerank.py)도 기본 끈다. 재순위를 검증하는 테스트만 켜고 HTTP 층을 가짜로 바꾼다.
os.environ["AAC_LLM_RERANK"] = "off"
# 재순위 판정 파일(SQLite)도 개발자 셸 값을 쓰지 않는다. 파일 캐시를 검증하는 테스트만 tmp 경로로 켠다.
os.environ.pop("AAC_LLM_RERANK_CACHE_DB", None)
# 개발자 셸의 OPENAI_API_KEY_FILE이 실제 키를 읽어 오지 않게 한다(secret_env.py는 파일을 우선한다).
os.environ.pop("OPENAI_API_KEY_FILE", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
