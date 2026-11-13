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
    _subscribe(site, "https://fcm.googleapis.com/fcm/send/a", client)
    r_help, _card = _open_help(site)
    assert r_help["state"] == "open"
    assert calls == []


def test_sends_to_each_subscription_without_worker_name(client, keys, sent):
    calls, _ = sent
    site = Site(client)
    other = Site(client, task=False)
    _subscribe(site, "https://fcm.googleapis.com/fcm/send/a", client)
    _subscribe(site, "https://fcm.googleapis.com/fcm/send/b", client)
    _subscribe(other, "https://fcm.googleapis.com/fcm/send/other", client)
    w = site.workers[0]
    card = site.card(w)
    r = client.post("/api/worker/help", headers=w["h"],
                    json={"assignment_id": card["assignment_id"], "step_id": card["steps"][0]["id"],
                          "client_request_id": "p1"})
    assert r.status_code == 201
    assert sorted(c["endpoint"] for c in calls) == ["https://fcm.googleapis.com/fcm/send/a", "https://fcm.googleapis.com/fcm/send/b"]
    for c in calls:
        assert c["data"] == {"title": "잡카드", "body": "도움 요청이 있어요", "url": "/manager#help"}
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
        _subscribe(site, f"https://fcm.googleapis.com/fcm/send/{name}", client)
    plan.update({"https://fcm.googleapis.com/fcm/send/gone410": 410, "https://fcm.googleapis.com/fcm/send/gone404": 404,
                 "https://fcm.googleapis.com/fcm/send/err500": 500, "https://fcm.googleapis.com/fcm/send/boom": "boom"})
    w = site.workers[0]
    card = site.card(w)
    r = client.post("/api/worker/help", headers=w["h"],
                    json={"assignment_id": card["assignment_id"], "step_id": card["steps"][0]["id"]})
    assert r.status_code == 201  # 푸시가 실패해도 도움은 만들어진다
    assert len(calls) == 5
    assert _subs(site.employer_id) == ["https://fcm.googleapis.com/fcm/send/boom", "https://fcm.googleapis.com/fcm/send/err500",
                                       "https://fcm.googleapis.com/fcm/send/ok"]


def test_help_201_even_if_dispatch_breaks(client, keys, monkeypatch):
    site = Site(client)
    _subscribe(site, "https://fcm.googleapis.com/fcm/send/a", client)

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
    _subscribe(site, "https://fcm.googleapis.com/fcm/send/a", client)
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
    _subscribe(site, "https://fcm.googleapis.com/fcm/send/same", client)
    _subscribe(site, "https://fcm.googleapis.com/fcm/send/same", client)  # 같은 주소는 한 줄
    assert _subs(site.employer_id) == ["https://fcm.googleapis.com/fcm/send/same"]
    # 같은 기기에서 다른 사업장으로 로그인해 켜면 그 사업장으로 옮긴다
    _subscribe(other, "https://fcm.googleapis.com/fcm/send/same", client)
    assert _subs(site.employer_id) == [] and _subs(other.employer_id) == ["https://fcm.googleapis.com/fcm/send/same"]
    # 남의 구독은 지우지 못한다
    r = client.request("DELETE", "/api/employer/push-subscriptions", headers=site.h,
                       json={"endpoint": "https://fcm.googleapis.com/fcm/send/same"})
    assert r.status_code == 204 and _subs(other.employer_id) == ["https://fcm.googleapis.com/fcm/send/same"]
    r = client.request("DELETE", "/api/employer/push-subscriptions", headers=other.h,
                       json={"endpoint": "https://fcm.googleapis.com/fcm/send/same"})
    assert r.status_code == 204 and _subs(other.employer_id) == []
    # 근로자 토큰은 안 됨
    site2 = Site(client)
    r = client.post("/api/employer/push-subscriptions", headers=site2.workers[0]["h"],
                    json={"endpoint": "https://fcm.googleapis.com/fcm/send/w", "keys": {"p256dh": "a", "auth": "b"}})
    assert r.status_code == 403


def test_subscription_cap_drops_oldest(client, monkeypatch):
    monkeypatch.setattr(push, "MAX_SUBSCRIPTIONS", 3)
    site = Site(client, task=False)
    import clock
    from datetime import timedelta
    base = clock.utcnow()
    for i in range(5):
        monkeypatch.setattr(clock, "utcnow", lambda i=i: base + timedelta(seconds=i))
        _subscribe(site, f"https://fcm.googleapis.com/fcm/send/{i}", client)
    assert _subs(site.employer_id) == [f"https://fcm.googleapis.com/fcm/send/{i}" for i in (2, 3, 4)]


def test_endpoint_only_known_push_hosts(client):
    """내부 주소로 POST를 보내게 하지 못한다(SSRF). 알려진 푸시 서비스 호스트의 https 443만 받는다."""
    site = Site(client, task=False)
    keys = {"p256dh": "a", "auth": "b"}
    for bad in ("https://127.0.0.1:8000/api/anything", "https://169.254.169.254/latest/meta-data",
                "https://localhost/x", "https://10.0.0.5/admin", "https://[::1]/x",
                "https://fcm.googleapis.com.evil.example/x", "https://evilfcm.googleapis.com/x",
                "https://fcm.googleapis.com:8443/x", "https://user@fcm.googleapis.com/x",
                "https://fcm.googleapis.com:99999/x", "http://fcm.googleapis.com/x",
                # 백슬래시: urlparse는 '...fcm.googleapis.com'으로 읽지만 urllib3는 127.0.0.1·evil.com에 연결한다
                "https://127.0.0.1\\.fcm.googleapis.com/x", "https://evil.com\\.fcm.googleapis.com/",
                "https://127.0.0.1\\@fcm.googleapis.com/x", "https://fcm.googleapis.com\t.evil/x",
                "https://127.0.0.1%2f.fcm.googleapis.com/x", "https://fcm.googleapis.com/x\x00y"):
        r = client.post("/api/employer/push-subscriptions", headers=site.h, json={"endpoint": bad, "keys": keys})
        assert r.status_code == 422, bad
        assert r.json()["detail"].startswith("알림 주소가 올바르지 않아요")
    for good in ("https://fcm.googleapis.com/fcm/send/abc", "https://updates.push.services.mozilla.com/wpush/v2/x",
                 "https://web.push.apple.com/QAbc", "https://db5p.notify.windows.com/w/?token=x",
                 "https://FCM.googleapis.com./fcm/send/up"):
        r = client.post("/api/employer/push-subscriptions", headers=site.h, json={"endpoint": good, "keys": keys})
        assert r.status_code == 201, good
    assert len(_subs(site.employer_id)) == 5


def test_short_timeout_per_subscription(client, keys, sent):
    calls, _plan = sent
    seen = []
    orig = push.webpush

    def spy(**kw):
        seen.append(kw["timeout"])
        return orig(**kw)

    push.webpush = spy
    try:
        site = Site(client)
        _subscribe(site, "https://fcm.googleapis.com/fcm/send/t", client)
        _open_help(site)
    finally:
        push.webpush = orig
    assert seen == [(3, 5)]


def test_one_slow_tenant_does_not_starve_others(client, keys, monkeypatch):
    """한 사업장의 느린 구독 20개와 도움 여러 건이 있어도 다른 사업장 푸시는 바로 나간다(사업장마다 한 번에 하나)."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    pool = ThreadPoolExecutor(max_workers=2)
    monkeypatch.setattr(push, "_submit", lambda fn, *a: pool.submit(push._safe, fn, *a))
    sent_at: dict[str, float] = {}
    a_calls = []
    lock = threading.Lock()

    a_done_at_b: list[int] = []

    def fake_webpush(subscription_info, data, vapid_private_key, vapid_claims, ttl, timeout):
        ep = subscription_info["endpoint"]
        if "/slow" in ep:
            with lock:
                a_calls.append(ep)
            time.sleep(0.1)
        else:
            sent_at[ep] = time.monotonic()
            with lock:
                a_done_at_b.append(len(a_calls))

    monkeypatch.setattr(push, "webpush", fake_webpush)
    a = Site(client, n_workers=3)
    b = Site(client)
    for i in range(20):
        _subscribe(a, f"https://fcm.googleapis.com/fcm/send/slow{i}", client)
    _subscribe(b, "https://fcm.googleapis.com/fcm/send/fast", client)
    for w in a.workers:  # 도움 3건 → 한 번 돌고, 도는 중에 온 2건은 '한 번 더' 하나로 합친다
        card = a.card(w)
        a.help(w, card["assignment_id"], card["steps"][0]["id"])
    t0 = time.monotonic()
    _open_help(b)
    deadline = time.monotonic() + 10
    while "https://fcm.googleapis.com/fcm/send/fast" not in sent_at and time.monotonic() < deadline:
        time.sleep(0.01)
    # 시간 대신 순서로 단언한다(SQLite 잠금 대기로 가끔 1초 안팎 늦어도 흔들리지 않게).
    # A는 40번 x 0.1초 = 4초 걸린다. B는 A가 첫 바퀴(20번)를 다 끝내기 전에 받아야 한다.
    assert "https://fcm.googleapis.com/fcm/send/fast" in sent_at
    assert a_done_at_b and a_done_at_b[0] < 20, a_done_at_b
    assert sent_at["https://fcm.googleapis.com/fcm/send/fast"] - t0 < 2.0
    pool.shutdown(wait=True)
    # 사업장 A는 한 번 + 합친 한 번 더 = 40번(도움 3건마다 20번씩 60번이 아니다). 요청을 잃지는 않는다.
    assert len(a_calls) == 40
    assert not push._running and not push._again
