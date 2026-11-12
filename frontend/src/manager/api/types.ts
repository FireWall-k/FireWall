// 2차 사업주 화면의 새 계약 타입(p2/contract.md). 옛 화면 타입은 src/api.ts에 그대로 둔다.
// 필드 이름은 서버 응답과 똑같이 쓴다(snake_case). 영어 값(state 등)은 화면에 그대로 보이지 않고
// manager/copy.ts의 한국어 문구로 바꿔 보인다.

// 이 파일은 e2e(tsconfig.e2e)도 가져다 쓴다: src/api.ts(import.meta.env)를 import하지 않는다.

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

// ── 보내기 검사·보내기·받는 사람(2a-0). 새 계약 타입은 이 파일에만 둔다(tasks.md §1). ──

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

// ── 2b-1 만들고 보내기: 편집기 단계·후보·일괄 확인·자동 저장·미리보기(contract §3.3·3.4) ──


// 이 파일은 e2e 목(page.route)도 가져다 쓴다. src/api.ts는 import.meta.env를 써서 e2e tsconfig에서 타입 검사가
// 깨지므로 가져오지 않고, 단계·직무의 공통 칸을 여기에 그대로 적는다(src/api.ts Step·Task와 같은 칸).

/** 그림 4상태(src/api.ts PictureState와 같다). */
export type PictureState = "confirmed" | "auto_high" | "choose" | "none";

/** 근로자 화면 단계 모양(src/api.ts Step과 같은 칸). */
export interface StepBase {
  id: string;
  order: number;
  sentence: string;
  action_type: string;
  symbol_url: string | null;
  symbol_source: string;
  needs_fallback: boolean;
  tts_audio_url: string | null;
  picture_state?: PictureState;
  /** 근로자 '조심해요' 띠(2b-1). */
  safety_flag?: boolean;
}

/** (2a-0) 보낸 버전 정보. */
export interface TaskVersionInfo {
  current_no: number | null;
  has_unsent_changes: boolean;
}

/** 지금 그림의 출처. auto = 자동으로 붙음(✦), manual = 사업주가 후보·검색에서 고름, photo = 현장 사진. */
export type PictureSource = "auto" | "manual" | "photo";

export interface StepPicture {
  /** AAC 그림 id(그림 파일 이름) 또는 사진 media id. */
  card_id: string;
  url: string;
  /** 그림 이름(사진은 빈 글). */
  label: string;
  source: PictureSource;
}

/** 그림 후보 한 장. 적용은 POST …/steps/{sid}/picture에 그대로 보낸다. */
export interface PictureCandidate {
  card_id: string;
  url: string;
  label: string;
}

export type SplitSource = "rule" | "model" | "manual" | "";

export interface StepSplit {
  source: SplitSource;
  /** 늘 false(나눈 문장 확인은 입력 화면이 끝냄, contract §3.2). 화면은 쓰지 않는다. */
  needs_review: boolean;
  /** 원래 지시문에서 온 부분(편집기 원문 인용). 없으면 빈 글. */
  original_span: string;
}

/** 문장 점검 code. 화면 문구는 manager/copy.ts('20자가 넘어요', '어려운 말: 적재 → 쌓기', '~해요 체로 바꾸기'). */
export type LintCode = "too_long" | "hard_word" | "command_tone";

export interface LintItem {
  code: LintCode;
  /** hard_word일 때만: 어려운 말 → 쉬운 말. 나머지는 null. */
  from: string | null;
  to: string | null;
}

/** 조심 표시 출처. auto = '✦ 자동 제안'(보라), manual = 사업주가 스위치를 바꿈, '' = 정한 적 없음. */
export type SafetySource = "auto" | "manual" | "";

export interface StepSafety {
  flag: boolean;
  source: SafetySource;
  note: string;
}

/** 편집기 단계(EditorStepOut). 근로자 Step 칸 + 편집 칸. 확신 점수 숫자는 오지 않는다. */
export interface EditorStep extends StepBase {
  picture_state: PictureState;
  safety_flag: boolean;
  picture: StepPicture | null;
  /** 늘 빈 목록 — 후보는 GET /api/tasks/{id}/candidates가 모든 단계를 한 번에 준다. */
  candidates: PictureCandidate[];
  split: StepSplit;
  lint: LintItem[];
  safety: StepSafety;
  /** 이 단계 앞에서 묶음을 나눈다(9단계가 넘는 직무, 데이터만). */
  group_break: boolean;
  /** 이 단계를 고친 뒤의 직무 updated_at. 다음 자동 저장의 expected_updated_at으로 보낸다. */
  task_updated_at: string | null;
}

/** 편집기 직무(TaskOut). 단계가 EditorStep이다. */
export interface EditorTask {
  id: string;
  title: string;
  status: string;
  steps: EditorStep[];
  version: TaskVersionInfo | null;
  /** 오늘 배정 중 하는 중인 수(VersionNotice '{m}명 중 {k}명이 지금 하고 있어요'의 k). */
  in_progress_count: number;
  /** 이 직무를 받은 적 있는 근로자 수(VersionNotice의 m). */
  recipients_count: number;
  /** 마지막으로 고친 시각(naive UTC ISO). */
  updated_at: string | null;
}

/** GET /api/tasks/{id}/candidates — 모든 단계(확인한 단계 포함) 후보 최대 3장. 유료 모델 없이 찾는다. */
export interface TaskCandidates {
  steps: { step_id: string; candidates: PictureCandidate[] }[];
}

/** POST /api/tasks/{id}/pictures/confirm 요청. 응답은 EditorStep[](보낸 순서). 섞이면 422 code "not_confirmable". */
export interface PicturesConfirmRequest {
  step_ids: string[];
}

/** POST /api/tasks/{id}/steps/{sid}/picture 요청(후보·검색 결과 적용 → 확인함). label은 저장하지 않는다. */
export interface PictureApplyRequest {
  card_id: string;
  url: string;
  label?: string;
}

/** PATCH /api/tasks/{id}/steps/{sid} 요청(2b-1). 응답은 EditorStep(+ task_updated_at). */
export interface StepPatchRequest {
  sentence?: string;
  /** 보내면 safety.source = "manual"(같은 값이어도). */
  safety_flag?: boolean;
  safety_note?: string;
  group_break?: boolean;
  /** 600ms 자동 저장: 문장만 저장(음성·나누기 검사 없음). 칸을 벗어날 때 rewrite로 마무리한다. */
  defer_media?: boolean;
  /** 이 창이 마지막으로 본 직무 updated_at. 다르면 409 code "stale_edit"(다른 창에서 먼저 고침). */
  expected_updated_at?: string;
}

/** POST /api/tasks/{id}/steps/{sid}/tts. 합성하지 못했으면 null(기기 음성이 대신). */
export interface StepTtsOut {
  tts_url: string | null;
}

/** GET /api/tasks/{id}/preview 단계: 근로자 Step 모양 + 조심 + 묶음 경계. picture_state는 지금 편집 단계 그대로. */
export interface PreviewStep extends StepBase {
  safety_flag: boolean;
  group_break: boolean;
}

/** GET /api/tasks/{id}/preview(사업주 토큰, 기록 없음). */
export interface TaskPreview {
  title: string;
  steps: PreviewStep[];
}

/** 나누기 미리보기 한 줄에 2b-1에서 더한 칸, POST /api/tasks 단계에 그대로 돌려보낸다. */
export interface ConfirmedStepExtra {
  split?: { source: SplitSource; original_span?: string | null };
  /** 미리보기의 '✦ 자동 제안' 조심 표시. */
  safety_flag?: boolean;
}

/** 보내기·편집 API 오류 code(영어, 화면에 보이지 않음). 단계를 가리키면 step_ids가 함께 온다. */
export type EditorErrorCode = "not_confirmable" | "stale_edit" | "send_blocked" | "no_steps" | "archived";

// --- (2c) 오늘 현황과 도움(contract §5.2). 서버 schemas.py LiveOut·TimelineOut·CoachingCardOut과 같은 모양 ---

/** 근로자 상태 배지. 판정은 서버(live.py)가 한다. 화면은 이 값으로 색·아이콘·글만 고른다. */
export type LiveBadge = "help" | "help_acked" | "offline" | "stuck_suspect" | "in_progress" | "new" | "done" | "idle";

export interface LiveStep {
  id: string;
  source_step_id: string | null;
  order: number;
  sentence: string;
  thumb_url: string | null;
}

export interface LiveCurrent {
  assignment_id: string;
  task_id: string;
  task_title: string;
  version_no: number | null;
  done: number;
  total: number;
  step: LiveStep | null;
}

export interface LiveToday {
  assignment_id: string;
  task_title: string;
  status: "new" | "in_progress" | "done";
  is_next: boolean;
}

export interface LiveWorker {
  worker_id: string;
  display_name: string;
  initials: string;
  badge: LiveBadge;
  last_activity_at: string | null;
  last_signal_at: string | null;
  current: LiveCurrent | null;
  today: LiveToday[];
}

export interface LiveSummary {
  working: number;
  total_workers: number;
  open_help: number;
  stuck_steps: number;
  needs_check_tasks: number;
}

export interface LiveOut {
  server_now: string;
  summary: LiveSummary;
  workers: LiveWorker[];
  help: LiveHelp[];
}

/** 도움 요청 한 줄(src/api.ts EmployerHelp와 같은 모양 + 2c 칸). */
export interface LiveHelp {
  id: string;
  state: "open" | "acknowledged" | "cancelled" | "resolved";
  created_at: string;
  acknowledged_at: string | null;
  worker_id: string;
  worker_name: string;
  assignment_id: string;
  task_id: string;
  task_title: string;
  step_id: string | null;
  step_order: number | null;
  step_sentence: string | null;
  step_symbol_url: string | null;
  source_step_id?: string | null;
  step_thumb_url?: string | null;
}

export interface TimelineStep {
  step_id: string;
  source_step_id: string | null;
  order: number;
  sentence: string;
  thumb_url: string | null;
  completed: boolean;
  completed_at: string | null;
  duration_sec: number | null;
  replay_count: number;
  prev_count: number;
  help_count: number;
}

export interface TimelineAssignment {
  assignment_id: string;
  task_id: string;
  task_title: string;
  version_no: number | null;
  status: "new" | "in_progress" | "done";
  assigned_at: string;
  steps: TimelineStep[];
}

export interface TimelineEvent {
  at: string;
  kind: "step_done" | "help_open" | "help_ack" | "help_resolved" | "help_cancelled";
  assignment_id: string;
  step_order: number | null;
}

export interface TimelineOut {
  worker_id: string;
  display_name: string;
  date: string;
  assignments: TimelineAssignment[];
  events: TimelineEvent[];
}

export interface CoachingSignals {
  replay_avg: number;
  duration_avg_sec: number;
  help_count: number;
  runs: number;
}

export type CoachingSuggestion = "photo" | "split" | "easy_words";

export interface CoachingCard {
  task_id: string;
  task_title: string;
  source_step_id: string;
  /** 지금 편집 화면의 단계 id. 편집 화면에서 지운 단계면 null. */
  step_id: string | null;
  sentence: string;
  thumb_url: string | null;
  signals: CoachingSignals;
  suggestion: CoachingSuggestion;
  after: (CoachingSignals & { since_version_no: number }) | null;
}

export interface PushConfig {
  enabled: boolean;
  public_key: string | null;
}

/** 측정 이벤트 이름(contract §5.2, 명세 8.4). 서버가 역할마다 이 목록만 받는다. */
export type EmployerEventName = "task_create_start" | "task_send_done" | "send_click_disabled" | "send_click_count";
export type WorkerEventName = "step_view" | "step_replay" | "step_prev" | "help_open";

export interface ClientEvent<N extends string = string> {
  name: N;
  task_id?: string | null;
  step_id?: string | null;
  value_num?: number | null;
  at: string;
}
