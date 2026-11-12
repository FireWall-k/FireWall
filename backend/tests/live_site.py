"""2c 시험이 함께 쓰는 사업장 만들기 도우미(test_live·test_push·test_events).

데모 사업장과 섞이지 않게 시험마다 새 사업장을 DB에 바로 만들고, 근로자·직무·보내기는 실제 API로 한다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from auth import make_token
from conftest import auth, give_pictures
from database import SessionLocal
from models import Employer


class Site:
    def __init__(self, client, n_workers: int = 1, task: bool = True):
        self.client = client
        with SessionLocal() as db:
            e = Employer(login_id=f"live-{uuid.uuid4().hex[:10]}", password_hash="x", name="사장", org_name="현황")
            db.add(e)
            db.commit()
            self.employer_id = e.id
        self.token = make_token(self.employer_id, "employer")
        self.h = auth(self.token)
        self.workers = [self.add_worker(f"근로자{i}") for i in range(n_workers)]
        self.task = None
        if task:
            self.task = self.new_task()
            self.send(self.task["id"], [w["id"] for w in self.workers])

    def add_worker(self, name: str) -> dict:
        r = self.client.post("/api/workers", json={"display_name": name}, headers=self.h)
        assert r.status_code == 201, r.text
        w = r.json()
        w["h"] = auth(make_token(w["id"], "worker"))
        return w

    def new_task(self) -> dict:
        r = self.client.post("/api/tasks", json={"raw_input": "상자를 옮기고 수량을 확인하세요"}, headers=self.h)
        assert r.status_code == 201, r.text
        give_pictures(self.client, self.token, r.json()["id"])
        return self.client.get(f"/api/tasks/{r.json()['id']}", headers=self.h).json()

    def send(self, task_id: str, worker_ids: list[str]):
        r = self.client.post(f"/api/tasks/{task_id}/send", headers=self.h,
                             json={"worker_ids": worker_ids, "day": "today"})
        assert r.status_code == 200, r.text
        return r.json()

    def card(self, w: dict, task_id: str | None = None) -> dict:
        r = self.client.get("/api/worker/me/today?include_done=true", headers=w["h"])
        assert r.status_code == 200, r.text
        tid = task_id or self.task["id"]
        return [c for c in r.json() if c["task_id"] == tid][-1]

    def log(self, w: dict, aid: str, sid: str, **kw):
        body = {"assignment_id": aid, "step_id": sid, "duration_sec": 3.0, "replay_count": 0, "stuck": False}
        body.update(kw)
        r = self.client.post("/api/performance-logs", headers=w["h"], json=body)
        assert r.status_code in (200, 201), r.text
        return r

    def presence(self, w: dict, aid: str, sid: str | None, *, started: datetime | None = None,
                 sent: datetime | None = None, replay: int = 0, prev: int = 0, raw: dict | None = None):
        sent = sent or datetime(2026, 1, 1, 0, 0, 0)
        started = started or sent
        body = {"assignment_id": aid, "step_id": sid, "step_started_at": started.isoformat() + "Z",
                "client_sent_at": sent.isoformat() + "Z", "replay_count": replay, "prev_count": prev}
        if raw:
            body.update(raw)
        return self.client.post("/api/worker/presence", headers=w["h"], json=body)

    def live(self) -> dict:
        import live
        live._cache.clear()
        r = self.client.get("/api/employer/live", headers=self.h)
        assert r.status_code == 200, r.text
        return r.json()

    def worker_live(self, w: dict) -> dict:
        return next(x for x in self.live()["workers"] if x["worker_id"] == w["id"])

    def help(self, w: dict, aid: str, sid: str | None):
        r = self.client.post("/api/worker/help", headers=w["h"],
                             json={"assignment_id": aid, "step_id": sid, "client_request_id": uuid.uuid4().hex})
        assert r.status_code in (200, 201), r.text
        return r.json()


class FakeClock:
    """clock.utcnow를 옮길 수 있는 시계(시작 = 지금)."""

    def __init__(self, monkeypatch):
        import clock
        self.base = clock.utcnow()
        self.offset = 0.0
        monkeypatch.setattr(clock, "utcnow", lambda: self.base + timedelta(seconds=self.offset))

    def at(self, seconds: float) -> None:
        self.offset = seconds

    def now(self) -> datetime:
        return self.base + timedelta(seconds=self.offset)
