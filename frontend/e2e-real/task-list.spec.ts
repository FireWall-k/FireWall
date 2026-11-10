import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import type { TaskListOut, TaskSummaryOut } from "../src/manager/api/types";

// 2a-1 직무 목록을 실제 백엔드에 붙여 본다(목킹 없음, playwright.real.config.ts 머리말 참고).
// tasks §3.5 시연 대본: ① 로그인 화면에서 Enter ② 사이드바 '직무' ③ '확인 필요' 걸러보기 ④ 한 직무 보관하기
// ⑤ '보관' 걸러보기에서 되살리기. 서버 결과(state·개수)는 API로 직접 확인한다 — 화면만 보고 믿지 않는다.
// phone 프로젝트는 390폭, tablet 프로젝트는 1440폭으로 넓혀 돈다(사업주 넓은 화면 = 사이드바).

const API = process.env.REAL_API_BASE ?? "http://127.0.0.1:8100";
const LOGIN = process.env.REAL_EMPLOYER_LOGIN ?? "realboss";
const PASSWORD = process.env.REAL_EMPLOYER_PASSWORD ?? "realtest1234";
const SHOTS = process.env.REAL_A1_SHOTS_DIR;

const RAW = "테이블을 행주로 닦아요. 의자를 테이블 안으로 넣어요. 쓰레기통을 비워요.";

// 프론트 TaskSummaryOut(src/manager/api/types.ts)의 필드. 서버 응답이 이것과 정확히 같아야 한다(계약이 어긋나면 실패).
const SUMMARY_KEYS: (keyof TaskSummaryOut)[] = [
  "id", "title", "state", "needs_check_count", "has_unsent_changes", "step_count", "cover_url",
  "recipients", "recipients_more", "updated_at", "current_version_no",
];

type Step = { id: string; sentence: string; symbol_url: string | null; picture_state?: string };
type TaskOut = { id: string; title: string; status: string; steps: Step[] };

async function ok<T>(res: Awaited<ReturnType<APIRequestContext["get"]>>): Promise<T> {
  if (!res.ok()) throw new Error(`${res.url()} → ${res.status()} ${await res.text()}`);
  return (await res.json()) as T;
}

const auth = (token: string) => ({ Authorization: `Bearer ${token}` });

async function employerToken(request: APIRequestContext): Promise<string> {
  const t = await ok<{ token: string }>(
    await request.post(`${API}/api/auth/login`, { data: { login_id: LOGIN, password: PASSWORD } }),
  );
  return t.token;
}

/** 그림 없는 단계에 그림을 붙이고 자동 그림은 확인한다(보내기 검사를 통과하게). real-flow.spec.ts와 같은 방식. */
async function givePictures(request: APIRequestContext, token: string, taskId: string, steps: Step[]) {
  const fallback = steps.find((s) => s.symbol_url)?.symbol_url ?? null;
  for (const s of steps) {
    if (s.picture_state === "confirmed") continue;
    if (s.symbol_url && s.picture_state && s.picture_state !== "none") {
      await ok(await request.post(`${API}/api/tasks/${taskId}/steps/${s.id}/picture/confirm`, { headers: auth(token) }));
      continue;
    }
    const found = await ok<{ matches: { image_url: string }[] }>(
      await request.post(`${API}/api/aac/search`, { headers: auth(token), data: { query: s.sentence, limit: 3 } }),
    );
    const url = found.matches[0]?.image_url ?? fallback;
    if (!url) throw new Error("붙일 그림을 찾지 못했다");
    await ok(
      await request.patch(`${API}/api/tasks/${taskId}/steps/${s.id}`, {
        headers: auth(token),
        data: { symbol_url: url, symbol_source: "LOCAL_AAC" },
      }),
    );
  }
}

async function makeTask(request: APIRequestContext, token: string, title: string): Promise<TaskOut> {
  const t = await ok<TaskOut>(
    await request.post(`${API}/api/tasks`, { headers: auth(token), data: { raw_input: RAW, business_type: "카페" } }),
  );
  // PATCH 제목(2a-1): 응답은 TaskOut
  const renamed = await ok<TaskOut>(
    await request.patch(`${API}/api/tasks/${t.id}`, { headers: auth(token), data: { title } }),
  );
  expect(renamed.title).toBe(title);
  return { ...t, title };
}

async function sendTo(request: APIRequestContext, token: string, task: TaskOut, workerId: string) {
  await givePictures(request, token, task.id, task.steps);
  await ok(
    await request.post(`${API}/api/tasks/${task.id}/send`, {
      headers: auth(token),
      data: { worker_ids: [workerId], day: "today" },
    }),
  );
}

async function list(request: APIRequestContext, token: string, filter = "all", q = ""): Promise<TaskListOut> {
  const qs = new URLSearchParams({ filter });
  if (q) qs.set("q", q);
  return ok<TaskListOut>(await request.get(`${API}/api/employer/tasks?${qs}`, { headers: auth(token) }));
}

async function shot(page: Page, width: number, name: string) {
  if (!SHOTS) return;
  const dir = `${SHOTS}/${width}`;
  mkdirSync(dir, { recursive: true });
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${dir}/${name}.png`, fullPage: false });
}

const widthOf = () => (test.info().project.name === "phone" ? 390 : 1440);

interface Seeded {
  token: string;
  draft: TaskOut; // 그림 없는 초안 → 초안·확인 필요 양쪽
  sent: TaskOut; // 보낸 그대로 → 보냄
  edited: TaskOut; // 보낸 뒤 단계를 더함 → 보냄·확인 필요, '고친 내용 안 보냄'
  workerName: string;
  workerId: string;
}

async function seed(request: APIRequestContext, tag: string): Promise<Seeded> {
  const token = await employerToken(request);
  const workerName = `목록${tag}`;
  const w = await ok<{ id: string }>(
    await request.post(`${API}/api/workers`, { headers: auth(token), data: { display_name: workerName } }),
  );
  const draft = await makeTask(request, token, `확인할 초안 ${tag}`);
  const sent = await makeTask(request, token, `보낸 직무 ${tag}`);
  await sendTo(request, token, sent, w.id);
  const edited = await makeTask(request, token, `보낸 뒤 고침 ${tag}`);
  await sendTo(request, token, edited, w.id);
  // 보낸 뒤 그림 없는 단계를 더한다 → 보낸 내용과 달라지고, 확인할 단계가 생긴다.
  await ok(
    await request.post(`${API}/api/tasks/${edited.id}/steps`, {
      headers: auth(token),
      data: { sentence: "행주를 빨아서 널어요.", action_type: "other" },
    }),
  );
  return { token, draft, sent, edited, workerName, workerId: w.id };
}

test.describe("2a-1 직무 목록(실제 서버)", () => {
  test("시연 대본: Enter 로그인 → 사이드바 '직무' → '확인 필요' → 보관하기 → '보관'에서 꺼내기", async ({ page, request }) => {
    const width = widthOf();
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    const tag = `${test.info().project.name}${Date.now() % 100000}`;
    const s = await seed(request, tag);

    // 서버 응답 모양 = 프론트 TaskSummaryOut(필드가 하나라도 다르면 실패)
    const all = await list(request, s.token, "all", tag);
    expect(Object.keys(all.counts).sort()).toEqual(["all", "archived", "draft", "needs_check", "published"]);
    expect(all.items).toHaveLength(3);
    for (const it of all.items) expect(Object.keys(it).sort()).toEqual([...SUMMARY_KEYS].sort());
    const byId = Object.fromEntries(all.items.map((it) => [it.id, it]));
    expect(byId[s.draft.id]).toMatchObject({ state: "draft", current_version_no: null, has_unsent_changes: false });
    expect(byId[s.draft.id].needs_check_count).toBeGreaterThan(0);
    expect(byId[s.sent.id]).toMatchObject({ state: "published", current_version_no: 1, needs_check_count: 0, has_unsent_changes: false });
    expect(byId[s.sent.id].recipients).toHaveLength(1);
    expect(byId[s.sent.id].recipients[0].initials).toBe(s.workerName.slice(0, 1));
    expect(byId[s.edited.id]).toMatchObject({ state: "published", has_unsent_changes: true });
    expect(byId[s.edited.id].needs_check_count).toBeGreaterThan(0);
    // 걸러보기는 겹친다: 확인할 초안은 초안·확인 필요 양쪽, 보낸 뒤 고친 직무는 보냄·확인 필요 양쪽
    const ids = async (f: string) => (await list(request, s.token, f, tag)).items.map((it) => it.id).sort();
    expect(await ids("draft")).toEqual([s.draft.id]);
    expect(await ids("needs_check")).toEqual([s.draft.id, s.edited.id].sort());
    expect(await ids("published")).toEqual([s.sent.id, s.edited.id].sort());
    expect(await ids("archived")).toEqual([]);
    const before = (await list(request, s.token)).counts;

    // ① 로그인 화면에서 Enter
    await page.goto("/m/login");
    await page.getByLabel("아이디").fill(LOGIN);
    await page.getByLabel("비밀번호").fill(PASSWORD);
    await shot(page, width, "01-login");
    await page.getByLabel("비밀번호").press("Enter");
    await expect(page).toHaveURL(/\/m(\?|$)/, { timeout: 15_000 });

    // ② 사이드바(390은 아래 탭바) '직무'
    const nav = width === 390 ? page.getByTestId("mobile-tabbar") : page.getByTestId("sidebar");
    await nav.getByRole("link", { name: "직무" }).click();
    await expect(page).toHaveURL(/\/m\/tasks$/);
    const table = page.getByRole("table", { name: "직무 목록" });
    for (const t of [s.draft, s.sent, s.edited]) await expect(table.getByText(t.title, { exact: true })).toBeVisible();
    await expect(page.getByRole("tab", { name: /전체/ })).toContainText(String(before.all));
    await expect(page.getByRole("tab", { name: /확인 필요/ })).toContainText(String(before.needs_check));
    await shot(page, width, "02-tasks-all");

    // ③ '확인 필요' 걸러보기: 초안과 보낸 뒤 고친 직무가 함께, 보낸 그대로인 직무는 빠짐
    await page.getByRole("tab", { name: /확인 필요/ }).click();
    await expect(page).toHaveURL(/filter=needs_check/);
    await expect(table.getByText(s.sent.title, { exact: true })).toBeHidden();
    await expect(table.getByText(s.draft.title, { exact: true })).toBeVisible();
    await expect(table.getByText(s.edited.title, { exact: true })).toBeVisible();
    const editedRow = table.getByRole("row").filter({ hasText: s.edited.title });
    await expect(editedRow.getByText("고친 내용 안 보냄").filter({ visible: true })).toBeVisible();
    await expect(editedRow.getByText(/^확인 필요 \d+$/).filter({ visible: true })).toBeVisible();
    await shot(page, width, "03-needs-check");

    // ④ 한 직무(확인할 초안) 보관하기
    await page.getByRole("button", { name: `${s.draft.title} 메뉴` }).click();
    await page.getByRole("menuitem", { name: "보관하기" }).click();
    await expect(page.getByText(`'${s.draft.title}'`).filter({ hasText: "보관함으로 옮겼어요" })).toBeVisible();
    await expect(table.getByText(s.draft.title, { exact: true })).toBeHidden();
    await expect(page.getByRole("tab", { name: /보관/ })).toContainText(String(before.archived + 1));
    await shot(page, width, "04-archived-toast");
    let row = (await list(request, s.token, "archived", tag)).items;
    expect(row.map((it) => it.id)).toEqual([s.draft.id]);
    expect(row[0].state).toBe("archived");
    // 보관한 직무는 서버가 보내기를 막는다(409)
    const blocked = await request.post(`${API}/api/tasks/${s.draft.id}/send`, {
      headers: auth(s.token),
      data: { worker_ids: [s.workerId], day: "today" },
    });
    expect(blocked.status()).toBe(409);
    expect((await blocked.json()).code).toBe("archived");

    // ⑤ '보관' 걸러보기에서 되살리기
    await page.getByRole("tab", { name: /보관/ }).click();
    await expect(page).toHaveURL(/filter=archived/);
    await expect(table.getByText(s.draft.title, { exact: true })).toBeVisible();
    await shot(page, width, "05-archived-filter");
    await page.getByRole("button", { name: `${s.draft.title} 메뉴` }).click();
    await page.getByRole("menuitem", { name: "보관함에서 꺼내기" }).click();
    await expect(page.getByText(`'${s.draft.title}'`).filter({ hasText: "보관함에서 꺼냈어요" })).toBeVisible();
    await expect(table.getByText(s.draft.title, { exact: true })).toBeHidden();
    await expect(page.getByRole("tab", { name: /보관/ })).toContainText(String(before.archived));
    await page.getByRole("tab", { name: /초안/ }).click();
    await expect(table.getByText(s.draft.title, { exact: true })).toBeVisible();
    await shot(page, width, "06-restored-draft");
    row = (await list(request, s.token, "draft", tag)).items;
    expect(row.map((it) => it.id)).toEqual([s.draft.id]);
    expect((await list(request, s.token)).counts).toEqual(before);
  });

  test("복제해서 고치기 → 보관 → 완전히 지우기, 보관 안 한 직무는 서버가 지우기를 막음", async ({ page, request }) => {
    const width = widthOf();
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    const tag = `d${test.info().project.name}${Date.now() % 100000}`;
    const token = await employerToken(request);
    const w = await ok<{ id: string }>(
      await request.post(`${API}/api/workers`, { headers: auth(token), data: { display_name: `복제${tag}` } }),
    );
    const orig = await makeTask(request, token, `원본 직무 ${tag}`);
    await sendTo(request, token, orig, w.id);
    // 보관 안 한 직무 지우기 → 409 한국어
    const del = await request.delete(`${API}/api/tasks/${orig.id}`, { headers: auth(token) });
    expect(del.status()).toBe(409);
    expect((await del.json()).detail).toBe("보관함으로 옮긴 직무만 완전히 지울 수 있어요.");

    await page.addInitScript((t) => {
      localStorage.setItem("jobcard_token", t);
      localStorage.setItem("jobcard_role", "employer");
      localStorage.setItem("jobcard_name", "통합 카페");
    }, token);
    await page.goto("/m/tasks");
    const table = page.getByRole("table", { name: "직무 목록" });
    await page.getByRole("button", { name: `${orig.title} 메뉴` }).click();
    await page.getByRole("menuitem", { name: "복제해서 고치기" }).click();
    const copyTitle = `${orig.title} (복사본)`;
    await expect(page.getByText(`'${copyTitle}'`).filter({ hasText: "새 초안으로 만들었어요" })).toBeVisible();
    await expect(table.getByText(copyTitle, { exact: true })).toBeVisible();
    const items = (await list(request, token, "all", tag)).items;
    const copy = items.find((it) => it.title === copyTitle);
    expect(copy).toMatchObject({ state: "draft", current_version_no: null, recipients: [], recipients_more: 0 });
    // 원래 직무의 버전·받은 사람은 그대로
    expect(items.find((it) => it.id === orig.id)).toMatchObject({ state: "published", current_version_no: 1 });
    expect(items.find((it) => it.id === orig.id)?.recipients).toHaveLength(1);
    await shot(page, width, "07-duplicated");

    // 복사본 보관 → 보관 걸러보기에서 완전히 지우기
    await page.getByRole("button", { name: `${copyTitle} 메뉴` }).click();
    await page.getByRole("menuitem", { name: "보관하기" }).click();
    await expect(table.getByText(copyTitle, { exact: true })).toBeHidden();
    await page.getByRole("tab", { name: /보관/ }).click();
    await page.getByRole("button", { name: `${copyTitle} 메뉴` }).click();
    await page.getByRole("menuitem", { name: "완전히 지우기" }).click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("수행 기록과 도움 요청 기록");
    await shot(page, width, "08-delete-dialog");
    await dialog.getByRole("button", { name: "완전히 지우기" }).click();
    await expect(page.getByText(`'${copyTitle}'`).filter({ hasText: "완전히 지웠어요" })).toBeVisible();
    await expect(table.getByText(copyTitle, { exact: true })).toHaveCount(0);
    const after = (await list(request, token, "all", tag)).items.map((it) => it.id);
    expect(after).toEqual([orig.id]);
    expect((await list(request, token, "archived", tag)).items).toEqual([]);
  });

  test("새 직무 ?example=1: 예시로 채워지고 'AI' 글자가 없다", async ({ page, request }) => {
    const width = widthOf();
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    const token = await employerToken(request);
    await page.addInitScript((t) => {
      localStorage.setItem("jobcard_token", t);
      localStorage.setItem("jobcard_role", "employer");
      localStorage.setItem("jobcard_name", "통합 카페");
    }, token);
    await page.goto("/m/tasks/new?example=1");
    await expect(page.getByLabel("직무 내용")).toHaveValue(/손을 깨끗이 씻어요/);
    await expect(page.getByLabel("업종")).toHaveValue("카페");
    await expect(page.getByTestId("example-note")).toBeVisible();
    expect(await page.locator("main").innerText()).not.toMatch(/\bAI\b/);
    await shot(page, width, "09-new-task-example");
  });
});
