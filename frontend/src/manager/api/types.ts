// 2차 사업주 작업대 API 계약 타입(p2/contract.md). 새 계약 타입은 이 파일에만 둔다(tasks.md §1).

/** 보내기를 막는 항목 code. 화면에는 영어 code를 보이지 않는다(contract §0). */
export type SendBlockCode = "no_picture" | "unconfirmed_auto" | "unreviewed_split" | "no_steps" | "archived";
/** 막지 않는 경고 code(2b-1부터 채움). */
export type SendWarnCode = "too_long" | "command_tone" | "auto_caution";

/** done/total: 통과한 단계 수/살펴본 단계 수. total=0인 줄은 화면에 보이지 않는다. */
export interface SendBlock {
  code: SendBlockCode;
  done: number;
  total: number;
  step_ids: string[];
}

export interface SendWarning {
  code: SendWarnCode;
  count: number;
  step_ids: string[];
}

/** GET /api/tasks/{id}/send-check. 서버는 code와 숫자만 보낸다(label 없음). */
export interface SendCheck {
  ok: boolean;
  blocking: SendBlock[];
  warnings: SendWarning[];
}

/** "today" | "tomorrow" | "YYYY-MM-DD"(현지 날짜). */
export type SendDay = "today" | "tomorrow" | string;

export type SendOutcome = "created" | "repinned" | "unchanged" | "kept" | "kept_in_progress";

export interface SendResultItem {
  worker_id: string;
  display_name: string;
  outcome: SendOutcome;
}

/** POST /api/tasks/{id}/send. 토스트 문구는 화면이 results로 만든다(message 칸 없음). */
export interface SendResult {
  version_no: number;
  version_created: boolean;
  day: string;
  results: SendResultItem[];
}

export type TodayStatus = "none" | "not_started" | "in_progress" | "done";

/** GET /api/tasks/{id}/recipients */
export interface Recipients {
  last_batch_worker_ids: string[];
  all_ever_worker_ids: string[];
  workplace_last_batch_worker_ids: string[];
  today_status: Record<string, TodayStatus>;
}
