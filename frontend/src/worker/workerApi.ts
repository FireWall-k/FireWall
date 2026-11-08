// 근로자 화면 전용 API 호출(contract §4.2·§5·§6·§7). 인증·오류 처리는 api.ts의 req를 그대로 쓴다
// (닿지 못함 → NetworkError, 로그인 밖 401 → AuthError, 그 밖 → ApiError). 화면은 오류를 copy.ts의
// toWorkerMessage로만 해석한다 — 서버 문장을 근로자 화면에 그대로 내지 않는다.
import { DEFAULT_A11Y_PREFS, req, type A11yPrefs, type HelpOut, type HistoryCard, type Step } from "../api";

/** 열린 도움 요청 요약(today 카드에 붙는다, 새로고침 뒤 도움 띠 복원용). */
export interface ActiveHelp {
  id: string;
  state: "open" | "acknowledged";
  step_id: string | null;
  created_at: string;
}

/** 오늘 할 일 카드(contract §5, include_done=true). 예전 서버가 빠뜨린 필드는 normalizeJob이 채운다. */
export interface TodayJob {
  assignment_id: string;
  task_id: string;
  task_title: string;
  steps: Step[];
  status: "new" | "in_progress" | "done";
  done_step_ids: string[];
  resume_step_index: number;
  is_next: boolean;
  assigned_at: string | null;
  completed_at: string | null;
  active_help: ActiveHelp | null;
}

export interface WorkerMe {
  id: string;
  display_name: string;
  workplace_name: string;
  teacher_title: string;
  a11y_prefs: A11yPrefs;
}

/** 단계 완료 기록(contract §6.1). 도움 요청은 여기로 보내지 않는다(§7). */
export interface LogBody {
  assignment_id: string;
  step_id: string;
  duration_sec: number;
  replay_count: number;
  stuck: boolean;
  completed: boolean;
  client_event_id: string;
  client_completed_at: string;
}

export interface LogResult {
  ok: boolean;
  assignment_status: string;
  duplicate: boolean;
  applied: boolean;
}

/** 서버 설정을 8개 키 모두 채운 모양으로(모르는 값은 기본값). */
export function normalizePrefs(p?: Partial<A11yPrefs> | null): A11yPrefs {
  const v = { ...DEFAULT_A11Y_PREFS, ...(p ?? {}) };
  return {
    font_size: v.font_size === "large" ? "large" : "normal",
    autoplay_sound: v.autoplay_sound !== false,
    tts_rate: v.tts_rate === 0.8 || v.tts_rate === 1.0 ? v.tts_rate : 0.9,
    sfx: v.sfx !== false,
    vibration: v.vibration === true,
    praise: v.praise === "quiet" ? "quiet" : "normal",
    hand: v.hand === "left" ? "left" : "right",
    contrast: v.contrast === "high" ? "high" : "normal",
  };
}

type JobInput = Partial<TodayJob> & Pick<TodayJob, "assignment_id" | "task_id" | "task_title" | "steps">;

/** 예전 서버(필드 없음)와도 화면이 돌게 기본값을 채운다. */
export function normalizeJob(c: JobInput): TodayJob {
  const done = c.done_step_ids ?? [];
  return {
    assignment_id: c.assignment_id,
    task_id: c.task_id,
    task_title: c.task_title,
    steps: c.steps ?? [],
    status: c.status ?? (done.length > 0 ? "in_progress" : "new"),
    done_step_ids: done,
    resume_step_index: c.resume_step_index ?? 0,
    is_next: c.is_next ?? false,
    assigned_at: c.assigned_at ?? null,
    completed_at: c.completed_at ?? null,
    active_help: c.active_help ?? null,
  };
}

/** 재전송 묶기 키(client_event_id·client_request_id). crypto.randomUUID가 없는 옛 브라우저는 대체 함수로. */
export function newId(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  } catch {
    /* 보안 맥락이 아니면(http) randomUUID가 없을 수 있다 */
  }
  const rnd = () => Math.floor(Math.random() * 0x10000).toString(16).padStart(4, "0");
  return `${Date.now().toString(16)}-${rnd()}-${rnd()}-${rnd()}-${rnd()}${rnd()}`;
}

export const workerApi = {
  me: async (): Promise<WorkerMe> => {
    const m = await req<WorkerMe>("/api/worker/me");
    return { ...m, teacher_title: m.teacher_title || "선생님", a11y_prefs: normalizePrefs(m.a11y_prefs) };
  },
  /** 오늘 끝낸 일까지(include_done=true) — 홈이 다 한 카드를 맨 아래에 보인다. */
  today: async (): Promise<TodayJob[]> => {
    const list = await req<JobInput[]>("/api/worker/me/today?include_done=true");
    return list.map(normalizeJob);
  },
  history: () => req<HistoryCard[]>("/api/worker/me/history"),
  logStep: (body: LogBody) =>
    req<LogResult>("/api/performance-logs", { method: "POST", body: JSON.stringify(body) }),
  /** signal로 끊을 수 있다(useHelp가 8초 넘게 답이 없으면 끊고 '아직 못 불렀어요'를 보인다). */
  createHelp: (body: { assignment_id: string; step_id: string | null; client_request_id: string }, signal?: AbortSignal) =>
    req<HelpOut>("/api/worker/help", { method: "POST", body: JSON.stringify(body), signal }),
  getHelp: (id: string) => req<HelpOut>(`/api/worker/help/${encodeURIComponent(id)}`),
  cancelHelp: (id: string) =>
    req<HelpOut>(`/api/worker/help/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
};

export type WorkerApi = typeof workerApi;
