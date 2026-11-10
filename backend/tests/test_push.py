"""2c 웹 푸시 시험 (contract §5.2). 실제 푸시 서비스는 부르지 않는다(push.webpush를 가짜로 바꾼다).

지키는 것: 키가 없으면 enabled=false·안 보냄, 구독 수만큼 보냄, 내용에 근로자 이름 없음, 410·404면 구독 삭제,
그 밖의 실패는 무시하고 도움 생성은 늘 201, 확인한 요청을 다시 부르면 다시 보냄, 구독 저장·삭제·주소 검사.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

import manage  # noqa: E402
import push  # noqa: E402
from database import SessionLocal  # noqa: E402
from live_site import Site  # noqa: E402
from models import PushSubscription  # noqa: E402


class FakeResp:
    def __init__(self, status):
        self.status_code = status


@pytest.fixture()
def keys(tmp_path, monkeypatch):
    """시험마다 버리는 VAPID 키(진짜 키 파일은 읽지 않는다)."""
    out = tmp_path / "vapid.pem"
    pub = manage.vapid_keys(str(out))
    monkeypatch.setenv("VAPID_PUBLIC_KEY", pub)
    monkeypatch.setenv("VAPID_PRIVATE_KEY_FILE", str(out))
    return pub


@pytest.fixture()
def sent(monkeypatch):
    calls = []
    plan = {}

    def fake_webpush(subscription_info, data, vapid_private_key, vapid_claims, ttl, timeout):
        calls.append({"endpoint": subscription_info["endpoint"], "data": json.loads(data), "claims": vapid_claims})
        status = plan.get(subscription_info["endpoint"])
        if status == "boom":
            raise ConnectionError("network down")
        if status:
            raise push.WebPushException("fail", response=FakeResp(status))

    monkeypatch.setattr(push, "webpush", fake_webpush)
    return calls, plan


def _subscribe(site, endpoint, client):
    r = client.post("/api/employer/push-subscriptions", headers=site.h,
                    json={"endpoint": endpoint, "keys": {"p256dh": "BPk" + "a" * 60, "auth": "auth" + "b" * 10}})
    assert r.status_code == 201, r.text


def _subs(employer_id):
    with SessionLocal() as db:
        return sorted(db.scalars(select(PushSubscription.endpoint)
                                 .where(PushSubscription.employer_id == employer_id)).all())


def _open_help(site):
    w = site.workers[0]
    card = site.card(w)
    return site.help(w, card["assignment_id"], card["steps"][0]["id"]), card


def test_config_disabled_without_keys(client):
    site = Site(client, task=False)
    assert client.get("/api/employer/push-config", headers=site.h).json() == {"enabled": False, "public_key": None}


def test_config_enabled_with_keys(client, keys):
    site = Site(client, task=False)
    assert client.get("/api/employer/push-config", headers=site.h).json() == {"enabled": True, "public_key": keys}


def test_no_keys_sends_nothing(client, sent):
    calls, _ = sent
    site = Site(client)
    _subscribe(site, "https://push.example.com/a", client)
    r_help, _card = _open_help(site)
    assert r_help["state"] == "open"
    assert calls == []


def test_sends_to_each_subscription_without_worker_name(client, keys, sent):
    calls, _ = sent
    site = Site(client)
    other = Site(client, task=False)
    _subscribe(site, "https://push.example.com/a", client)
    _subscribe(site, "https://push.example.com/b", client)
    _subscribe(other, "https://push.example.com/other", client)
    w = site.workers[0]
    card = site.card(w)
    r = client.post("/api/worker/help", headers=w["h"],
                    json={"assignment_id": card["assignment_id"], "step_id": card["steps"][0]["id"],
                          "client_request_id": "p1"})
    assert r.status_code == 201
    assert sorted(c["endpoint"] for c in calls) == ["https://push.example.com/a", "https://push.example.com/b"]
    for c in calls:
        assert c["data"] == {"title": "잡카드", "body": "도움 요청이 있어요", "url": "/m#help"}
        assert w["display_name"] not in json.dumps(c["data"], ensure_ascii=False)
        assert c["claims"]["sub"].startswith("mailto:")
    with SessionLocal() as db:
        assert all(s.last_ok_at is not None for s in db.scalars(
            select(PushSubscription).where(PushSubscription.employer_id == site.employer_id)).all())
    # 같은 누름 재전송은 새 요청이 아니라 다시 보내지 않는다
    again = client.post("/api/worker/help", headers=w["h"],
                        json={"assignment_id": card["assignment_id"], "client_request_id": "p1"})
    assert again.status_code == 200 and len(calls) == 2


def test_gone_subscriptions_deleted_other_failures_ignored(client, keys, sent):
    calls, plan = sent
    site = Site(client)
    for name in ("gone410", "gone404", "err500", "boom", "ok"):
        _subscribe(site, f"https://push.example.com/{name}", client)
    plan.update({"https://push.example.com/gone410": 410, "https://push.example.com/gone404": 404,
                 "https://push.example.com/err500": 500, "https://push.example.com/boom": "boom"})
    w = site.workers[0]
    card = site.card(w)
    r = client.post("/api/worker/help", headers=w["h"],
                    json={"assignment_id": card["assignment_id"], "step_id": card["steps"][0]["id"]})
    assert r.status_code == 201  # 푸시가 실패해도 도움은 만들어진다
    assert len(calls) == 5
    assert _subs(site.employer_id) == ["https://push.example.com/boom", "https://push.example.com/err500",
                                       "https://push.example.com/ok"]


def test_help_201_even_if_dispatch_breaks(client, keys, monkeypatch):
    site = Site(client)
    _subscribe(site, "https://push.example.com/a", client)

    def broken(*_a, **_k):
        raise RuntimeError("pool closed")

    monkeypatch.setattr(push, "_submit", broken)
    w = site.workers[0]
    card = site.card(w)
    r = client.post("/api/worker/help", headers=w["h"], json={"assignment_id": card["assignment_id"]})
    assert r.status_code == 201


def test_reopen_after_acknowledge_pushes_again(client, keys, sent):
    calls, _ = sent
    site = Site(client)
    _subscribe(site, "https://push.example.com/a", client)
    h, card = _open_help(site)
    assert len(calls) == 1
    client.post(f"/api/employer/help/{h['id']}/acknowledge", headers=site.h)
    import ratelimit
    ratelimit.help_throttle.clear()
    site.help(site.workers[0], card["assignment_id"], card["steps"][0]["id"])
    assert len(calls) == 2


def test_subscribe_validation_upsert_and_delete(client):
    site = Site(client, task=False)
    other = Site(client, task=False)
    bad = client.post("/api/employer/push-subscriptions", headers=site.h,
                      json={"endpoint": "http://insecure.example.com/x", "keys": {"p256dh": "a", "auth": "b"}})
    assert bad.status_code == 422 and "알림" in bad.json()["detail"]
    _subscribe(site, "https://push.example.com/same", client)
    _subscribe(site, "https://push.example.com/same", client)  # 같은 주소는 한 줄
    assert _subs(site.employer_id) == ["https://push.example.com/same"]
    # 같은 기기에서 다른 사업장으로 로그인해 켜면 그 사업장으로 옮긴다
    _subscribe(other, "https://push.example.com/same", client)
    assert _subs(site.employer_id) == [] and _subs(other.employer_id) == ["https://push.example.com/same"]
    # 남의 구독은 지우지 못한다
    r = client.request("DELETE", "/api/employer/push-subscriptions", headers=site.h,
                       json={"endpoint": "https://push.example.com/same"})
    assert r.status_code == 204 and _subs(other.employer_id) == ["https://push.example.com/same"]
    r = client.request("DELETE", "/api/employer/push-subscriptions", headers=other.h,
                       json={"endpoint": "https://push.example.com/same"})
    assert r.status_code == 204 and _subs(other.employer_id) == []
    # 근로자 토큰은 안 됨
    site2 = Site(client)
    r = client.post("/api/employer/push-subscriptions", headers=site2.workers[0]["h"],
                    json={"endpoint": "https://push.example.com/w", "keys": {"p256dh": "a", "auth": "b"}})
    assert r.status_code == 403


def test_subscription_cap_drops_oldest(client, monkeypatch):
    monkeypatch.setattr(push, "MAX_SUBSCRIPTIONS", 3)
    site = Site(client, task=False)
    import clock
    from datetime import timedelta
    base = clock.utcnow()
    for i in range(5):
        monkeypatch.setattr(clock, "utcnow", lambda i=i: base + timedelta(seconds=i))
        _subscribe(site, f"https://push.example.com/{i}", client)
    assert _subs(site.employer_id) == [f"https://push.example.com/{i}" for i in (2, 3, 4)]
