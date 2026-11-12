// 근로자·설정 화면 시험이 함께 쓰는 서버 응답 모양(contract §6.2).
import { DEFAULT_A11Y_PREFS } from "../../src/api";
import type { WorkerRow, WorkerStats, WorkplaceSettings } from "../../src/manager/api/workerTypes";

export function workerRow(over: Partial<WorkerRow> = {}): WorkerRow {
  return {
    id: "w1",
    display_name: "김민지",
    access_code_hint: "34",
    access_code_length: 4,
    code_length: 4,
    note: "",
    ai_note_allowed: false,
    ai_consent: false,
    personal_info_consent: true,
    name_ambiguous: false,
    a11y_prefs: { ...DEFAULT_A11Y_PREFS },
    today_badge: "in_progress",
    done_7d: [0, 1, 0, 2, 1, 0, 1],
    help_7d: 2,
    consent_state: "ai_missing",
    ...over,
  };
}

export function workplace(over: Partial<WorkplaceSettings> = {}): WorkplaceSettings {
  return {
    workplace_code: "DEMO01",
    org_name: "햇살카페",
    device_link: "http://localhost:5173/w?site=DEMO01",
    teacher_title: "선생님",
    worker_defaults: { ...DEFAULT_A11Y_PREFS },
    ...over,
  };
}

export function stats(over: Partial<WorkerStats> = {}): WorkerStats {
  const days = ["2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08", "2026-11-09", "2026-11-10"];
  return {
    worker_id: "w1",
    days: 7,
    daily: days.map((day, i) => ({ day, assigned: 1, done: i % 2, steps_done: 3, help: i === 6 ? 1 : 0, work_sec: 120 })),
    steps: [
      { task_id: "t1", task_title: "컵 씻기", order: 1, sentence: "컵을 물에 넣어요", samples: 3, avg_duration_sec: 148, replay_count: 2, help_count: 1 },
      { task_id: "t1", task_title: "컵 씻기", order: 2, sentence: "컵을 닦아요", samples: 3, avg_duration_sec: 40, replay_count: 0, help_count: 0 },
    ],
    avg_step_sec: 94,
    ...over,
  };
}
