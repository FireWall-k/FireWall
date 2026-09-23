"""ai_service 테스트 공통 설정.

임베딩 가산 항은 OpenAI 호출이 필요하다. 개발자 환경에 키가 있어도 테스트가 네트워크를 타거나
결과가 흔들리지 않도록 기본은 끄고, 임베딩을 검증하는 테스트만 가짜 벡터로 켠다.
"""
import os
import sys

os.environ["AAC_EMBEDDINGS"] = "off"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
