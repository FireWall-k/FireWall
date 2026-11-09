// 2차 사업주 화면의 새 계약 타입(p2/contract.md). 옛 화면 타입은 src/api.ts에 그대로 둔다.
// 필드 이름은 서버 응답과 똑같이 쓴다(snake_case). 영어 값(state 등)은 화면에 그대로 보이지 않고
// manager/copy.ts의 한국어 문구로 바꿔 보인다.

/** 직무 목록 걸러보기(contract §2.1). 서로 겹친다: 확인할 것이 있는 초안은 '초안'과 '확인 필요' 양쪽에 셈. */
export type TaskFilter = "all" | "draft" | "needs_check" | "published" | "archived";

export const TASK_FILTERS: readonly TaskFilter[] = ["all", "draft", "needs_check", "published", "archived"];

/** 직무 한 개의 상태(TaskSummaryOut.state). */
export type TaskListState = "draft" | "published" | "archived";

export interface TaskRecipient {
  worker_id: string;
  /** 이름 앞 글자(아바타). 실명 전체는 목록에 싣지 않는다. */
  initials: string;
}

/** contract §2.1 TaskSummaryOut. */
export interface TaskSummaryOut {
  id: string;
  title: string;
  state: TaskListState;
  /** 확인할 단계 수(그림·자동 결과). 0보다 크면 '확인 필요 n' 배지. */
  needs_check_count: number;
  /** 보낸 뒤 고쳤지만 아직 다시 보내지 않음 → '고친 내용 안 보냄' 배지. */
  has_unsent_changes: boolean;
  step_count: number;
  /** 대표 그림(첫 단계 그림). 없으면 null. */
  cover_url: string | null;
  /** 받은 사람 최대 3명. */
  recipients: TaskRecipient[];
  /** recipients 밖에 더 있는 수. */
  recipients_more: number;
  /** 마지막으로 고친 시각(naive UTC ISO). */
  updated_at: string;
  /** 보낸 적이 없으면 null. */
  current_version_no: number | null;
}

export type TaskCounts = Record<TaskFilter, number>;

/** GET /api/employer/tasks 응답. */
export interface TaskListOut {
  items: TaskSummaryOut[];
  counts: TaskCounts;
}
