import type { Page, Route } from "@playwright/test";

// 사업주 화면(/m) e2e용 가짜 백엔드(page.route). 실제 백엔드·DB·GPT 없이 contract §2.1 모양을 흉내 낸다.
// GET /api/employer/tasks(backend/task_list.py)와 같은 모양을 준다. 실제 서버 흐름은 e2e-real/task-list.spec.ts가 본다.
// 목에 없는 요청은 599로 돌려 목 누락이 실패로 드러나게 한다(설정의 e2e-api.invalid와 같은 뜻).

export const API = "http://e2e-api.invalid";
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET,POST,PATCH,DELETE,OPTIONS",
};
const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

type State = "draft" | "published" | "archived";
export interface MockTask {
  id: string;
  title: string;
  state: State;
  needs_check_count: number;
  has_unsent_changes: boolean;
  step_count: number;
  cover_url: string | null;
  recipients: { worker_id: string; initials: string }[];
  recipients_more: number;
  updated_at: string;
  current_version_no: number | null;
}

const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString().replace("Z", "");

export function makeTasks(): MockTask[] {
  return [
    {
      id: "t1", title: "컵 씻기", state: "draft", needs_check_count: 2, has_unsent_changes: false, step_count: 5,
      cover_url: `${API}/media/c1.png`, recipients: [], recipients_more: 0, updated_at: ago(3), current_version_no: null,
    },
    {
      id: "t2", title: "앞치마 입기", state: "draft", needs_check_count: 0, has_unsent_changes: false, step_count: 3,
      cover_url: null, recipients: [], recipients_more: 0, updated_at: ago(90), current_version_no: null,
    },
    {
      id: "t3", title: "택배 상자 포장하고 운송장 붙이기", state: "published", needs_check_count: 1, has_unsent_changes: true,
      step_count: 7, cover_url: `${API}/media/c3.png`,
      recipients: [{ worker_id: "w1", initials: "김" }, { worker_id: "w2", initials: "이" }, { worker_id: "w3", initials: "박" }],
      recipients_more: 2, updated_at: ago(60 * 26), current_version_no: 2,
    },
    {
      id: "t4", title: "매장 바닥 청소", state: "published", needs_check_count: 0, has_unsent_changes: false, step_count: 4,
      cover_url: `${API}/media/c4.png`, recipients: [{ worker_id: "w1", initials: "김" }], recipients_more: 0,
      updated_at: ago(60 * 24 * 9), current_version_no: 1,
    },
    {
      id: "t9", title: "옛 창고 정리", state: "archived", needs_check_count: 0, has_unsent_changes: false, step_count: 6,
      cover_url: null, recipients: [], recipients_more: 0, updated_at: ago(60 * 24 * 40), current_version_no: 1,
    },
  ];
}

export function makeHelp() {
  return {
    id: "h1", state: "open", created_at: ago(1), acknowledged_at: null,
    worker_id: "w1", worker_name: "김민지", assignment_id: "a1", task_id: "t3", task_title: "택배 상자 포장하고 운송장 붙이기",
    step_id: "s3", step_order: 3, step_sentence: "운송장을 붙여요", step_symbol_url: null,
    source_step_id: "src3", step_thumb_url: null,
  };
}

/** (2c) 오늘 현황 표의 근로자(GET /api/employer/live workers). */
export function makeLiveWorkers() {
  const cur = (done: number, order: number, sentence: string) => ({
    assignment_id: "a1", task_id: "t3", task_title: "택배 상자 포장하고 운송장 붙이기", version_no: 2, done, total: 7,
    step: { id: "s" + order, source_step_id: "src" + order, order, sentence, thumb_url: API + "/media/s" + order + ".png" },
  });
  const today = (id: string, title: string, status: string) => [{ assignment_id: id, task_title: title, status, is_next: status !== "done" }];
  return [
    { worker_id: "w1", display_name: "김민지", initials: "김", badge: "help", last_activity_at: ago(1), last_signal_at: ago(0),
      current: cur(2, 3, "운송장을 붙여요"), today: today("a1", "택배 상자 포장하고 운송장 붙이기", "in_progress") },
    { worker_id: "w2", display_name: "이수진", initials: "이", badge: "stuck_suspect", last_activity_at: ago(4), last_signal_at: ago(0),
      current: cur(4, 5, "상자를 테이프로 붙여요"), today: today("a2", "택배 상자 포장하고 운송장 붙이기", "in_progress") },
    { worker_id: "w3", display_name: "박하늘", initials: "박", badge: "offline", last_activity_at: ago(6), last_signal_at: ago(6),
      current: cur(1, 2, "상자를 펼쳐요"), today: today("a3", "택배 상자 포장하고 운송장 붙이기", "in_progress") },
    { worker_id: "w4", display_name: "최다온", initials: "최", badge: "done", last_activity_at: ago(30), last_signal_at: ago(30),
      current: null, today: today("a4", "매장 바닥 청소", "done") },
  ];
}

/** (2c) 고치면 좋은 단계 카드. */
export function makeCoaching() {
  return [
    { task_id: "t3", task_title: "택배 상자 포장하고 운송장 붙이기", source_step_id: "src5", step_id: "s5", sentence: "상자를 테이프로 붙여요",
      thumb_url: API + "/media/s5.png", signals: { replay_avg: 3.4, duration_avg_sec: 150, help_count: 2, runs: 5 }, suggestion: "photo", after: null },
    { task_id: "t4", task_title: "매장 바닥 청소", source_step_id: "src9", step_id: "s9", sentence: "대걸레를 물에 적시고 꼭 짜서 바닥을 닦아요",
      thumb_url: null, signals: { replay_avg: 1.2, duration_avg_sec: 200, help_count: 0, runs: 4 }, suggestion: "split", after: null },
  ];
}

export interface EmployerMock {
  tasks: MockTask[];
  help: (Omit<ReturnType<typeof makeHelp>, "state"> & { state: string })[];
  workers: ReturnType<typeof makeLiveWorkers>;
  coaching: ReturnType<typeof makeCoaching>;
  /** GET /api/employer/live를 부른 수. */
  liveCalls: number;
  /** true면 /api/employer/live가 닿지 않는다(연결 끊김). */
  liveDown: boolean;
  calls: string[];
  /** 이 경로를 부르면 500을 준다(오류 토스트 시험). */
  failPaths: Set<string>;
}

function summarize(tasks: MockTask[], filter: string, q: string) {
  const live = tasks.filter((t) => t.state !== "archived");
  let items: MockTask[];
  if (filter === "draft") items = live.filter((t) => t.state === "draft");
  else if (filter === "published") items = live.filter((t) => t.state === "published");
  else if (filter === "needs_check") items = live.filter((t) => t.needs_check_count > 0);
  else if (filter === "archived") items = tasks.filter((t) => t.state === "archived");
  else items = live;
  if (q) items = items.filter((t) => t.title.includes(q));
  const counts = {
    all: live.length,
    draft: live.filter((t) => t.state === "draft").length,
    needs_check: live.filter((t) => t.needs_check_count > 0).length,
    published: live.filter((t) => t.state === "published").length,
    archived: tasks.filter((t) => t.state === "archived").length,
  };
  return { items, counts };
}

export async function mockEmployer(
  page: Page,
  opts: { tasks?: MockTask[]; help?: boolean; workers?: boolean; coaching?: boolean } = {},
): Promise<EmployerMock> {
  const m: EmployerMock = {
    tasks: opts.tasks ?? makeTasks(),
    help: opts.help === false ? [] : [makeHelp()],
    workers: opts.workers === false ? [] : makeLiveWorkers(),
    coaching: opts.coaching === false ? [] : makeCoaching(),
    liveCalls: 0,
    liveDown: false,
    calls: [],
    failPaths: new Set(),
  };
  await page.route("https://cdn.jsdelivr.net/**", (route) => route.abort());
  await page.route(`${API}/**`, async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    const method = req.method();
    const path = url.pathname;
    if (method === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
    m.calls.push(`${method} ${path}${url.search}`);
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, headers: { ...CORS, "content-type": "application/json" }, body: JSON.stringify(body) });
    if (m.failPaths.has(path)) return json({ detail: "처리하지 못했어요. 잠시 뒤 다시 시도해 주세요." }, 500);
    if (path.startsWith("/media/")) {
      return route.fulfill({ status: 200, headers: { ...CORS, "content-type": "image/png" }, body: PNG_1X1 });
    }

    if (path === "/api/auth/demo") return json({ detail: "없음" }, 404);
    if (path === "/api/auth/login" && method === "POST") {
      return json({ token: "e2e-employer-token", role: "employer", display_name: "테스트사장" });
    }
    if (path === "/api/employer/help") return json(m.help);
    // (2c) 오늘 현황 하나로 띠·종·홈이 함께 쓴다.
    if (path === "/api/employer/live" && method === "GET") {
      m.liveCalls += 1;
      if (m.liveDown) return route.abort("internetdisconnected");
      const active = m.help.filter((h) => h.state === "open" || h.state === "acknowledged");
      const ws = m.workers;
      return json({
        server_now: ago(0),
        summary: {
          working: ws.filter((w) => ["help", "help_acked", "stuck_suspect", "offline", "in_progress"].includes(w.badge)).length,
          total_workers: ws.length,
          open_help: active.filter((h) => h.state === "open").length,
          stuck_steps: ws.filter((w) => w.badge === "stuck_suspect").length,
          needs_check_tasks: m.tasks.filter((t) => t.state !== "archived" && t.needs_check_count > 0).length,
        },
        workers: ws,
        help: active,
      });
    }
    const helpAct = path.match(/^\/api\/employer\/help\/([^/]+)\/(acknowledge|resolve)$/);
    if (helpAct && method === "POST") {
      const h = m.help.find((x) => x.id === decodeURIComponent(helpAct[1]));
      if (!h) return json({ detail: "도움 요청을 찾을 수 없어요." }, 404);
      h.state = helpAct[2] === "resolve" ? "resolved" : "acknowledged";
      return json({ id: h.id, state: h.state, step_id: h.step_id, created_at: h.created_at, acknowledged_at: null, resolved_at: null });
    }
    if (path === "/api/employer/coaching" && method === "GET") return json(m.coaching);
    const tl = path.match(/^\/api\/employer\/workers\/([^/]+)\/timeline$/);
    if (tl && method === "GET") {
      const w = m.workers.find((x) => x.worker_id === decodeURIComponent(tl[1]));
      const step = (order: number, sentence: string, done: boolean, sec: number | null, replay: number, prev: number, help: number) => ({
        step_id: "s" + order, source_step_id: "src" + order, order, sentence, thumb_url: null, completed: done,
        completed_at: done ? ago(40 - order * 5) : null, duration_sec: sec, replay_count: replay, prev_count: prev, help_count: help,
      });
      return json({
        worker_id: tl[1], display_name: w?.display_name ?? "김민지", date: "2026-11-10",
        assignments: [{
          assignment_id: "a1", task_id: "t3", task_title: "택배 상자 포장하고 운송장 붙이기", version_no: 2, status: "in_progress", assigned_at: ago(90),
          steps: [step(1, "상자를 꺼내요", true, 35, 0, 0, 0), step(2, "상자를 펼쳐요", true, 150, 2, 1, 0), step(3, "운송장을 붙여요", false, null, 1, 0, 1)],
        }],
        events: [
          { at: ago(35), kind: "step_done", assignment_id: "a1", step_order: 1 },
          { at: ago(30), kind: "step_done", assignment_id: "a1", step_order: 2 },
          { at: ago(1), kind: "help_open", assignment_id: "a1", step_order: 3 },
        ],
      });
    }
    if (path === "/api/employer/push-config") return json({ enabled: false, public_key: null });
    if (path === "/api/events" && method === "POST") return route.fulfill({ status: 204, headers: CORS });
    if (path === "/api/employer/tasks" && method === "GET") {
      return json(summarize(m.tasks, url.searchParams.get("filter") ?? "all", url.searchParams.get("q") ?? ""));
    }
    const act = path.match(/^\/api\/tasks\/([^/]+)\/(archive|unarchive|duplicate)$/);
    if (act && method === "POST") {
      const t = m.tasks.find((x) => x.id === decodeURIComponent(act[1]));
      if (!t) return json({ detail: "직무를 찾을 수 없어요." }, 404);
      if (act[2] === "archive") t.state = "archived";
      else if (act[2] === "unarchive") t.state = t.current_version_no ? "published" : "draft";
      else {
        const dup: MockTask = {
          ...t, id: `${t.id}-copy${m.tasks.length}`, title: `${t.title} (복사본)`, state: "draft", has_unsent_changes: false,
          recipients: [], recipients_more: 0, current_version_no: null, updated_at: ago(0),
        };
        m.tasks.unshift(dup);
        return json({ id: dup.id, title: dup.title, status: "draft", steps: [] });
      }
      return json(t);
    }
    const del = path.match(/^\/api\/tasks\/([^/]+)$/);
    if (del && method === "DELETE") {
      const t = m.tasks.find((x) => x.id === decodeURIComponent(del[1]));
      if (!t) return json({ detail: "직무를 찾을 수 없어요." }, 404);
      if (t.state !== "archived") return json({ detail: "보관함으로 옮긴 직무만 완전히 지울 수 있어요." }, 409);
      m.tasks = m.tasks.filter((x) => x !== t);
      return json({ ok: true });
    }
    // 옛 화면(대시보드·근로자·새 직무)이 처음 부르는 것들.
    if (path === "/api/workers" && method === "GET") return json([]);
    if (path === "/api/workplace") return json({ workplace_code: "AB12CD", org_name: "테스트 사업장" });
    if (path === "/api/tasks" && method === "GET") return json([]);
    // 새 직무 화면: 나누기 미리보기 → 초안 만들기(1단계는 확인할 자동 그림, 2단계는 그림 없음).
    if (path === "/api/tasks/split-preview" && method === "POST") {
      return json({
        task_title: "컵 씻기", job: "cafe",
        steps: [
          { order: 1, sentence: "손을 씻어요.", action_type: "clean", symbol_query: [], split_group: null, split_check: false, source_text: null },
          { order: 2, sentence: "컵을 씻어요.", action_type: "clean", symbol_query: [], split_group: null, split_check: false, source_text: null },
        ],
      });
    }
    if (path === "/api/tasks" && method === "POST") {
      const body = req.postDataJSON() as { steps: { sentence: string }[] };
      return json({
        id: "task-new", title: "컵 씻기", status: "draft",
        steps: body.steps.map((s, i) => ({
          id: `s${i + 1}`, order: i + 1, sentence: s.sentence, action_type: "clean",
          symbol_url: i === 0 ? `${API}/media/symbols/s1.png` : null, symbol_source: i === 0 ? "LOCAL_AAC" : "fallback",
          needs_fallback: i !== 0, tts_audio_url: null,
        })),
      }, 201);
    }
    return route.fulfill({ status: 599, headers: CORS, body: `unmocked ${method} ${path}` });
  });
  return m;
}

/** 저장된 사업주 로그인을 넣고 그 주소로 간다. */
export async function loginEmployer(page: Page, path = "/m/tasks") {
  await page.goto("/m/login");
  await page.evaluate(() => {
    localStorage.setItem("jobcard_token", "e2e-employer-token");
    localStorage.setItem("jobcard_role", "employer");
    localStorage.setItem("jobcard_name", "테스트사장");
  });
  await page.goto(path);
}

/** 문서가 가로로 넘치는 폭(0이면 가로 스크롤 없음). */
export async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

/** 화면 글에 든 그림 글자(이모지). ✦(자동 표기)·›·· 같은 기호는 이모지가 아니다. */
export async function emojiInText(page: Page): Promise<string[]> {
  return page.evaluate(() => Array.from(document.body.innerText.matchAll(/\p{Extended_Pictographic}/gu), (x) => x[0]));
}
