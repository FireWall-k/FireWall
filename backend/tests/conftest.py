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
os.environ["DEMO_EMPLOYER_LOGIN"] = "demo"
os.environ["DEMO_EMPLOYER_PASSWORD"] = "demo1234"
os.environ["DEMO_WORKER_CODE"] = "1234"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import ai_client  # noqa: E402
import main  # noqa: E402


def _fake_decompose(raw_input: str, context=None) -> dict:
    return {
        "task_title": "테스트 직무",
        "steps": [
            {"order": 1, "sentence": "상자를 옮기세요.", "action_type": "move",
             "keywords": [{"term": "상자", "pos": "noun"}]},
            {"order": 2, "sentence": "수량을 확인하세요.", "action_type": "observe",
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
def _patch_ai(monkeypatch):
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
                        lambda title, steps, context=None: {
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
    r = client.post("/api/auth/worker-login", json={"access_code": "1234"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
