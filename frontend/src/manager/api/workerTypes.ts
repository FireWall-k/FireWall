// 2d 근로자·사업장 설정 계약 타입(contract §6.2). types.ts는 2b-1·2c가 함께 늘리는 파일이라 겹치지 않게 따로 둔다.
import type { A11yPrefs } from "../../api";

/** 오늘 상태 배지. 앞에 있는 것이 이긴다: 도움 > 도움 가는 중 > 다 함 > 하는 중 > 시작 전 > 없음. */
export type TodayBadge = "help" | "help_coming" | "done" | "in_progress" | "not_started" | "none";

/** 동의 상태: 둘 다 있음 / 개인정보만 있음(자동 처리 미동의) / 개인정보 동의 없음. */
export type ConsentState = "complete" | "ai_missing" | "missing";

/** GET /api/workers 한 줄. 전체 코드는 없다(눈 단추 → reveal). */
export interface WorkerRow {
  id: string;
  display_name: string;
  access_code_hint: string;
  access_code_length: number;
  code_length: number;
  note: string;
  ai_note_allowed: boolean;
  ai_consent: boolean;
  personal_info_consent: boolean;
  name_ambiguous: boolean;
  a11y_prefs: A11yPrefs;
  today_badge: TodayBadge;
  /** 6일 전 → 오늘, 날마다 다 한 배정 수. */
  done_7d: number[];
  help_7d: number;
  consent_state: ConsentState;
}

/** 만들기·새 번호 응답: 전체 코드를 볼 수 있는 순간. */
export interface WorkerWithCode extends WorkerRow {
  access_code: string;
}

export interface DeleteWorkerResult {
  ok: boolean;
  wal_checkpointed?: boolean;
  name_mentions?: { task_id: string; title: string }[];
}

/** GET·PATCH /api/workplace */
export interface WorkplaceSettings {
  workplace_code: string;
  org_name: string;
  device_link: string;
  teacher_title: string;
  worker_defaults: A11yPrefs;
}

export interface WorkplacePatch {
  org_name?: string;
  teacher_title?: string;
  worker_defaults?: Partial<A11yPrefs>;
}

export interface WorkerDayStat {
  day: string;
  assigned: number;
  done: number;
  steps_done: number;
  help: number;
  work_sec: number;
}

export interface WorkerStepStat {
  task_id: string;
  task_title: string;
  order: number;
  sentence: string;
  samples: number;
  avg_duration_sec: number;
  replay_count: number;
  help_count: number;
}

/** GET /api/employer/workers/{id}/stats?days=7 */
export interface WorkerStats {
  worker_id: string;
  days: number;
  daily: WorkerDayStat[];
  steps: WorkerStepStat[];
  avg_step_sec: number;
}

export type ConsentType = "personal_info" | "ai_processing";
export type ConsentSubject = "self" | "guardian";

export interface Consent {
  id: string;
  consent_type: ConsentType;
  subject: ConsentSubject;
  policy_version: string;
  granted_at: string;
  revoked_at: string | null;
  recorded_by: string;
}
