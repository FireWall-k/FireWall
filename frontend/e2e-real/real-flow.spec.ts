import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

// 실제 백엔드 통합 e2e(목킹 없음, playwright.real.config.ts 머리말 참고).
// 사업주 → 근로자(자동 4자리 번호) → 직무(그림 붙이기·게시·배정) → 근로자 화면을 브라우저로 끝까지 돈다.
// 서버 쪽 결과(배정 완료 여부, 도움 요청 상태, 기록 개수)는 API로 직접 확인한다 — 화면만 보고 믿지 않는다.

const API = process.env.REAL_API_BASE ?? "http://127.0.0.1:8100";
const LOGIN = process.env.REAL_EMPLOYER_LOGIN ?? "realboss";
const PASSWORD = process.env.REAL_EMPLOYER_PASSWORD ?? "realtest1234";
const SHOTS = process.env.REAL_SHOTS_DIR;

const RAW = "테이블을 행주로 닦아요. 의자를 테이블 안으로 넣어요. 쓰레기통을 비워요. 바닥을 빗자루로 쓸어요.";

interface Seed {
  employer: string;
  workplaceCode: string;
  workerId: string;
  workerName: string;
  code: string;
  taskId: string;
  title: string;
  sentences: string[];
  /** 사업주 편집 단계 id(steps). 고치기·지우기 API에 쓴다. */
  editStepIds: string[];
  /**
   * 근로자가 받은 버전의 단계 id. (2a-0) 보낼 때 버전 단계가 새 id로 고정되므로 편집 단계 id와 다르다.
   * 근로자 토큰이 생긴 뒤(pairAndLogin) 오늘 할 일에서 채운다.
   */
  stepIds: string[];
  assignmentId: string;
}

type Step = { id: string; order: number; sentence: string; symbol_url: string | null; picture_state?: string };

async function ok<T>(res: Awaited<ReturnType<APIRequestContext["get"]>>): Promise<T> {
  if (!res.ok()) throw new Error(`${res.url()} → ${res.status()} ${await res.text()}`);
  return (await res.json()) as T;
}

async function employerToken(request: APIRequestContext): Promise<string> {
  const t = await ok<{ token: string }>(
    await request.post(`${API}/api/auth/login`, { data: { login_id: LOGIN, password: PASSWORD } }),
  );
  return t.token;
}

const auth = (token: string) => ({ Authorization: `Bearer ${token}` });

/**
 * 그림 없는 단계에 그림을 붙이고(그림 검색 1순위, 없으면 다른 단계 그림), 자동으로 붙은 그림은 사업주처럼
 * 확인한다. (2a-0) 서버가 확인 안 한 자동 그림(auto_high·choose)을 보내기에서 422로 막는다.
 */
async function givePictures(request: APIRequestContext, token: string, taskId: string, steps: Step[]) {
  const fallback = steps.find((s) => s.symbol_url)?.symbol_url ?? null;
  for (const s of steps) {
    if (s.picture_state === "confirmed") continue;
    if (s.symbol_url && s.picture_state && s.picture_state !== "none") {
      await ok(
        await request.post(`${API}/api/tasks/${taskId}/steps/${s.id}/picture/confirm`, { headers: auth(token) }),
      );
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

async function seed(request: APIRequestContext, tag: string): Promise<Seed> {
  const employer = await employerToken(request);
  const wp = await ok<{ workplace_code: string }>(await request.get(`${API}/api/workplace`, { headers: auth(employer) }));
  const workerName = `통합${tag}`;
  const w = await ok<{ id: string; access_code: string }>(
    await request.post(`${API}/api/workers`, { headers: auth(employer), data: { display_name: workerName } }),
  );
  // 결정 3: 서버가 만든 자동 번호는 정확히 4자리.
  expect(w.access_code).toMatch(/^\d{4}$/);
  const task = await ok<{ id: string; title: string; steps: Step[] }>(
    await request.post(`${API}/api/tasks`, { headers: auth(employer), data: { raw_input: RAW, business_type: "카페" } }),
  );
  expect(task.steps.length).toBeGreaterThanOrEqual(3);
  await givePictures(request, employer, task.id, task.steps);
  await ok(await request.post(`${API}/api/tasks/${task.id}/publish`, { headers: auth(employer) }));
  const asg = await ok<{ id: string }[]>(
    await request.post(`${API}/api/tasks/${task.id}/assignments`, { headers: auth(employer), data: { worker_id: w.id } }),
  );
  return {
    employer,
    workplaceCode: wp.workplace_code,
    workerId: w.id,
    workerName,
    code: w.access_code,
    taskId: task.id,
    title: task.title,
    sentences: task.steps.map((s) => s.sentence),
    editStepIds: task.steps.map((s) => s.id),
    stepIds: [],
    assignmentId: asg[0].id,
  };
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  const dir = `${SHOTS}/${test.info().project.name}`;
  mkdirSync(dir, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: `${dir}/${name}.png` });
}

/** 근로자 토큰으로 오늘 할 일(다 한 일 포함)에서 이 배정 카드를 읽는다. */
async function todayCard(page: Page, request: APIRequestContext, assignmentId: string) {
  const token = await page.evaluate(() => localStorage.getItem("jobcard_token"));
  const list = await ok<{ assignment_id: string; status: string; done_step_ids: string[]; active_help: unknown; steps: Step[] }[]>(
    await request.get(`${API}/api/worker/me/today?include_done=true`, { headers: auth(token ?? "") }),
  );
  const card = list.find((c) => c.assignment_id === assignmentId);
  if (!card) throw new Error("오늘 할 일에 배정이 없다");
  return card;
}

async function pairAndLogin(page: Page, request: APIRequestContext, s: Seed) {
  await page.goto("/w/setup");
  await page.getByLabel("가게 코드").fill(s.workplaceCode);
  await page.getByRole("button", { name: "연결하기" }).click();
  await expect(page).toHaveURL(/\/w$/);
  await page.getByTestId("keypad").waitFor();
  await shot(page, "01-entry");
  for (const d of s.code) await page.getByRole("button", { name: d, exact: true }).click();
  await expect(page).toHaveURL(/\/w\/today$/, { timeout: 15_000 });
  await page.getByTestId("job-card").first().waitFor();
  // 근로자가 받은 버전의 단계 id(편집 단계 id와 다름).
  const card = await todayCard(page, request, s.assignmentId);
  expect(card.steps.map((x) => x.sentence)).toEqual(s.sentences);
  s.stepIds = card.steps.map((x) => x.id);
}

// 근로자 버튼은 600ms 안의 두 번째 누름을 무시한다(WorkerButton TAP_DEBOUNCE_MS, 손 떨림 막기). 칭찬 0.4초 뒤 다음
// 단계가 뜨자마자 누르면 그 간격 안이라 누름이 버려져 시험이 가끔 멈췄다 — 사람처럼 간격을 두고 누른다.
const TAP_GAP_MS = 650;
let lastDoneTap = 0;

async function pressDone(page: Page, expectUrl: RegExp) {
  const wait = lastDoneTap + TAP_GAP_MS - Date.now();
  if (wait > 0) await page.waitForTimeout(wait);
  await page.getByRole("button", { name: "다 했어요" }).click();
  lastDoneTap = Date.now();
  await expect(page).toHaveURL(expectUrl, { timeout: 10_000 });
}

const stepUrl = (s: Seed, n: number) => new RegExp(`/w/job/${s.assignmentId}/step/${n}$`);

test.describe("실제 백엔드 — 근로자 흐름", () => {
  test("키패드 → 오늘 → 단계 → 마지막 단계 도움(완료 아님) → 취소 → 완료 → 했던 일", async ({ page, request, browser }) => {
    const s = await seed(request, `흐름${test.info().project.name}`);
    const n = s.sentences.length;

    // 틀린 번호 먼저: 칸이 비고 쉬운 문장이 나온다(서버 401 문장이 그대로 나오지 않는다).
    await page.goto("/w/setup");
    await page.getByLabel("가게 코드").fill(s.workplaceCode);
    await page.getByRole("button", { name: "연결하기" }).click();
    await page.getByTestId("keypad").waitFor();
    const wrong = s.code === "0000" ? "1111" : "0000";
    for (const d of wrong) await page.getByRole("button", { name: d, exact: true }).click();
    await expect(page.getByTestId("login-notice")).toContainText("번호가 맞지 않아요");
    await expect(page.locator("body")).not.toContainText("접속 코드");
    await shot(page, "02-entry-wrong");

    for (const d of s.code) await page.getByRole("button", { name: d, exact: true }).click();
    await expect(page).toHaveURL(/\/w\/today$/, { timeout: 15_000 });
    const card = page.getByTestId("job-card").filter({ hasText: s.title });
    await card.waitFor();
    await shot(page, "03-today");

    await card.click();
    await expect(page).toHaveURL(new RegExp(`/w/job/${s.assignmentId}$`));
    await shot(page, "04-start");
    await page.getByRole("button", { name: "시작하기" }).click();
    await expect(page).toHaveURL(stepUrl(s, 1));
    await expect(page.getByTestId("step-sentence")).toHaveText(s.sentences[0]);
    // 그림이 실제 백엔드 이미지로 뜬다(깨진 그림 아님).
    await expect
      .poll(() => page.getByTestId("step-picture").locator("img").evaluate((i: HTMLImageElement) => i.naturalWidth))
      .toBeGreaterThan(0);
    await shot(page, "05-step1");

    for (let i = 1; i < n; i++) await pressDone(page, stepUrl(s, i + 1));
    await expect(page.getByTestId("step-sentence")).toHaveText(s.sentences[n - 1]);
    await shot(page, "06-step-last");

    // 마지막 단계에서 도움 요청 — 배정은 끝나지 않는다(예전 버그: 도움 요청이 완료 기록으로 들어가 done이 됨).
    await page.getByTestId("help-button").click();
    await expect(page.getByTestId("help-band-text")).toHaveText("선생님을 불렀어요. 여기서 기다려요.");
    await shot(page, "07-help-sent");
    const helps = await ok<{ id: string; state: string; worker_name?: string }[]>(
      await request.get(`${API}/api/employer/help?state=active`, { headers: auth(s.employer) }),
    );
    expect(helps.some((h) => h.state === "open")).toBe(true);
    let c = await todayCard(page, request, s.assignmentId);
    expect(c.status).not.toBe("done");
    expect(c.done_step_ids).toHaveLength(n - 1);
    expect(c.active_help).not.toBeNull();

    // 결정 8: 문장과 [취소]가 한 줄, [취소] 글자는 줄바꿈 없음.
    const cancel = page.getByRole("button", { name: "취소" });
    const tb = (await page.getByTestId("help-band-text").boundingBox())!;
    const cb = (await cancel.boundingBox())!;
    expect(cb.x).toBeGreaterThan(tb.x + tb.width - 1);
    expect(Math.abs(cb.y + cb.height / 2 - (tb.y + tb.height / 2))).toBeLessThan(cb.height / 2);

    await cancel.click();
    await expect(page.getByTestId("help-band-text")).toHaveCount(0);
    c = await todayCard(page, request, s.assignmentId);
    expect(c.status).not.toBe("done");
    expect(c.active_help).toBeNull();
    await shot(page, "08-help-cancelled");

    // 다시 부르면 사업주 화면 띠에 뜨고, 사업주가 [확인했어요]를 누르면 근로자 띠가 '선생님이 확인했어요'로 바뀐다.
    await page.getByTestId("help-button").click();
    await expect(page.getByTestId("help-band-text")).toBeVisible();
    const boss = await browser.newContext({ viewport: { width: 1280, height: 800 }, locale: "ko-KR" });
    const bossPage = await boss.newPage();
    await bossPage.addInitScript((t) => {
      localStorage.setItem("jobcard_token", t);
      localStorage.setItem("jobcard_role", "employer");
      localStorage.setItem("jobcard_name", "통합 카페");
    }, s.employer);
    await bossPage.goto("/m/tasks/new");
    // 2c: 옛 HelpAlertStrip 대신 틀(AppShell) 맨 위 도움 띠(HelpBand). 1280폭이라 [확인했어요]가 바로 보인다.
    const strip = bossPage.getByTestId("help-band-item").filter({ hasText: s.workerName });
    await expect(strip).toContainText(`${n}단계`, { timeout: 15_000 });
    if (SHOTS) await bossPage.screenshot({ path: `${SHOTS}/${test.info().project.name}/07b-employer-help-strip.png` });
    await strip.getByRole("button", { name: "확인했어요" }).click();
    await expect(page.getByText("선생님이 확인했어요")).toBeVisible({ timeout: 10_000 });
    await shot(page, "08b-help-acked");
    await boss.close();

    // 확인된 요청이 열린 채로 [다 했어요] — 서버가 요청을 닫고 배정이 끝난다.
    await pressDone(page, new RegExp(`/w/job/${s.assignmentId}/done$`));
    await shot(page, "09-job-done");
    c = await todayCard(page, request, s.assignmentId);
    expect(c.status).toBe("done");
    expect(c.done_step_ids).toHaveLength(n);
    expect(c.active_help).toBeNull();

    await page.getByRole("button", { name: "했던 일 보기" }).click();
    await expect(page).toHaveURL(/\/w\/history$/);
    await expect(page.getByText(s.title).first()).toBeVisible();
    await expect(page.getByText("다 했어요").first()).toBeVisible();
    await shot(page, "10-history");
    await page.getByText(s.title).first().click();
    await expect(page).toHaveURL(new RegExp(`/w/history/${s.assignmentId}$`));
    await expect(page.getByTestId("help-button")).toHaveCount(0);
    await shot(page, "11-history-review");

    // 홈: 다 한 카드는 체크와 함께 남는다.
    await page.goto("/w/today");
    await page.getByTestId("job-card").first().waitFor();
    await shot(page, "12-today-done");
  });

  test("일하는 중 인터넷이 끊겼다가 돌아오면 기록을 잃지 않는다", async ({ page, request }) => {
    const s = await seed(request, `끊김${test.info().project.name}`);
    const n = s.sentences.length;
    await pairAndLogin(page, request, s);
    await page.goto(`/w/job/${s.assignmentId}`);
    await page.getByRole("button", { name: "시작하기" }).click();
    await pressDone(page, stepUrl(s, 2));
    // 1단계 기록이 서버에 닿은 뒤에 끊는다(느린 기계에서는 보내는 중에 끊겨 대기열로 가서 아래 비교가 흔들렸다, 2c).
    await expect
      .poll(async () => (await todayCard(page, request, s.assignmentId)).done_step_ids, { timeout: 10_000 })
      .toEqual([s.stepIds[0]]);

    // 기기의 인터넷을 끊는다(와이파이가 잠깐 끊긴 것과 같다). API만 끊는 경우(page.route abort)는 아래
    // 새로고침 시험이 본다 — route를 걸면 Playwright가 브라우저 캐시를 꺼서 미리 받은 그림 확인을 못 한다.
    await page.context().setOffline(true);
    await pressDone(page, stepUrl(s, 3));
    await expect(page.getByText("인터넷이 끊겼어요. 일은 계속해도 돼요.")).toBeVisible({ timeout: 15_000 });
    // 끊긴 뒤 처음 들어온 단계도 그림이 보인다(오늘 할 일을 받을 때 미리 받아 둠, preload.ts).
    await expect
      .poll(() => page.getByTestId("step-picture").getAttribute("data-state"), { timeout: 10_000 })
      .toBe("ok");
    await shot(page, "13-offline-band");
    // 도움 요청은 대기열에 넣지 않고 사실대로 알린다.
    await page.getByTestId("help-button").click();
    await expect(page.getByTestId("help-band-text")).toHaveText("아직 못 불렀어요. 손을 들어 선생님을 불러요.");
    await shot(page, "14-offline-help-failed");
    await pressDone(page, stepUrl(s, 4));
    const queued = await page.evaluate(() =>
      Object.keys(localStorage).filter((k) => k.startsWith("jobcard_outbox_v1")).map((k) => localStorage.getItem(k)),
    );
    expect(JSON.stringify(queued)).toContain(s.stepIds[1]);
    expect(JSON.stringify(queued)).toContain(s.stepIds[2]);
    let c = await todayCard(page, request, s.assignmentId); // 테스트의 request는 끊지 않았다
    expect(c.done_step_ids).toEqual([s.stepIds[0]]);

    // 인터넷이 돌아오면(online 이벤트) 밀린 기록을 보낸다.
    await page.context().setOffline(false);
    await expect
      .poll(async () => (await todayCard(page, request, s.assignmentId)).done_step_ids.length, { timeout: 45_000 })
      .toBe(3);
    await shot(page, "15-synced");

    for (let i = 4; i < n; i++) await pressDone(page, stepUrl(s, i + 1));
    await pressDone(page, new RegExp(`/w/job/${s.assignmentId}/done$`));
    c = await todayCard(page, request, s.assignmentId);
    expect(c.status).toBe("done");
    expect(new Set(c.done_step_ids)).toEqual(new Set(s.stepIds));
    // 같은 단계 기록이 두 번 저장되지 않았다(재전송은 client_event_id로 한 번만) — 내보내기로 서버 기록을 센다.
    const exp = await ok<{ performance_logs: { assignment_id: string; step_id: string; completed: boolean }[] }>(
      await request.get(`${API}/api/workers/${s.workerId}/export`, { headers: auth(s.employer) }),
    );
    const logs = exp.performance_logs.filter((l) => l.assignment_id === s.assignmentId);
    expect(logs.map((l) => l.step_id).sort()).toEqual([...s.stepIds].sort());
    expect(logs.every((l) => l.completed)).toBe(true);
    const left = await page.evaluate(() =>
      Object.keys(localStorage)
        .filter((k) => k.startsWith("jobcard_outbox_v1"))
        .map((k) => localStorage.getItem(k))
        .join(""),
    );
    expect(left.replace(/[[\]{}"]|null/g, "")).toBe("");
  });

  test("일하는 중 새로고침하면 그 단계에서 이어 간다", async ({ page, request }) => {
    const s = await seed(request, `이어${test.info().project.name}`);
    await pairAndLogin(page, request, s);
    await page.goto(`/w/job/${s.assignmentId}`);
    await page.getByRole("button", { name: "시작하기" }).click();
    await pressDone(page, stepUrl(s, 2));
    await pressDone(page, stepUrl(s, 3));
    await expect.poll(async () => (await todayCard(page, request, s.assignmentId)).done_step_ids.length).toBe(2);

    await page.reload();
    await expect(page).toHaveURL(stepUrl(s, 3));
    await expect(page.getByTestId("step-sentence")).toHaveText(s.sentences[2]);
    await shot(page, "16-reload-resume");

    // 홈에서 다시 들어와도 3단계부터.
    await page.goto("/w/today");
    const card = page.getByTestId("job-card").filter({ hasText: s.title });
    await expect(card).toContainText("3단계부터 이어서 해요");
    await shot(page, "17-today-resume-card");
    await card.click();
    await shot(page, "18-start-resume");
    await page.getByRole("button", { name: "이어서 하기" }).click();
    await expect(page).toHaveURL(stepUrl(s, 3));

    // 끊긴 채로 끝낸 단계도 새로고침 뒤 다시 하라고 하지 않는다(대기열이 기억).
    await page.route(`${API}/**`, (r) => r.abort("internetdisconnected"));
    await pressDone(page, stepUrl(s, 4));
    await page.reload();
    await expect(page).toHaveURL(stepUrl(s, 4));
    await expect(page.getByTestId("step-sentence")).toHaveText(s.sentences[3]);
    // API만 끊겼던 경우라 online 이벤트가 오지 않는다 — 30초 재시도가 보낸다.
    await page.unroute(`${API}/**`);
    await expect
      .poll(async () => (await todayCard(page, request, s.assignmentId)).done_step_ids.length, { timeout: 45_000 })
      .toBe(3);
  });
});

// (2a-0) 결정 5: 보낸 직무를 고쳐도 하는 중인 근로자는 받은 버전 그대로 끝내고, 고친 내용은 다음 배정부터 간다.
test.describe("실제 백엔드 — 하는 중에 고쳐도 그대로", () => {
  test("1단계를 끝낸 뒤 사업주가 문장 고치기·지우기·더하기·순서 바꾸기·다시 보내기를 해도 진행·완료가 어긋나지 않는다", async ({ page, request }) => {
    const s = await seed(request, `고침${test.info().project.name}`);
    const n = s.sentences.length;
    const h = auth(s.employer);
    await pairAndLogin(page, request, s);
    await page.goto(`/w/job/${s.assignmentId}`);
    await page.getByRole("button", { name: "시작하기" }).click();
    await expect(page.getByTestId("step-sentence")).toHaveText(s.sentences[0]);
    await pressDone(page, stepUrl(s, 2));
    await expect.poll(async () => (await todayCard(page, request, s.assignmentId)).done_step_ids).toEqual([s.stepIds[0]]);
    const before = await todayCard(page, request, s.assignmentId);

    // 사업주: 2단계 문장을 고치고, 마지막 단계를 지우고, 새 단계를 더하고(그림 붙임), 순서를 뒤집는다.
    const edited = "행주를 물에 헹궈요.";
    await ok(await request.patch(`${API}/api/tasks/${s.taskId}/steps/${s.editStepIds[1]}`, { headers: h, data: { sentence: edited } }));
    await ok(await request.delete(`${API}/api/tasks/${s.taskId}/steps/${s.editStepIds[n - 1]}`, { headers: h }));
    const added = await ok<{ steps: Step[] }>(
      await request.post(`${API}/api/tasks/${s.taskId}/steps`, { headers: h, data: { sentence: "의자를 닦아요." } }),
    );
    await givePictures(request, s.employer, s.taskId, added.steps);
    const reversed = [...added.steps].sort((a, b) => b.order - a.order).map((x) => x.id);
    await ok(await request.patch(`${API}/api/tasks/${s.taskId}/steps/reorder`, { headers: h, data: { step_ids: reversed } }));
    const draft = await ok<{ steps: Step[]; version: { current_no: number; has_unsent_changes: boolean }; in_progress_count: number }>(
      await request.get(`${API}/api/tasks/${s.taskId}`, { headers: h }),
    );
    expect(draft.version).toEqual({ current_no: 1, has_unsent_changes: true });
    expect(draft.in_progress_count).toBe(1);

    // 근로자: 오늘 할 일은 받은 그대로(단계 id·문장·완료 기록).
    let c = await todayCard(page, request, s.assignmentId);
    expect(c.steps.map((x) => x.id)).toEqual(s.stepIds);
    expect(c.steps.map((x) => x.sentence)).toEqual(s.sentences);
    expect(c.done_step_ids).toEqual(before.done_step_ids);

    // 다시 보내기: 새 버전을 만들지만, 하는 중인 이 근로자는 옛 버전을 그대로 한다(kept_in_progress).
    const resend = await ok<{ version_no: number; version_created: boolean; results: { worker_id: string; outcome: string }[] }>(
      await request.post(`${API}/api/tasks/${s.taskId}/send`, { headers: h, data: { worker_ids: [s.workerId], day: "today" } }),
    );
    expect(resend.version_created).toBe(true);
    expect(resend.version_no).toBe(2);
    expect(resend.results).toEqual([expect.objectContaining({ worker_id: s.workerId, outcome: "kept_in_progress" })]);

    // 새로고침해도 2단계, 옛 문장 그대로.
    await page.reload();
    await expect(page).toHaveURL(stepUrl(s, 2));
    await expect(page.getByTestId("step-sentence")).toHaveText(s.sentences[1]);
    await shot(page, "30-edit-during-work-step2");

    // 남은 단계를 모두 끝내면 완료(지운 마지막 단계까지 받은 버전대로).
    for (let i = 2; i < n; i++) {
      await pressDone(page, stepUrl(s, i + 1));
      await expect(page.getByTestId("step-sentence")).toHaveText(s.sentences[i]);
    }
    await pressDone(page, new RegExp(`/w/job/${s.assignmentId}/done$`));
    c = await todayCard(page, request, s.assignmentId);
    expect(c.status).toBe("done");
    expect(c.done_step_ids).toEqual(s.stepIds);
    // 기록 수 그대로 — 편집이 기록을 지우지 않았다.
    const exp = await ok<{ performance_logs: { assignment_id: string; step_id: string; completed: boolean }[] }>(
      await request.get(`${API}/api/workers/${s.workerId}/export`, { headers: h }),
    );
    const logs = exp.performance_logs.filter((l) => l.assignment_id === s.assignmentId);
    expect(logs.map((l) => l.step_id).sort()).toEqual([...s.stepIds].sort());

    // 다 한 뒤 다시 보내면 새 배정(created)이 고친 내용(버전 2)으로 온다.
    const again = await ok<{ version_no: number; version_created: boolean; results: { outcome: string }[] }>(
      await request.post(`${API}/api/tasks/${s.taskId}/send`, { headers: h, data: { worker_ids: [s.workerId], day: "today" } }),
    );
    expect(again.version_created).toBe(false);
    expect(again.version_no).toBe(2);
    expect(again.results.map((r) => r.outcome)).toEqual(["created"]);
    const token = await page.evaluate(() => localStorage.getItem("jobcard_token"));
    const list = await ok<{ assignment_id: string; task_id: string; status: string; task_version_no: number; steps: Step[] }[]>(
      await request.get(`${API}/api/worker/me/today?include_done=true`, { headers: auth(token ?? "") }),
    );
    const fresh = list.find((x) => x.task_id === s.taskId && x.assignment_id !== s.assignmentId);
    expect(fresh).toBeTruthy();
    expect(fresh!.task_version_no).toBe(2);
    const current = await ok<{ steps: Step[] }>(await request.get(`${API}/api/tasks/${s.taskId}`, { headers: h }));
    expect(fresh!.steps.map((x) => x.sentence)).toEqual(current.steps.map((x) => x.sentence));
    expect(fresh!.steps.map((x) => x.sentence)).toContain(edited);
    expect(fresh!.steps).toHaveLength(n);

    // 근로자 화면: 새 카드로 들어가면 바뀐 순서의 첫 단계부터.
    await page.goto("/w/today");
    const card = page.locator(`[data-testid="job-card"]:not([data-done])`).filter({ hasText: s.title });
    await card.first().click();
    await expect(page).toHaveURL(new RegExp(`/w/job/${fresh!.assignment_id}$`));
    await page.getByRole("button", { name: "시작하기" }).click();
    await expect(page.getByTestId("step-sentence")).toHaveText(current.steps[0].sentence);
    await shot(page, "31-edit-during-work-next-assignment");
  });
});

test.describe("실제 백엔드 — 사업주", () => {
  test("그림 없는 단계는 보내지 못하고, 보내기 목록은 번호를 가린다", async ({ page, request }) => {
    test.skip(test.info().project.name !== "tablet", "사업주 화면은 한 번만 본다");
    const employer = await employerToken(request);
    const w = await ok<{ id: string; access_code: string; display_name: string }>(
      await request.post(`${API}/api/workers`, { headers: auth(employer), data: { display_name: `가림${Date.now() % 100000}` } }),
    );
    const task = await ok<{ id: string; steps: Step[] }>(
      await request.post(`${API}/api/tasks`, {
        headers: auth(employer),
        data: { raw_input: "테이블을 행주로 닦아요. 의자를 테이블 안으로 넣어요.", business_type: "카페" },
      }),
    );
    const missing = task.steps.filter((x) => x.picture_state === "none");
    // 규칙 모드에서 '행주로 닦아요'는 그림을 못 고른다. 혹시 붙으면 그림을 지운 단계를 하나 만든다.
    if (missing.length === 0) {
      const added = await ok<{ steps: Step[] }>(
        await request.post(`${API}/api/tasks/${task.id}/steps`, {
          headers: auth(employer),
          data: { sentence: "쀍쀍을 흔들어요" },
        }),
      );
      expect(added.steps.some((x) => x.picture_state === "none")).toBe(true);
    }
    const res = await request.post(`${API}/api/tasks/${task.id}/publish`, { headers: auth(employer) });
    expect(res.status()).toBe(422);
    // (2a-0) 서버 보내기 검사 문구(contract §1.4)와 그 단계 id.
    const blocked = (await res.json()) as { detail: string; code: string; step_ids: string[] };
    expect(blocked.detail).toMatch(/^\d+단계(?:(?:, |와 )\d+단계)*에 그림이 없어요\. 그림을 고르거나 사진을 올려 주세요\.$/);
    expect(blocked.code).toBe("send_blocked");
    expect(blocked.step_ids.length).toBeGreaterThanOrEqual(1);

    // 화면: 직무를 입력해 나누면 보내기가 막히고 한국어 안내가 나온다.
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.addInitScript((t) => {
      localStorage.setItem("jobcard_token", t);
      localStorage.setItem("jobcard_role", "employer");
      localStorage.setItem("jobcard_name", "통합 카페");
    }, employer);
    await page.goto("/m/tasks/new");
    await page.locator("textarea").first().fill("테이블을 행주로 닦아요. 의자를 테이블 안으로 넣어요.");
    await page.getByLabel("업종").fill("카페").catch(() => undefined);
    await page.getByRole("button", { name: "단계로 나누기" }).click();
    // dev의 입력 화면 나누기: 나눈 단계 목록을 먼저 보이고, 사업주가 확인하면 직무를 만든다.
    await page.getByRole("button", { name: "이대로 그림 고르기 ›" }).click({ timeout: 30_000 });
    await expect(page.getByText(/그림이 없는 단계가 있어요\(\d/)).toBeVisible({ timeout: 30_000 });
    await page.getByRole("checkbox").first().check();
    await expect(page.getByRole("button", { name: /게시하고/ })).toBeDisabled();
    // 보내기 목록(체크박스 묶음)에는 이름만, 등록된 근로자 목록의 번호는 ●로 가려진다.
    const group = page.getByRole("group", { name: /배정할 근로자/ });
    await expect(group).toContainText(w.display_name);
    await expect(group).not.toContainText(w.access_code);
    const code = page.getByTestId(`code-${w.id}`);
    await expect(code).toHaveText("(●●●●)");
    await expect(page.locator("body")).not.toContainText(`(${w.access_code})`);
    await page.getByText("그림이 없는 단계가 있어요").first().scrollIntoViewIfNeeded();
    await shot(page, "20-employer-blocked");
    await page.getByRole("button", { name: `${w.display_name} 번호 보기` }).click();
    await expect(code).toHaveText(`(${w.access_code})`);
    await expect(code).toHaveText("(●●●●)", { timeout: 8_000 });
  });

  // 1차 검증: 전역 버튼 nowrap 때문에 390px 휴대폰에서 직무 편집·근로자 목록이 옆으로 넘쳤다('삭제'·휴지통이 화면 밖).
  test("390px 휴대폰: 직무 편집(단계 있음)·근로자 목록이 옆으로 넘치지 않는다", async ({ page, request }) => {
    test.skip(test.info().project.name !== "phone", "휴대폰 폭에서만 본다");
    const employer = await employerToken(request);
    await ok(await request.post(`${API}/api/workers`, { headers: auth(employer), data: { display_name: `통합흐름phone${Date.now() % 1000}` } }));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript((t) => {
      localStorage.setItem("jobcard_token", t);
      localStorage.setItem("jobcard_role", "employer");
      localStorage.setItem("jobcard_name", "통합 카페");
    }, employer);
    const noSideScroll = async (label: string) => {
      const r = await page.evaluate(() => {
        const d = document.documentElement;
        const off = Array.from(document.querySelectorAll("button, a")).filter((e) => e.getBoundingClientRect().right > window.innerWidth + 1)
          .map((e) => (e as HTMLElement).innerText.slice(0, 20) || e.getAttribute("aria-label"));
        return { sw: d.scrollWidth, cw: d.clientWidth, off };
      });
      expect(r.sw, `${label}: scrollWidth ${r.sw} > ${r.cw}, 화면 밖 버튼 ${JSON.stringify(r.off)}`).toBeLessThanOrEqual(r.cw);
      expect(r.off, label).toEqual([]);
    };
    await page.goto("/m/workers");
    await page.getByRole("button", { name: "삭제" }).first().waitFor();
    await noSideScroll("근로자 목록");
    await shot(page, "21-employer-workers-390");
    await page.goto("/m/tasks/new");
    await page.getByLabel("직무 내용").fill(RAW);
    await page.getByRole("button", { name: "단계로 나누기" }).click();
    await expect(page.getByLabel("1단계 문장")).toBeVisible({ timeout: 60_000 });
    await page.waitForTimeout(1000);
    await noSideScroll("직무 편집");
    await shot(page, "22-employer-editor-390");
  });
});
