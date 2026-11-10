// 백엔드 계약을 그대로 비추는 타입 + 호출 함수.
// 이 파일이 프론트엔드 <-> 백엔드 경계의 전부다. (인증 토큰 부착 포함)

import { ApiError, AuthError, NetworkError } from "./apiErrors";
import { getDeviceToken, saveDeviceToken, saveWorkplaceName } from "./workerCodes";

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
async function toError(path: string, res: Response, fallback?: string, sentToken?: string | null): Promise<ApiError> {
  if (res.status === 401 && !isLoginPath(path)) {
    // 저장된 로그인은 이 요청이 실어 보낸 토큰일 때만 지운다(3차 검증). 앞사람(근로자 A)의 대기열이 A 토큰으로
    // 보낸 기록이 401이 됐다고, 그사이 같은 기기로 들어온 근로자 B의 로그인을 지우면 안 된다.
    if (sentToken === undefined || getAuth()?.token === sentToken) clearAuth();
    return new AuthError();
  }
  const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
  if (typeof body.detail === "string" && body.detail.trim()) return new ApiError(res.status, body.detail);
  // pydantic 검증 오류(422)는 detail이 배열이다 — 사람이 읽을 문장이 아니므로 errorDetail의 일반 문구로 바꾼다.
  if (fallback && res.status !== 422) return new ApiError(res.status, null, `${fallback} (${res.status})`);
  return new ApiError(res.status, null, errorDetail(body, res.status));
}

export interface ReqOptions {
  /** 저장된 로그인 대신 이 토큰을 붙인다. */
  token?: string | null;
}

/**
 * 인증 토큰을 붙여 JSON API를 부른다. 실패하면 던지는 것:
 * NetworkError(닿지 못함) / AuthError(로그인 밖의 401, 저장된 로그인을 지움) / ApiError(그 밖, message = 서버 detail).
 * 근로자 화면 호출(worker/workerApi.ts)도 이 함수를 쓴다.
 */
export async function req<T>(path: string, init?: RequestInit, opts?: ReqOptions): Promise<T> {
  // opts.token: 이 토큰으로 보낸다(저장된 로그인이 그사이 바뀌어도). 근로자 세션·대기열은 세션을 연 토큰을 쓴다 —
  // 같은 기기에서 다른 근로자가 들어온 뒤 앞사람 기록이 뒷사람 토큰으로 가 404로 버려지던 문제(3차 검증).
  const token = opts?.token !== undefined ? opts.token : (getAuth()?.token ?? null);
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await send(`${BASE}${path}`, { ...init, headers: { ...headers, ...(init?.headers ?? {}) } });
  if (!res.ok) throw await toError(path, res, undefined, token);
  return res.json() as Promise<T>;
}

/** 오류 응답의 detail을 화면에 띄울 문장으로. 문자열이 아니면(검증 오류 목록 등) '[object Object]'가 뜨지 않게
 * 일반 문장을 쓴다(입력 화면 나누기 2차 검증). */
export function errorDetail(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (status === 422) return "입력한 내용을 다시 확인해 주세요.";
  return `요청 실패 (${status})`;
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
    const device_token = getDeviceToken();
    const r = await req<{
      token: string;
      role: Role;
      display_name: string;
      workplace_name?: string | null;
      device_token?: string | null;
    }>(
      "/api/auth/worker-login",
      { method: "POST", body: JSON.stringify(device_token ? { workplace_code, access_code, device_token } : { workplace_code, access_code }) }
    );
    if (r.device_token) saveDeviceToken(r.device_token);
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
  /** 2a-1: 보관함에 있는지(옛 서버는 보내지 않으니 없으면 false로 본다). */
  archived?: boolean;
}

export interface Worker {
  id: string;
  display_name: string;
  /**
   * (2d) 목록·수정 응답에는 전체 코드가 없다(눈 단추 → POST …/access-code/reveal). 만들기·새 번호 응답에만 있다.
   * 옛 새 직무 화면(2b-1에서 지움)이 아직 읽어서 선택 칸으로 남긴다.
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

/** 근로자 추가·코드 재발급 응답. 평문 코드를 볼 수 있는 유일한 순간이다. */
export interface WorkerWithCode extends Worker {
  access_code: string;
}

export interface TaskContext {
  business_type?: string;
  work_environment?: string;
  worker_note?: string;
  /** 맞춤 대상 근로자. 메모는 이 근로자가 허용·동의한 경우에만 AI로 간다. */
  worker_id?: string;
}

/** 입력 화면 나누기 미리보기의 한 줄(POST /api/tasks/split-preview). 한 줄 = 한 동작 = 그림 1장. */
export interface SplitPreviewStep {
  order: number;
  sentence: string;
  action_type: string;
  symbol_query: string[];
  /** 같은 원래 절에서 나온 줄끼리 같은 번호. 원문 그대로인 줄은 null. */
  split_group: number | null;
  /** 나눈 곳이 애매해 사업주가 봐야 하는 줄(노란 표시). */
  split_check: boolean;
  /** 이 줄들이 나온 원래 절 — [합치기]로 되돌릴 문장. */
  source_text: string | null;
}

export interface SplitPreview {
  task_title: string;
  job: string;
  steps: SplitPreviewStep[];
}

/** 사업주가 입력 화면에서 확인한 단계. symbol_query는 문장을 고치지 않은 줄만 보낸다. */
export interface ConfirmedStep {
  sentence: string;
  action_type?: string;
  symbol_query?: string[] | null;
}

export interface CreateTaskOptions extends TaskContext {
  steps?: ConfirmedStep[];
  title?: string;
  job?: string;
}

/** 편집기 문장 저장 결과. 동작이 둘이라 나눴으면 split_step_ids에 새 단계 id가 온다(되돌리기용). */
export interface StepRewriteResult {
  task: Task;
  split_step_ids: string[];
  sentence: string;
}

export const api = {
  createTask: (raw_input: string, context: CreateTaskOptions = {}) =>
    req<Task>("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ raw_input, ...context }),
    }),
  /** 직무를 만들지 않고 단계로 나눈 결과만 받는다(입력 화면에서 바로 확인·수정). */
  splitPreview: (raw_input: string, context: TaskContext = {}) =>
    req<SplitPreview>("/api/tasks/split-preview", {
      method: "POST",
      body: JSON.stringify({ raw_input, ...context }),
    }),
  /** 편집기에서 문장을 고쳐 저장. 동작이 둘이면 서버가 두 단계로 나눠 돌려준다. */
  rewriteStep: (taskId: string, stepId: string, sentence: string) =>
    req<StepRewriteResult>(`/api/tasks/${taskId}/steps/${stepId}/rewrite`, {
      method: "POST",
      body: JSON.stringify({ sentence }),
    }),
  /** 이어진 단계들을 한 단계로 합친다(저장하며 나눈 것 되돌리기). actionType은 나누기 전 단계의 동작 종류. */
  mergeSteps: (taskId: string, stepIds: string[], sentence: string, actionType?: string) =>
    req<Task>(`/api/tasks/${taskId}/steps/merge`, {
      method: "POST",
      body: JSON.stringify({ step_ids: stepIds, sentence, action_type: actionType }),
    }),
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
  /** 단계 추가. 새 문장에 동작이 둘이면 서버가 두 단계로 나눠 넣고 split_step_ids를 준다(되돌리기용). */
  addStep: (taskId: string, sentence: string) =>
    req<Task & { split_step_ids?: string[]; sentence?: string }>(
      `/api/tasks/${taskId}/steps`, { method: "POST", body: JSON.stringify({ sentence }) }),
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
  /** access_code를 비우면 서버가 사업장 안에서 겹치지 않는 4자리 무작위 코드를 만든다. */
  createWorker: (display_name: string, access_code?: string) =>
    req<WorkerWithCode>("/api/workers", {
      method: "POST",
      body: JSON.stringify(access_code ? { display_name, access_code } : { display_name }),
    }),
  /** 접속 코드를 새 4자리 무작위 코드로 바꾼다(유출 시·예전 긴 코드 교체). */
  reissueAccessCode: (id: string) =>
    req<WorkerWithCode>(`/api/workers/${id}/access-code`, { method: "POST" }),
  /** (옛 새 직무 화면 전용, 2b-1에서 지움) 근로자 지우기. 옛 DELETE는 없어졌고 이름을 다시 적어야 한다(contract §6.2).
   *  새 화면은 manager/api/workers.ts의 deleteWorker를 쓴다. */
  deleteWorker: (id: string, confirmName = "") =>
    req<DeleteWorkerResult>(`/api/workers/${id}/delete`, { method: "POST", body: JSON.stringify({ confirm_name: confirmName }) }),
  /** 이름·메모·"AI 코칭에 메모 사용"·화면 설정을 바꾼다. 보낸 필드만 바뀐다(a11y_prefs도 보낸 키만 병합). */
  updateWorker: (
    id: string,
    patch: { display_name?: string; note?: string; ai_note_allowed?: boolean; a11y_prefs?: Partial<A11yPrefs> },
  ) =>
    req<Worker>(`/api/workers/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
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
