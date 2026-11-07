"""백엔드 테스트 공통 설정.

- 임시 SQLite DB / 시크릿 / TTS 캐시 경로를 import 전에 주입한다.
- AI 하네스 HTTP 경계(ai_client)는 결정론적 목으로 패치한다.
"""
import os
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["JOBCARD_SECRET"] = "test-secret"
os.environ["TTS_CACHE_DIR"] = f"{_tmp}/tts"
# 사진도 임시 경로에 둔다(기본 ./data/photos에 테스트 사진이 쌓이지 않게).
os.environ["PHOTO_DIR"] = f"{_tmp}/photos"
os.environ["DEMO_EMPLOYER_LOGIN"] = "demo"
os.environ["DEMO_EMPLOYER_PASSWORD"] = "demo1234"
os.environ["DEMO_WORKER_CODE"] = "1234"
os.environ["DEMO_WORKPLACE_CODE"] = "DEMO01"
# 그림 URL 검증·공개 URL 생성이 이 값에 기대므로 실행 환경과 상관없이 고정한다.
os.environ["PUBLIC_BACKEND_URL"] = "http://localhost:8000"
os.environ.pop("JOBCARD_ENV", None)
# 개발자 셸에 JOBCARD_SECRET_FILE이 있으면 파일이 위 테스트 키보다 우선한다(secret_env.py) — 지운다.
os.environ.pop("JOBCARD_SECRET_FILE", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import ai_client  # noqa: E402
import main  # noqa: E402
import db_migrate  # noqa: E402

# 테스트 DB 스키마도 운영과 같은 경로(Alembic 리비전)로 만든다. 예전처럼 create_all()로 만들면
# 리비전을 빠뜨린 모델 변경이 테스트에서는 통과하고 실제 DB에서만 깨진다.
db_migrate.migrate()


def _fake_decompose(raw_input: str, context=None) -> dict:
    return {
        "task_title": "테스트 직무",
        "steps": [
            {"order": 1, "sentence": "상자를 옮기세요.", "action_type": "move",
             "symbol_query": ["상자", "box"],
             "keywords": [{"term": "상자", "pos": "noun"}]},
            {"order": 2, "sentence": "수량을 확인하세요.", "action_type": "observe",
             "symbol_query": ["수량", "quantity"],
             "keywords": [{"term": "수량", "pos": "noun"}]},
        ],
    }


def _fake_map_symbols(keywords, context=None) -> dict:
    # 실제 /ai/map-symbols와 같은 모양을 유지한다(reason/candidates 포함).
    return {"symbols": [
        {"keyword": k, "image_url": None, "source": "fallback",
         "confidence": 0.0, "needs_fallback": True,
         "reason": "no_candidate", "candidates": []}
        for k in keywords
    ]}


def fake_map_symbols_with_candidates(keywords, context=None) -> dict:
    """후보 경합(low_margin) 상황을 흉내내는 목. 후보 선택 경로 테스트용."""
    return {"symbols": [{
        "keyword": keywords[0] if keywords else "",
        "image_url": None, "source": "fallback", "confidence": 0.0,
        "needs_fallback": True, "reason": "low_margin",
        "candidates": [
            {"asset_id": "CAFE_007", "group_id": "CAFE_007", "job": "cafe",
             "asset_type": "action", "label": "원두를 준비한다",
             "image_url": "/api/aac/images/cafe/CAFE_007.webp", "score": 0.171},
            {"asset_id": "CAFE_013", "group_id": "CAFE_013", "job": "cafe",
             "asset_type": "action", "label": "원두를 분쇄한다",
             "image_url": "/api/aac/images/cafe/CAFE_013.webp", "score": 0.171},
        ],
    }]}


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    # 로그인 실패 카운터는 프로세스 전역이다. 테스트끼리 서로 막지 않게 매번 비운다.
    import ratelimit
    ratelimit.employer_throttle.clear()
    ratelimit.worker_throttle.clear()
    yield


@pytest.fixture(autouse=True)
def _reset_secret_cache():
    # auth._secret()은 프로세스에서 한 번만 읽어 캐시한다(운영: 키 교체는 재시작). 테스트는 JOBCARD_SECRET·
    # JOBCARD_ENV를 바꿔 가며 부르므로 앞뒤로 비운다 — 안 비우면 한 테스트가 넣은 키가 다음 테스트의 토큰·
    # 접속 코드 해시에 쓰여(기본 테스트 키로 만든 데모 근로자 해시와 어긋나) 엉뚱한 곳이 깨진다.
    import auth as auth_module
    auth_module.reset_secret_cache()
    yield
    auth_module.reset_secret_cache()


@pytest.fixture(autouse=True)
def _patch_ai(monkeypatch):
    # 테스트가 실제 Google TTS를 부르지 않게 한다(느리고 과금되며, CI에는 자격 증명이 없다).
    # TTS 모듈 자체는 test_tts.py가 가짜 google 모듈로 따로 검증한다.
    monkeypatch.setattr(main, "synthesize_tts", lambda text, scope: None)
    monkeypatch.setattr(ai_client, "decompose", _fake_decompose)
    monkeypatch.setattr(ai_client, "map_symbols", _fake_map_symbols)
    monkeypatch.setattr(
        ai_client,
        "search_aac",
        lambda query, context=None, limit=5: {
            "query": query,
            "matches": [],
        },
    )
    monkeypatch.setattr(ai_client, "coaching",
                        lambda title, steps, context=None, allow_llm=True: {
                            "summary": "1개 단계에서 개선이 필요해 보입니다.",
                            "suggestions": [{"order": 2, "issue": "다시듣기 과다",
                                             "suggestion": "사진으로 교체하세요.", "action": "photo"}],
                        })


@pytest.fixture()
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture()
def employer_token(client):
    r = client.post("/api/auth/login", json={"login_id": "demo", "password": "demo1234"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture()
def worker_token(client):
    r = client.post("/api/auth/worker-login", json={"workplace_code": "DEMO01", "access_code": "1234"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
