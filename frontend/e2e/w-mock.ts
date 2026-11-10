import type { Page, Route } from "@playwright/test";

// 새 근로자 화면(/w) e2e용 가짜 백엔드. 실제 백엔드·DB 없이 page.route로 API를 흉내 낸다.
// 상태(MockState)를 테스트가 바꿔 '인터넷 끊김'·'선생님 확인' 같은 상황을 만든다.
// 목 데이터 글자는 근로자 화면 금지어 검사(FORBIDDEN_PATTERNS)에 걸리지 않게 한국어 '~해요' 체만 쓴다.

// 했던 일 목록의 날짜는 '오늘' 묶음으로 보여야 한다 — 날짜를 박아 두면 다음 날부터 '어제'가 되어 시험이 깨진다.
function localToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET,POST,PATCH,DELETE,OPTIONS",
};

export const LONG_SENTENCE = "포장된 상자를 카트에 놓아요. 큰 상자는 아래쪽에 놓고 작은 상자는 위쪽에 놓아요";

function step(id: string, order: number, sentence: string) {
  return {
    id, order, sentence, action_type: "other",
    symbol_url: `http://e2e-api.invalid/media/symbols/${id}.png`,
    symbol_source: "LOCAL_AAC", needs_fallback: false, tts_audio_url: null, picture_state: "confirmed",
  };
}

export function makeJobs() {
  return [
    {
      assignment_id: "asg-1", task_id: "t1", task_title: "택배 상자 포장",
      steps: [step("s1", 1, "박스 바닥 덮개를 접어요"), step("s2", 2, "테이프를 붙여요"), step("s3", 3, LONG_SENTENCE)],
      status: "new", done_step_ids: [] as string[], resume_step_index: 0, is_next: true,
      assigned_at: "2026-11-09T00:00:00", completed_at: null, active_help: null,
    },
    {
      assignment_id: "asg-2", task_id: "t2", task_title: "매장 바닥 청소",
      steps: [step("c1", 1, "밀대로 바닥을 닦아요")],
      status: "new", done_step_ids: [] as string[], resume_step_index: 0, is_next: false,
      assigned_at: "2026-11-09T00:10:00", completed_at: null, active_help: null,
    },
  ];
}

export interface MockState {
  jobs: ReturnType<typeof makeJobs>;
  /** true면 모든 API 요청이 네트워크 오류로 끊긴다(그림 파일은 그대로 온다). */
  offline: boolean;
  /** 도움 요청만 끊는다. */
  helpOffline: boolean;
  /** GET /api/worker/help/{id}가 돌려줄 상태. */
  helpState: "open" | "acknowledged" | "resolved" | "cancelled";
  logs: Record<string, unknown>[];
  helpCreates: number;
  loginAttempts: string[];
  prefs: Record<string, unknown>;
  /** 했던 일 목록의 날짜("YYYY-MM-DD"). 없으면 실행하는 날(현지). 브라우저 시계를 고정하는 시험은 같은 날로 맞춘다. */
  historyDate?: string;
  /** (2c) 받은 presence 본문과 측정 이벤트. */
  presence?: Record<string, unknown>[];
  events?: Record<string, unknown>[];
}

export function newState(): MockState {
  return {
    jobs: makeJobs(), offline: false, helpOffline: false, helpState: "open", logs: [], helpCreates: 0,
    loginAttempts: [],
    prefs: {
      font_size: "normal", autoplay_sound: true, tts_rate: 0.9, sfx: true, vibration: false,
      praise: "normal", hand: "right", contrast: "normal",
    },
  };
}

function helpOut(state: MockState["helpState"]) {
  return {
    id: "h1", assignment_id: "asg-1", step_id: "s1", step_order: 1, state, resolution: state === "resolved" ? "employer" : null,
    created_at: "2026-11-09T01:00:00", acknowledged_at: null, cancelled_at: null, resolved_at: null,
  };
}

export async function mockWorkerBackend(page: Page, state: MockState) {
  await page.route("https://cdn.jsdelivr.net/**", (route) => route.abort());
  await page.route("http://e2e-api.invalid/**", async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, headers: { ...CORS, "content-type": "application/json" }, body: JSON.stringify(body) });
    if (url.pathname.startsWith("/media/")) {
      return route.fulfill({ status: 200, headers: { ...CORS, "content-type": "image/png" }, body: PNG_1X1 });
    }
    if (state.offline) return route.abort("internetdisconnected");
    const p = url.pathname;
    if (p === "/api/auth/worker-login") {
      const body = JSON.parse(req.postData() || "{}");
      state.loginAttempts.push(body.access_code);
      if (body.access_code === "1234") {
        return json({ token: "e2e-worker-token", role: "worker", display_name: "김민수", workplace_name: "행복카페" });
      }
      return json({ detail: "사업장 코드 또는 접속 코드가 올바르지 않습니다." }, 401);
    }
    if (p === "/api/worker/me") {
      return json({ id: "w1", display_name: "김민수", workplace_name: "행복카페", teacher_title: "선생님", a11y_prefs: state.prefs });
    }
    if (p === "/api/worker/me/today") return json(state.jobs);
    if (p === "/api/worker/me/history") {
      return json(state.jobs.map((j) => ({
        assignment_id: j.assignment_id, task_id: j.task_id, task_title: j.task_title,
        assigned_date: state.historyDate ?? localToday(), status: j.status === "done" ? "done" : "assigned",
        steps: j.steps.map((s) => ({ ...s, completed: j.done_step_ids.includes(s.id) })),
      })));
    }
    if (p === "/api/performance-logs" && req.method() === "POST") {
      const body = JSON.parse(req.postData() || "{}");
      state.logs.push(body);
      const job = state.jobs.find((j) => j.assignment_id === body.assignment_id);
      if (job && !job.done_step_ids.includes(body.step_id)) job.done_step_ids.push(body.step_id);
      return json({ ok: true, assignment_status: "assigned", duplicate: false, applied: true }, 201);
    }
    if (p === "/api/worker/help" && req.method() === "POST") {
      if (state.helpOffline) return route.abort("internetdisconnected");
      state.helpCreates += 1;
      return json(helpOut("open"), 201);
    }
    if (p === "/api/worker/help/h1") return json(helpOut(state.helpState));
    // (2c) 지금 단계 신호와 측정 이벤트(204). 화면에는 아무것도 보이지 않는다.
    if (p === "/api/worker/presence" && req.method() === "POST") {
      (state.presence ??= []).push(JSON.parse(req.postData() || "{}"));
      return route.fulfill({ status: 204, headers: CORS });
    }
    if (p === "/api/events" && req.method() === "POST") {
      (state.events ??= []).push(...(JSON.parse(req.postData() || "{}").events ?? []));
      return route.fulfill({ status: 204, headers: CORS });
    }
    if (p === "/api/worker/help/h1/cancel") return json(helpOut("cancelled"));
    // 목킹하지 않은 API를 화면이 부르기 시작하면 조용히 넘어가지 않고 드러나게 한다.
    return route.fulfill({ status: 599, headers: CORS, body: `unmocked ${req.method()} ${p}` });
  });
}

/** 근로자로 로그인된 기기(사업장 코드 저장됨)로 시작한다. 키는 src/api.ts·workerCodes.ts와 같다. */
export async function loginAsWorker(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("jobcard_token", "e2e-worker-token");
    localStorage.setItem("jobcard_role", "worker");
    localStorage.setItem("jobcard_name", "김민수");
    localStorage.setItem("jobcard_workplace_code", "DEMO01");
    localStorage.setItem("jobcard_workplace_name", "행복카페");
  });
}

/** 사업장 코드만 저장된(로그인 전) 기기. */
export async function pairedDevice(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("jobcard_workplace_code", "DEMO01");
    localStorage.setItem("jobcard_workplace_name", "행복카페");
  });
}
