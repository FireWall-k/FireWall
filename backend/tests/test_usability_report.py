"""3b-1 사용성 보고(manage.py usability-report, 명세 8.4) 시험.

가짜 이벤트로 지표 값을 직접 맞춰 보고, 출력(글·JSON)에 배정 id·근로자 id·이름·직무 제목이 없는지 본다.
"""
import json
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import manage  # noqa: E402
import usability  # noqa: E402
from database import SessionLocal  # noqa: E402
from live_site import Site  # noqa: E402
from models import Assignment, ClientEvent, Employer, HelpRequest  # noqa: E402

T0 = datetime(2030, 5, 1, 9, 0, 0)  # 다른 시험의 이벤트와 섞이지 않는 날


def _ev(db, emp, name, sec, *, aid=None, task=None, step=None, value=None, actor="worker"):
    db.add(ClientEvent(employer_id=emp, actor=actor, name=name, assignment_id=aid, task_id=task, step_id=step,
                       value_num=value, created_at=T0 + timedelta(seconds=sec)))


@pytest.fixture()
def site(client):
    """근로자 셋(이름이 보이는 이름), 직무 하나를 셋에게 보낸 사업장 + 가짜 이벤트.

    - 근로자0(배정 A): 3단계 혼자 끝냄. 단계 시간 10·20·30초, 다시 듣기 2번, [다 했어요] 1초 뒤 [이전](잘못 누름) 1번,
      중복 방지 1번, '멈출래요' 창에서 '계속할래요' 1번.
    - 근로자1(배정 B): 끝냈지만 도움 요청 1번(이벤트) → 혼자 아님. [다 했어요] 5초 뒤 [이전](잘못 누름 아님).
    - 근로자2(배정 C): 끝내지 않음. '멈출래요' 1번, 도움 요청 행(help_requests)만 1개.
    - 사업주: 보내기 40초·클릭 6번, 비활성 [보내기] 2번.
    """
    s = Site(client, n_workers=3)
    for i, w in enumerate(s.workers):
        r = client.patch(f"/api/workers/{w['id']}", headers=s.h, json={"display_name": f"홍길동{i}"})
        assert r.status_code == 200, r.text
    aids = [s.card(w)["assignment_id"] for w in s.workers]
    t = s.task["id"]
    e = s.employer_id
    with SessionLocal() as db:
        a, b, c = aids
        for x in (a, b):
            db.get(Assignment, x).status = "done"
        # 배정 A
        _ev(db, e, "step_view", 0, aid=a, task=t, step="s1")
        _ev(db, e, "step_replay", 3, aid=a, task=t, step="s1")
        _ev(db, e, "step_done", 10, aid=a, task=t, step="s1", value=10)
        _ev(db, e, "step_prev", 11, aid=a, task=t, step="s2")        # 1초 뒤 → step_back_quick
        _ev(db, e, "step_done", 31, aid=a, task=t, step="s1", value=20)
        _ev(db, e, "tap_debounced", 31.3, aid=a, task=t, step="s2")
        _ev(db, e, "step_replay", 40, aid=a, task=t, step="s2")
        _ev(db, e, "exit_cancel", 45, aid=a, task=t, step="s2")
        _ev(db, e, "step_view", 50, aid=a, task=t, step="s3")
        _ev(db, e, "step_done", 80, aid=a, task=t, step="s3")          # 값 없음 → step_view부터 30초
        # 배정 B
        _ev(db, e, "help_open", 100, aid=b, task=t, step="s1")
        _ev(db, e, "help_cancel", 101, aid=b, task=t, step="s1")
        _ev(db, e, "step_done", 110, aid=b, task=t, step="s1", value=40)
        _ev(db, e, "step_prev", 115, aid=b, task=t, step="s2")       # 5초 뒤 → 잘못 누름 아님
        # 배정 C
        _ev(db, e, "step_view", 200, aid=c, task=t, step="s1")
        _ev(db, e, "exit_confirm", 205, aid=c, task=t, step="s1")
        _ev(db, e, "offline_queued", 206, aid=c, task=t, step="s1")
        _ev(db, e, "offline_flushed", 207, value=1)
        db.add(HelpRequest(assignment_id=c, worker_id=s.workers[2]["id"], employer_id=e, step_id=None,
                           created_at=T0))
        # 사업주
        _ev(db, e, "task_send_done", 300, task=t, value=40, actor="employer")
        _ev(db, e, "send_click_count", 300, task=t, value=6, actor="employer")
        _ev(db, e, "send_click_disabled", 290, actor="employer")
        _ev(db, e, "send_click_disabled", 291, actor="employer")
        db.commit()
        code = db.get(Employer, e).workplace_code
    s.aids = aids
    s.code = code
    return s


def _report(site):
    with SessionLocal() as db:
        return usability.compute(db, since=date(2030, 5, 1), until=date(2030, 5, 1), workplace_code=site.code)


def test_metrics_match_spec_definitions(site):
    r = _report(site)
    assert r["jobs"] == 3
    ic = r["independent_completion"]
    assert (ic["jobs_done"], ic["jobs_alone"], ic["rate"]) == (2, 1, 0.5)
    assert (ic["people_done"], ic["people_alone"]) == (2, 1)
    mc = r["misclick"]
    assert (mc["step_back_quick"], mc["tap_debounced"]) == (1, 1)
    assert mc["per_job"] == round(2 / 3, 3)
    sp = r["step_performance"]
    assert sp["steps_done"] == 4
    assert sp["seconds_per_step"] == {"n": 4, "mean": 25.0, "median": 25.0}  # 10·20·30(시각 차이)·40
    assert (sp["replays"], sp["replays_per_step"]) == (2, 0.5)
    assert (sp["help_requests"], sp["help_per_step"], sp["help_cancel"]) == (1, 0.25, 1)
    assert (sp["exit_confirm"], sp["exit_cancel"], sp["stop_rate"]) == (1, 1, 0.5)
    assert (sp["offline_queued"], sp["offline_flushed"]) == (1, 1)
    em = r["employer"]
    assert em["send_seconds"] == {"n": 1, "mean": 40.0, "median": 40.0}
    assert em["send_clicks"]["mean"] == 6.0
    assert em["send_click_disabled"] == 2


def test_coach_override_breaks_independence(site):
    with SessionLocal() as db:
        _ev(db, site.employer_id, "coach_override", 60, aid=site.aids[0], step="s3")
        db.commit()
    ic = _report(site)["independent_completion"]
    assert (ic["jobs_done"], ic["jobs_alone"], ic["rate"]) == (2, 0, 0.0)


def test_filters_by_date_and_workplace(site, client):
    other = Site(client, task=False)
    with SessionLocal() as db:
        _ev(db, other.employer_id, "step_done", 5, value=99)
        db.commit()
        out_of_range = usability.compute(db, since=date(2030, 5, 2), workplace_code=site.code)
        mine = usability.compute(db, since=date(2030, 5, 1), until=date(2030, 5, 1), workplace_code=site.code)
        with pytest.raises(ValueError):
            usability.compute(db, workplace_code="없는코드")
    assert out_of_range["events"] == 0 and out_of_range["jobs"] == 0
    assert mine["step_performance"]["steps_done"] == 4  # 다른 사업장의 99초는 빠진다


def _forbidden(site) -> list[str]:
    return [*site.aids, *(w["id"] for w in site.workers), *(f"홍길동{i}" for i in range(3)), site.task["title"],
            site.employer_id, site.code]


def test_output_has_no_ids_or_names(site, capsys):
    r = _report(site)
    text = usability.format_report(r) + json.dumps(r, ensure_ascii=False)
    for bad in _forbidden(site):
        assert bad not in text, bad
    for args in ([], ["--json"]):
        manage.main(["usability-report", "--since", "2030-05-01", "--until", "2030-05-01",
                     "--workplace", site.code, *args])
        out = capsys.readouterr().out
        assert "혼자" in out or "independent_completion" in out
        for bad in _forbidden(site):
            assert bad not in out, bad


def test_cli_rejects_bad_date():
    with pytest.raises(SystemExit):
        manage.main(["usability-report", "--since", "5월 1일"])
