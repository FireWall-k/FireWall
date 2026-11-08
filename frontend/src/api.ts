// 백엔드 계약을 그대로 비추는 타입 + 호출 함수.
// 이 파일이 프론트엔드 <-> 백엔드 경계의 전부다. (인증 토큰 부착 포함)

import { ApiError, AuthError, NetworkError } from "./apiErrors";
import { saveWorkplaceName } from "./workerCodes";

export { ApiError, AuthError, NetworkError };

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

// --- 인증 상태 (localStorage 유지) ---
const TOKEN_KEY = "jobcard_token";
const ROLE_KEY = "jobcard_role";
const NAME_KEY = "jobcard_name";

export type Role = "employer" | "worker";

export interface AuthState {
  token: string;
  role: Role;
  displayName: string;
}

export function getAuth(): AuthState | null {
  const token = localStorage.getItem(TOKEN_KEY);
  const role = localStorage.getItem(ROLE_KEY) as Role | null;
  const displayName = localStorage.getItem(NAME_KEY) ?? "";
  if (!token || !role) return null;
  return { token, role, displayName };
}

function setAuth(a: AuthState) {
  localStorage.setItem(TOKEN_KEY, a.token);
  localStorage.setItem(ROLE_KEY, a.role);
  localStorage.setItem(NAME_KEY, a.displayName);
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ROLE_KEY);
  localStorage.removeItem(NAME_KEY);
}

// --- 타입 ---
export interface Step {
  id: string;
  order: number;
  sentence: string;
  action_type: string;
  symbol_url: string | null;
  symbol_source: string;
  needs_fallback: boolean;
  tts_audio_url: string | null;
  /**
   * 그림 4상태(contract §2). confirmed = 사업주가 확인함, auto_high = 자동으로 고름(확인 필요),
   * choose = 그림은 있으나 골라 주세요, none = 그림 없음(보내기 막힘). 예전 서버는 이 필드가 없다.
   */
  picture_state?: PictureState;
}

export type PictureState = "confirmed" | "auto_high" | "choose" | "none";

/** 근로자 화면 설정(contract §4.1). 서버는 늘 8개 키를 채워 준다. */
export interface A11yPrefs {
  font_size: "normal" | "large";
  /** 단계에 들어가면 소리를 한 번 자동으로 읽는다(창업자 결정 4, 기본 켬). */
  autoplay_sound: boolean;
  tts_rate: 0.8 | 0.9 | 1.0;
  sfx: boolean;
  vibration: boolean;
  praise: "normal" | "quiet";
  hand: "right" | "left";
  contrast: "normal" | "high";
}

export const DEFAULT_A11Y_PREFS: A11yPrefs = {
  font_size: "normal",
  autoplay_sound: true,
  tts_rate: 0.9,
  sfx: true,
  vibration: false,
  praise: "normal",
  hand: "right",
  contrast: "normal",
};

export type HelpState = "open" | "acknowledged" | "cancelled" | "resolved";

/** 도움 요청(contract §7 공통 응답). 근로자 쪽 호출은 worker/workerApi.ts가 만든다. */
export interface HelpOut {
  id: string;
  assignment_id: string;
  step_id: string | null;
  step_order: number | null;
  state: HelpState;
  resolution: string | null;
  created_at: string;
  acknowledged_at: string | null;
  cancelled_at: string | null;
  resolved_at: string | null;
}

/** 사업주 화면 도움 요청 목록 한 줄(contract §7.4). 단계가 지워졌으면 step_* 는 null. */
export interface EmployerHelp {
  id: string;
  state: HelpState;
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
}

export interface Task {
  id: string;
  title: string;
  status: string;
  steps: Step[];
}

export interface TodayCard {
  assignment_id: string;
  task_id: string;
  task_title: string;
  steps: Step[];
}

export interface HistoryStep extends Step {
  completed: boolean;
}

export interface HistoryCard {
  assignment_id: string;
  task_id: string;
  task_title: string;
  assigned_date: string; // YYYY-MM-DD
  status: string;
  steps: HistoryStep[];
}

export interface StepStat {
  order: number;
  sentence: string;
  completed: boolean;
  duration_sec: number;
  replay_count: number;
  stuck: boolean;
}

export interface AacMatch {
  asset_id: string;
  group_id: string;
  job: string;
  asset_type: string;
  label: string;
  image_url: string;
  score: number;
}

export interface AacSearchResult {
  query: string;
  matches: AacMatch[];
}

/** 자동으로 그림을 못 고른 이유. low_margin이면 후보를 보여주고 사람이 고른다. */
export type MatchReason = "accepted" | "no_candidate" | "low_score" | "low_margin";

export interface StepSymbolCandidates {
  step_id: string;
  reason: MatchReason;
  candidates: AacMatch[];
}

export interface Dashboard {
  task_id: string;
  task_title: string;
  total_steps: number;
  completed_steps: number;
  completion_rate: number;
  stuck_steps: number[];
  steps: StepStat[];
}

export interface DashboardWorker {
  worker_id: string;
  display_name: string;
  /** Worker.access_code와 같은 규칙(모르면 null → 뒤 2자리로 대신). */
  access_code?: string | null;
  access_code_hint: string;
  status: string;
}

// 로그인 요청(/api/auth/*)의 401은 "로그인이 풀렸다"가 아니라 "아이디·번호가 틀렸다"다. 저장된 로그인을
// 지우지 않고 서버 문장을 그대로 보여 준다(0차 2번). 예전에는 '로그인이 필요합니다'가 떠서 무엇이 틀렸는지 몰랐다.
function isLoginPath(path: string): boolean {
  return path.startsWith("/api/auth/");
}

/** fetch를 부르고, 닿지 못하면 NetworkError로 감싼다(영어 "Failed to fetch"를 화면에 내지 않게). */
async function send(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e; // 호출한 쪽이 일부러 끊었다.
    throw new NetworkError(undefined, { cause: e });
  }
}

/** 2xx가 아닌 응답을 ApiError(또는 AuthError)로 바꾼다. */
async function toError(path: string, res: Response, fallback?: string): Promise<ApiError> {
  if (res.status === 401 && !isLoginPath(path)) {
    clearAuth();
    return new AuthError();
  }
  const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
  if (typeof body.detail === "string") return new ApiError(res.status, body.detail);
  // pydantic 검증 오류(422)는 detail이 배열이다 — 사람이 읽을 문장이 아니므로 일반 문구로 바꾼다.
  if (Array.isArray(body.detail)) return new ApiError(res.status, null, "입력값을 확인해 주세요.");
  return new ApiError(res.status, null, fallback ? `${fallback} (${res.status})` : undefined);
}

/**
 * 인증 토큰을 붙여 JSON API를 부른다. 실패하면 던지는 것:
 * NetworkError(닿지 못함) / AuthError(로그인 밖의 401, 저장된 로그인을 지움) / ApiError(그 밖, message = 서버 detail).
 * 근로자 화면 호출(worker/workerApi.ts)도 이 함수를 쓴다.
 */
export async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const auth = getAuth();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (auth) headers.Authorization = `Bearer ${auth.token}`;
  const res = await send(`${BASE}${path}`, { ...init, headers: { ...headers, ...(init?.headers ?? {}) } });
  if (!res.ok) throw await toError(path, res);
  return res.json() as Promise<T>;
}

export const auth = {
  async loginEmployer(login_id: string, password: string): Promise<AuthState> {
    const r = await req<{ token: string; role: Role; display_name: string }>(
      "/api/auth/login",
      { method: "POST", body: JSON.stringify({ login_id, password }) }
    );
    const state: AuthState = { token: r.token, role: r.role, displayName: r.display_name };
    setAuth(state);
    return state;
  },
  /** 접속 코드는 사업장 안에서만 unique라 사업장 코드가 함께 있어야 근로자를 찾을 수 있다. */
  async loginWorker(workplace_code: string, access_code: string): Promise<AuthState> {
    const r = await req<{ token: string; role: Role; display_name: string; workplace_name?: string | null }>(
      "/api/auth/worker-login",
      { method: "POST", body: JSON.stringify({ workplace_code, access_code }) }
    );
    const state: AuthState = { token: r.token, role: r.role, displayName: r.display_name };
    setAuth(state);
    // 사업장 이름은 근로자 기기의 번호 넣기 화면 위 띠에 보인다(로그인 전에는 서버가 알려 주지 않는다).
    if (r.workplace_name) saveWorkplaceName(r.workplace_name);
    return state;
  },
  /**
   * 시연용 데모 계정(로그인 화면 미리 채우기). 데모 계정이 없는 서버(운영)는 404 → null.
   * req()를 쓰지 않는다: 로그인 전 화면에서 부르는 보조 조회라, 실패해도 저장된 로그인 상태를 지우거나
   * 오류를 띄우면 안 된다.
   */
  async demoCredentials(): Promise<DemoCredentials | null> {
    try {
      const res = await fetch(`${BASE}/api/auth/demo`);
      if (!res.ok) return null;
      return (await res.json()) as DemoCredentials;
    } catch {
      return null; // 백엔드가 아직 안 떴어도 로그인 화면은 그대로 쓸 수 있어야 한다.
    }
  },
};

/** 서버는 공개 기본값이 지금도 맞을 때만 값을 준다(바뀐 비밀번호·코드는 null). */
export interface DemoCredentials {
  employer: { login_id: string; password: string } | null;
  worker: { workplace_code: string; access_code: string } | null;
}

export interface TaskSummary {
  id: string;
  title: string;
  status: string;
  created_at: string;
}

export interface Worker {
  id: string;
  display_name: string;
  /**
   * 전체 접속 코드(사업주가 근로자에게 알려 주는 용도). 서버가 암호문으로 들고 있다가 이 사업주에게만 준다.
   * 예전에 만든 근로자는 서버도 모르는 상태라 null — 그 근로자가 한 번 로그인하거나 재발급하면 채워진다.
   */
  access_code?: string | null;
  /** 뒤 2자리(access_code가 null일 때 대신 보여 준다)와 길이(짧은 코드 경고용). */
  access_code_hint: string;
  access_code_length: number;
  /** 사업주 메모(근로자 특성). 기본으로는 AI에 보내지 않는다. */
  note?: string;
  /** 근로자 화면 설정(contract §4.3). 예전 서버는 이 필드가 없다. */
  a11y_prefs?: A11yPrefs;
  /** "AI 코칭에 메모 사용" — 사업주가 켜야 하고, AI 처리 동의도 있어야 실제로 보낸다. */
  ai_note_allowed?: boolean;
  /** AI 처리(국외 이전) 동의가 살아 있는지. 없으면 AI 코칭은 규칙 기반 제안만 나온다. */
  ai_consent?: boolean;
  /** 개인정보 수집·이용 동의가 살아 있는지(사업주가 동의서를 받았다고 기록했는지). */
  personal_info_consent?: boolean;
  /** 이름이 일반 낱말("하나"·"보람" 등)과 같아 AI에 보낼 때 호칭이 붙은 경우("하나 씨")만 가릴 수 있다. */
  name_ambiguous?: boolean;
}

/** 근로자 삭제 응답. 직무 문장 속 이름은 사업주 데이터라 지우지 않으므로, 남은 직무를 알려 준다. */
export interface DeleteWorkerResult {
  ok: boolean;
  /** false면 다른 화면이 DB를 읽는 중이라 디스크(WAL) 정리를 끝내지 못했다. 다음 정리 작업이 다시 한다. */
  wal_checkpointed?: boolean;
  name_mentions?: { task_id: string; title: string }[];
}

export type ConsentType = "personal_info" | "ai_processing";
export type ConsentSubject = "self" | "guardian";

/** 보호자·당사자에게서 받은 동의 기록. 철회해도 지우지 않고 revoked_at이 채워진다. */
export interface Consent {
  id: string;
  consent_type: ConsentType;
  subject: ConsentSubject;
  policy_version: string;
  granted_at: string;
  revoked_at: string | null;
  recorded_by: string;
}

/** 근로자 추가·코드 재발급 응답. 평문 코드를 볼 수 있는 유일한 순간이다. */
export interface WorkerWithCode extends Worker {
  access_code: string;
}

export interface Workplace {
  workplace_code: string;
  org_name: string;
}

export interface TaskContext {
  business_type?: string;
  work_environment?: string;
  worker_note?: string;
  /** 맞춤 대상 근로자. 메모는 이 근로자가 허용·동의한 경우에만 AI로 간다. */
  worker_id?: string;
}

export interface CoachingSuggestion {
  order: number;
  issue: string;
  suggestion: string;
  action: "rephrase" | "photo" | "split" | "ok" | string;
}

export interface Coaching {
  summary: string;
  suggestions: CoachingSuggestion[];
  /** AI 처리 동의가 없는 근로자 기록이 있어 규칙 기반 제안만 만든 경우 true. */
  ai_excluded?: boolean;
}

export const api = {
  listTasks: () => req<TaskSummary[]>("/api/tasks"),
  createTask: (raw_input: string, context: TaskContext = {}) =>
    req<Task>("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ raw_input, ...context }),
    }),
  coaching: (taskId: string, workerId?: string) =>
    req<Coaching>(`/api/dashboard/tasks/${taskId}/coaching${workerId ? `?worker_id=${workerId}` : ""}`),
  getTask: (id: string) => req<Task>(`/api/tasks/${id}`),
  deleteTask: (id: string) => req<{ ok: boolean }>(`/api/tasks/${id}`, { method: "DELETE" }),
  updateStep: (
    taskId: string,
    stepId: string,
    patch: Partial<Pick<Step, "sentence" | "symbol_url" | "symbol_source">>,
  ) => req<Step>(`/api/tasks/${taskId}/steps/${stepId}`, { method: "PATCH", body: JSON.stringify(patch) }),
  /** 자동 채택하지 못한 단계에 붙일 AAC 후보를 가져온다(검토 화면 후보 선택용). */
  stepSymbolCandidates: (taskId: string, stepId: string) =>
    req<StepSymbolCandidates>(`/api/tasks/${taskId}/steps/${stepId}/symbol-candidates`),
  deleteStep: (taskId: string, stepId: string) =>
    req<Task>(`/api/tasks/${taskId}/steps/${stepId}`, { method: "DELETE" }),
  addStep: (taskId: string, sentence: string) =>
    req<Task>(`/api/tasks/${taskId}/steps`, { method: "POST", body: JSON.stringify({ sentence }) }),
  reorderSteps: (taskId: string, stepIds: string[]) =>
    req<Task>(`/api/tasks/${taskId}/steps/reorder`, {
      method: "PATCH",
      body: JSON.stringify({ step_ids: stepIds }),
    }),
  publish: (id: string) => req<Task>(`/api/tasks/${id}/publish`, { method: "POST" }),
  uploadStepPhoto: async (taskId: string, stepId: string, file: File): Promise<Step> => {
    const a = getAuth();
    const form = new FormData();
    form.append("file", file);
    const path = `/api/tasks/${taskId}/steps/${stepId}/photo`;
    const res = await send(`${BASE}${path}`, {
      method: "POST",
      // multipart 경계는 브라우저가 설정하므로 Content-Type을 직접 넣지 않는다.
      headers: a ? { Authorization: `Bearer ${a.token}` } : {},
      body: form,
    });
    if (!res.ok) throw await toError(path, res, "사진 업로드 실패");
    return res.json() as Promise<Step>;
  },
  removeStepPhoto: (taskId: string, stepId: string) =>
    req<Step>(`/api/tasks/${taskId}/steps/${stepId}/photo`, { method: "DELETE" }),
  /** 근로자 한 명 이상에게 게시된 직무를 배정한다(빈 배열이면 사업주의 유일한 근로자에게 자동 배정). */
  assign: (id: string, workerIds: string[] = []) =>
    req<{ id: string; task_id: string; worker_id: string; status: string }[]>(
      `/api/tasks/${id}/assignments`,
      { method: "POST", body: JSON.stringify({ worker_ids: workerIds }) },
    ),
  listWorkers: () => req<Worker[]>("/api/workers"),
  workerTasks: (workerId: string, date?: string) =>
    req<TaskSummary[]>(`/api/workers/${workerId}/tasks${date ? `?date=${date}` : ""}`),
  workerActiveDates: (workerId: string) => req<string[]>(`/api/workers/${workerId}/active-dates`),
  /** access_code를 비우면 서버가 사업장 안에서 겹치지 않는 4자리 무작위 코드를 만든다. */
  createWorker: (display_name: string, access_code?: string) =>
    req<WorkerWithCode>("/api/workers", {
      method: "POST",
      body: JSON.stringify(access_code ? { display_name, access_code } : { display_name }),
    }),
  /** 접속 코드를 새 4자리 무작위 코드로 바꾼다(유출 시·예전 긴 코드 교체). */
  reissueAccessCode: (id: string) =>
    req<WorkerWithCode>(`/api/workers/${id}/access-code`, { method: "POST" }),
  /** 내 사업장 코드(근로자 기기의 로그인 화면에 한 번 입력해 둔다). */
  workplace: () => req<Workplace>("/api/workplace"),
  deleteWorker: (id: string) => req<DeleteWorkerResult>(`/api/workers/${id}`, { method: "DELETE" }),
  /** 이름·메모·"AI 코칭에 메모 사용"·화면 설정을 바꾼다. 보낸 필드만 바뀐다(a11y_prefs도 보낸 키만 병합). */
  updateWorker: (
    id: string,
    patch: { display_name?: string; note?: string; ai_note_allowed?: boolean; a11y_prefs?: Partial<A11yPrefs> },
  ) =>
    req<Worker>(`/api/workers/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  listConsents: (id: string) => req<Consent[]>(`/api/workers/${id}/consents`),
  grantConsent: (id: string, consent_type: ConsentType, subject: ConsentSubject) =>
    req<Consent>(`/api/workers/${id}/consents`, {
      method: "POST",
      body: JSON.stringify({ consent_type, subject }),
    }),
  revokeConsent: (workerId: string, consentId: string) =>
    req<Consent>(`/api/workers/${workerId}/consents/${consentId}/revoke`, { method: "POST" }),
  /** 근로자 한 명의 데이터(프로필·동의·배정·수행 로그) JSON. 열람 요구에 응할 때 쓴다. */
  exportWorker: (id: string) => req<Record<string, unknown>>(`/api/workers/${id}/export`),
  today: () => req<TodayCard[]>("/api/worker/me/today"),
  /** 근로자 본인이 받았던 일 전체(완료 포함, 최신순) — '오늘 할 일'은 완료되면 빠지므로 복습용. */
  history: () => req<HistoryCard[]>("/api/worker/me/history"),
  logStep: (body: {
    assignment_id: string;
    step_id: string;
    duration_sec: number;
    replay_count: number;
    stuck: boolean;
  }) => req<{ ok: boolean }>("/api/performance-logs", { method: "POST", body: JSON.stringify(body) }),
  /** 사업주: 근로자 도움 요청 목록(contract §7.4). 기본 active = 열림 + 확인함. */
  employerHelp: (state: "active" | "open" | "today" = "active") =>
    req<EmployerHelp[]>(`/api/employer/help?state=${state}`),
  /** 사업주 [확인했어요]: 근로자 화면에 '선생님이 확인했어요'가 뜬다. */
  ackHelp: (id: string) => req<HelpOut>(`/api/employer/help/${id}/acknowledge`, { method: "POST" }),
  /** 사업주 [도와줬어요]: 요청을 닫는다. */
  resolveHelp: (id: string) => req<HelpOut>(`/api/employer/help/${id}/resolve`, { method: "POST" }),
  dashboard: (id: string, workerId?: string) =>
    req<Dashboard>(`/api/dashboard/tasks/${id}${workerId ? `?worker_id=${workerId}` : ""}`),
  dashboardWorkers: (id: string) => req<DashboardWorker[]>(`/api/dashboard/tasks/${id}/workers`),
  searchAac: (query: string, job?: string, limit = 5) =>
  req<AacSearchResult>("/api/aac/search", {
    method: "POST",
    body: JSON.stringify({
      query,
      job: job || null,
      limit,
    }),
  }),
};
