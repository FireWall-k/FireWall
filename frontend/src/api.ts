// 백엔드 계약을 그대로 비추는 타입 + 호출 함수.
// 이 파일이 프론트엔드 <-> 백엔드 경계의 전부다. (인증 토큰 부착 포함)

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

export interface StepStat {
  order: number;
  sentence: string;
  completed: boolean;
  duration_sec: number;
  replay_count: number;
  stuck: boolean;
}

export interface ArasaacMatch {
  language: string;
  term: string;
  pictogram_id: string;
  image_url: string;
}

export interface ArasaacSearchResult {
  term: string;
  matches: ArasaacMatch[];
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

export class AuthError extends Error {}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const auth = getAuth();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (auth) headers.Authorization = `Bearer ${auth.token}`;
  const res = await fetch(`${BASE}${path}`, { ...init, headers: { ...headers, ...(init?.headers ?? {}) } });
  if (res.status === 401) {
    clearAuth();
    throw new AuthError("로그인이 필요합니다. 다시 로그인해 주세요.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? `요청 실패 (${res.status})`);
  }
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
  async loginWorker(access_code: string): Promise<AuthState> {
    const r = await req<{ token: string; role: Role; display_name: string }>(
      "/api/auth/worker-login",
      { method: "POST", body: JSON.stringify({ access_code }) }
    );
    const state: AuthState = { token: r.token, role: r.role, displayName: r.display_name };
    setAuth(state);
    return state;
  },
};

export interface TaskSummary {
  id: string;
  title: string;
  status: string;
}

export interface TaskContext {
  business_type?: string;
  work_environment?: string;
  worker_note?: string;
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
}

export const api = {
  listTasks: () => req<TaskSummary[]>("/api/tasks"),
  createTask: (raw_input: string, context: TaskContext = {}) =>
    req<Task>("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ raw_input, ...context }),
    }),
  coaching: (taskId: string) => req<Coaching>(`/api/dashboard/tasks/${taskId}/coaching`),
  getTask: (id: string) => req<Task>(`/api/tasks/${id}`),
  updateStep: (taskId: string, stepId: string, patch: Partial<Pick<Step, "sentence" | "symbol_url">>) =>
    req<Step>(`/api/tasks/${taskId}/steps/${stepId}`, { method: "PATCH", body: JSON.stringify(patch) }),
  publish: (id: string) => req<Task>(`/api/tasks/${id}/publish`, { method: "POST" }),
  uploadStepPhoto: async (taskId: string, stepId: string, file: File): Promise<Step> => {
    const a = getAuth();
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE}/api/tasks/${taskId}/steps/${stepId}/photo`, {
      method: "POST",
      // multipart 경계는 브라우저가 설정하므로 Content-Type을 직접 넣지 않는다.
      headers: a ? { Authorization: `Bearer ${a.token}` } : {},
      body: form,
    });
    if (res.status === 401) {
      clearAuth();
      throw new AuthError("로그인이 필요합니다. 다시 로그인해 주세요.");
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error((body as { detail?: string }).detail ?? `사진 업로드 실패 (${res.status})`);
    }
    return res.json() as Promise<Step>;
  },
  removeStepPhoto: (taskId: string, stepId: string) =>
    req<Step>(`/api/tasks/${taskId}/steps/${stepId}/photo`, { method: "DELETE" }),
  assign: (id: string, worker_id?: string) =>
    req<{ id: string }>(`/api/tasks/${id}/assignments`, {
      method: "POST",
      body: JSON.stringify({ worker_id: worker_id ?? null }),
    }),
  today: () => req<TodayCard[]>("/api/worker/me/today"),
  logStep: (body: {
    assignment_id: string;
    step_id: string;
    duration_sec: number;
    replay_count: number;
    stuck: boolean;
  }) => req<{ ok: boolean }>("/api/performance-logs", { method: "POST", body: JSON.stringify(body) }),
  dashboard: (id: string) => req<Dashboard>(`/api/dashboard/tasks/${id}`),
  searchArasaac: (term: string, langs: string[] = ["en", "es"], limit = 3) =>
    req<ArasaacSearchResult>("/api/arasaac/search", {
      method: "POST",
      body: JSON.stringify({ term, langs, limit }),
    }),
};
