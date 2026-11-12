"""2c 측정 이벤트 시험 (contract §5.2, 명세 8.4).

지키는 것: 역할마다 정한 이름만(다르면 422), 한 번에 50건까지, 근로자·사업주 토큰 모두, 개인정보 칸 없음,
남의 직무 id는 비움, 엉터리 시각은 서버 시각, 토큰 없으면 401.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, select  # noqa: E402

import clock  # noqa: E402
import events  # noqa: E402
from database import SessionLocal, engine  # noqa: E402
from live_site import Site  # noqa: E402
from models import ClientEvent  # noqa: E402


def _rows(employer_id):
    with SessionLocal() as db:
        return db.scalars(select(ClientEvent).where(ClientEvent.employer_id == employer_id)
                          .order_by(ClientEvent.created_at, ClientEvent.name)).all()


def test_worker_and_employer_events_saved(client):
    site = Site(client)
    w = site.workers[0]
    step_id = site.card(w)["steps"][0]["id"]
    r = client.post("/api/events", headers=w["h"], json={"events": [
        {"name": "step_view", "task_id": site.task["id"], "step_id": step_id},
        {"name": "step_replay", "task_id": site.task["id"], "step_id": step_id, "value_num": 2},
        {"name": "step_prev"}, {"name": "help_open"}]})
    assert r.status_code == 204, r.text
    r = client.post("/api/events", headers=site.h, json={"events": [
        {"name": "task_create_start"}, {"name": "task_send_done", "task_id": site.task["id"], "value_num": 41.5},
        {"name": "send_click_disabled"}, {"name": "send_click_count", "value_num": 7}]})
    assert r.status_code == 204, r.text
    rows = _rows(site.employer_id)
    assert sorted((x.actor, x.name) for x in rows) == sorted(
        [("worker", n) for n in ("step_view", "step_replay", "step_prev", "help_open")]
        + [("employer", n) for n in ("task_create_start", "task_send_done", "send_click_disabled",
                                     "send_click_count")])
    done = next(x for x in rows if x.name == "task_send_done")
    assert done.task_id == site.task["id"] and done.value_num == 41.5
    replay = next(x for x in rows if x.name == "step_replay")
    assert replay.step_id == step_id and replay.value_num == 2


def test_event_names_checked_per_role(client):
    site = Site(client)
    w = site.workers[0]
    for headers, name in ((w["h"], "task_send_done"), (site.h, "step_view"), (w["h"], "keylog"),
                          (site.h, "step_done")):
        r = client.post("/api/events", headers=headers, json={"events": [{"name": "step_prev"}, {"name": name}]})
        assert r.status_code == 422, (name, r.text)
        assert "detail" in r.json()
    assert _rows(site.employer_id) == []  # 하나라도 틀리면 아무것도 남기지 않는다


def test_event_batch_limits_and_auth(client):
    site = Site(client, task=False)
    assert client.post("/api/events", headers=site.h,
                       json={"events": [{"name": "send_click_count"}] * 51}).status_code == 422
    assert client.post("/api/events", headers=site.h, json={"events": []}).status_code == 422
    assert client.post("/api/events", headers=site.h,
                       json={"events": [{"name": "send_click_count"}] * 50}).status_code == 204
    assert client.post("/api/events", json={"events": [{"name": "send_click_count"}]}).status_code == 401


def test_no_personal_columns():
    cols = {c["name"] for c in inspect(engine).get_columns("client_events")}
    assert cols == {"id", "employer_id", "actor", "name", "task_id", "step_id", "value_num", "created_at"}


def test_foreign_task_id_dropped_and_bad_ids_cleaned(client):
    site = Site(client)
    other = Site(client)
    r = client.post("/api/events", headers=site.h, json={"events": [
        {"name": "task_send_done", "task_id": other.task["id"]},
        {"name": "send_click_count", "task_id": "김민지 님", "step_id": "<script>"}]})
    assert r.status_code == 204
    rows = _rows(site.employer_id)
    assert all(x.task_id is None and x.step_id is None for x in rows)


def test_event_time_clamped(client):
    site = Site(client, task=False)
    now = clock.utcnow()
    good = now - timedelta(minutes=3)
    r = client.post("/api/events", headers=site.h, json={"events": [
        {"name": "send_click_count", "value_num": 1, "at": good.isoformat() + "Z"},
        {"name": "send_click_count", "value_num": 2, "at": "9999-12-31T23:00:00-09:00"},
        {"name": "send_click_count", "value_num": 3, "at": "2001-01-01T00:00:00Z"},
        {"name": "send_click_count", "value_num": 4, "at": "엉터리"}]})
    assert r.status_code == 204, r.text
    by = {x.value_num: x.created_at for x in _rows(site.employer_id)}
    assert abs((by[1] - good).total_seconds()) < 1
    for v in (2, 3, 4):
        assert abs((by[v] - now).total_seconds()) < 5


def test_event_rate_limit(client, monkeypatch):
    monkeypatch.setattr(events, "events_throttle", events.LoginThrottle(max_failures=2, window_sec=60))
    site = Site(client, task=False)
    codes = [client.post("/api/events", headers=site.h, json={"events": [{"name": "send_click_count"}]}).status_code
             for _ in range(3)]
    assert codes == [204, 204, 429]
