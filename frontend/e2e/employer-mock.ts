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
  };
}

export interface EmployerMock {
  tasks: MockTask[];
  help: ReturnType<typeof makeHelp>[];
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

export async function mockEmployer(page: Page, opts: { tasks?: MockTask[]; help?: boolean } = {}): Promise<EmployerMock> {
  const m: EmployerMock = {
    tasks: opts.tasks ?? makeTasks(),
    help: opts.help === false ? [] : [makeHelp()],
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
    // 근로자·설정·새 직무 화면이 처음 부르는 것들.
    if (path === "/api/workers" && method === "GET") return json([]);
    // (2d) GET /api/workplace는 device_link·teacher_title·worker_defaults를 함께 준다(contract §6.2).
    if (path === "/api/workplace") {
      return json({
        workplace_code: "AB12CD",
        org_name: "테스트 사업장",
        device_link: "http://localhost:5173/w?site=AB12CD",
        teacher_title: "선생님",
        worker_defaults: {},
      });
    }
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
