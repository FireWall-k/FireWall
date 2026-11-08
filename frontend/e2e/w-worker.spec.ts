import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { FORBIDDEN_PATTERNS } from "../src/worker/copy";
import { LONG_SENTENCE, loginAsWorker, mockWorkerBackend, newState, pairedDevice, type MockState } from "./w-mock";

// 새 근로자 화면(/w) 자동 검사(명세 8.3의 1~6). 7번(백엔드)은 backend/tests/test_worker_phase1.py가 맡는다.
// 실제 브라우저 레이아웃으로 잰다(jsdom은 배치를 계산하지 않는다). API는 w-mock.ts의 가짜 백엔드.

const TOUCH_MIN_PX = 80;

const VIEWPORTS = [
  ["360×560", { width: 360, height: 560 }],
  ["390×740", { width: 390, height: 740 }],
  ["412×915", { width: 412, height: 915 }],
  ["844×390", { width: 844, height: 390 }],
  ["820×1180", { width: 820, height: 1180 }],
  ["1180×820", { width: 1180, height: 820 }],
] as const;

let state: MockState;

test.beforeEach(async ({ page }) => {
  state = newState();
  await mockWorkerBackend(page, state);
});

const doneButton = (page: Page) => page.getByRole("button", { name: "다 했어요" });

/** 1번: [다 했어요] 아래끝 ≤ innerHeight, 문서 스크롤 높이 = 뷰포트(문서는 스크롤하지 않음). */
async function expectDoneInViewport(page: Page, label: string) {
  const box = await doneButton(page).boundingBox();
  expect(box, `${label}: [다 했어요] 위치`).not.toBeNull();
  const { inner, scrollH } = await page.evaluate(() => ({
    inner: window.innerHeight,
    scrollH: document.documentElement.scrollHeight,
  }));
  expect(box!.y + box!.height, `${label}: [다 했어요] 아래끝 ${box!.y + box!.height} > ${inner}`).toBeLessThanOrEqual(inner + 0.5);
  expect(box!.y, `${label}: [다 했어요] 위끝`).toBeGreaterThanOrEqual(0);
  expect(scrollH, `${label}: 문서 스크롤 높이 ${scrollH} ≠ 뷰포트 ${inner}`).toBeLessThanOrEqual(inner);
  expect(box!.height).toBeGreaterThanOrEqual(88);
}

const INTERACTIVE = [
  "button", "a[href]", "input:not([type=hidden])", "select", "textarea",
  "[role=button]", "[role=link]", "[tabindex]:not([tabindex='-1'])",
].map((sel) => `${sel}:visible:not([data-teacher-only])`).join(", ");

async function expectTouchTargets(page: Page) {
  const targets = page.locator(INTERACTIVE);
  const count = await targets.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    const el = targets.nth(i);
    const box = await el.boundingBox();
    const label = ((await el.getAttribute("aria-label")) || (await el.innerText())).trim();
    expect(box!.height, `"${label}" 높이 ${box!.height}px`).toBeGreaterThanOrEqual(TOUCH_MIN_PX);
  }
}

async function expectNoSeriousAxe(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious, serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`).join("\n")).toEqual([]);
}

/** 5번: 화면 글자에 금지어·영어 없음. */
async function expectNoForbidden(page: Page, label: string) {
  const text = await page.evaluate(() => document.body.innerText);
  for (const re of FORBIDDEN_PATTERNS) expect(text, `${label}: ${re} — ${text.slice(0, 200)}`).not.toMatch(re);
}

test.describe("1. [다 했어요]가 늘 화면 안에 있다", () => {
  for (const [name, vp] of VIEWPORTS) {
    test(`${name}: 기본·도움 띠·글자 130%`, async ({ page }) => {
      await loginAsWorker(page);
      await page.setViewportSize(vp);
      // 가장 긴 문장 단계(3단계)에서 잰다.
      await page.goto("/w/job/asg-1/step/3");
      await expect(page.getByTestId("step-sentence")).toHaveText(LONG_SENTENCE);
      await expectDoneInViewport(page, `${name} 기본`);

      await page.getByTestId("help-button").click();
      await expect(page.getByTestId("help-band")).toContainText("선생님을 불렀어요. 여기서 기다려요.");
      await expectDoneInViewport(page, `${name} 도움 띠`);

      // 시스템 글자 130%.
      await page.addStyleTag({ content: "html { font-size: 130% !important; }" });
      await page.evaluate(() => window.dispatchEvent(new Event("resize")));
      await expectDoneInViewport(page, `${name} 글자 130%`);
    });
  }

  test("도움 띠 '불렀어요': 문장 왼쪽·[취소] 오른쪽 한 줄, [취소] 글자는 줄바꿈 없음(결정 8)", async ({ page }) => {
    await loginAsWorker(page);
    await page.setViewportSize({ width: 360, height: 640 });
    await page.goto("/w/job/asg-1/step/1");
    await page.getByTestId("help-button").click();
    const text = page.getByTestId("help-band-text");
    const cancel = page.getByRole("button", { name: "취소" });
    await expect(cancel).toBeVisible();
    const t = (await text.boundingBox())!;
    const c = (await cancel.boundingBox())!;
    expect(c.x, "[취소]는 문장 오른쪽").toBeGreaterThanOrEqual(t.x + t.width - 1);
    expect(c.y < t.y + t.height && t.y < c.y + c.height, "같은 줄(세로로 겹침)").toBe(true);
    const lines = await cancel.locator("span").last().evaluate((el) => el.getClientRects().length);
    expect(lines).toBe(1);
    expect(c.height).toBeLessThan(100);
  });
});

test("2. 근로자 문장은 낱말 단위 줄바꿈(keep-all)", async ({ page }) => {
  await loginAsWorker(page);
  await page.goto("/w/job/asg-1/step/3");
  const wb = await page.getByTestId("step-sentence").evaluate((el) => getComputedStyle(el).wordBreak);
  expect(wb).toBe("keep-all");
});

test.describe("3. 번호 넣기(/w)", () => {
  test("키가 80px 이상이고 axe 심각 위반이 없다", async ({ page }) => {
    await pairedDevice(page);
    await page.goto("/w");
    await expect(page.getByRole("heading", { name: "내 번호를 눌러요" })).toBeVisible();
    await expect(page.getByText("행복카페")).toBeVisible();
    // [들어가기] 키는 없다(창업자 결정 3). 맨 아래 줄 [지우기][0][비우기].
    await expect(page.getByRole("button", { name: "들어가기", exact: true })).toHaveCount(0);
    await expectTouchTargets(page);
    await expectNoSeriousAxe(page);
    await expectNoForbidden(page, "번호 넣기");
  });

  test("4번째 숫자에서 바로 들어가고, 틀리면 칸을 비우고, 3번째부터 선생님께 물어보라고 한다", async ({ page }) => {
    await pairedDevice(page);
    await page.goto("/w");
    const press = async (code: string) => {
      for (const d of code) await page.getByRole("button", { name: d, exact: true }).click();
    };
    await press("1235");
    await expect(page.getByTestId("login-notice")).toHaveText("번호가 맞지 않아요. 다시 눌러 봐요.");
    // 안내가 제목·번호 칸 자리에 대신 나온다(칸은 비워졌다). 첫 숫자를 누르면 안내가 닫히고 칸이 다시 보인다.
    await expect(page.getByTestId("code-boxes")).toHaveCount(0);
    await press("1");
    await expect(page.getByTestId("login-notice")).toHaveCount(0);
    await expect(page.getByTestId("code-boxes")).toHaveText("1");
    await press("236");
    await expect(page.getByTestId("login-notice")).not.toContainText("선생님께");
    await press("1237");
    await expect(page.getByTestId("login-notice")).toContainText("선생님께 번호를 물어봐요.");
    await expectNoForbidden(page, "번호 틀림");
    await press("1234");
    await expect(page).toHaveURL(/\/w\/today$/);
    await expect(page.getByText("김민수 님, 안녕하세요")).toBeVisible();
    expect(state.loginAttempts).toEqual(["1235", "1236", "1237", "1234"]);
  });

  test("연결 안 된 기기는 '연결 안 됨' 화면", async ({ page }) => {
    await page.goto("/w");
    await expect(page.getByText("이 기기를 아직 연결하지 않았어요")).toBeVisible();
    await page.getByRole("button", { name: "선생님용: 기기 연결하기" }).click();
    await page.getByLabel("가게 코드").fill("demo01");
    await page.getByRole("button", { name: "연결하기" }).click();
    await expect(page.getByRole("heading", { name: "내 번호를 눌러요" })).toBeVisible();
  });
});

test.describe("4. 오프라인", () => {
  test("도움 요청이 닿지 않으면 '아직 못 불렀어요'와 [다시 부르기]", async ({ page }) => {
    await loginAsWorker(page);
    await page.goto("/w/job/asg-1/step/1");
    await expect(page.getByTestId("step-sentence")).toBeVisible();
    state.helpOffline = true;
    await page.getByTestId("help-button").click();
    await expect(page.getByTestId("help-band")).toContainText("아직 못 불렀어요. 손을 들어 선생님을 불러요.");
    state.helpOffline = false;
    await page.getByRole("button", { name: "다시 부르기" }).click();
    await expect(page.getByTestId("help-band")).toContainText("선생님을 불렀어요");
    // 선생님이 확인하면 '선생님이 확인했어요'.
    state.helpState = "acknowledged";
    await expect(page.getByTestId("help-band")).toContainText("선생님이 확인했어요", { timeout: 8_000 });
  });

  test("끊긴 동안 끝낸 단계 기록은 대기열에 남았다가 다시 연결되면 보낸다", async ({ page }) => {
    await loginAsWorker(page);
    await page.goto("/w/job/asg-2/step/1");
    await expect(page.getByTestId("step-sentence")).toHaveText("밀대로 바닥을 닦아요");
    state.offline = true;
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await expect(page.getByTestId("offline-band")).toContainText("인터넷이 끊겼어요. 일은 계속해도 돼요.");
    await doneButton(page).click();
    // 마지막 단계: 서버가 못 받아도 완료 화면은 보인다.
    await expect(page.getByTestId("job-done-screen")).toBeVisible();
    expect(state.logs).toHaveLength(0);
    const queued = await page.evaluate(() => localStorage.getItem("jobcard_outbox_v1:w1"));
    expect(queued).toContain("c1");

    state.offline = false;
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await expect.poll(() => state.logs.length).toBe(1);
    expect(state.logs[0]).toMatchObject({ assignment_id: "asg-2", step_id: "c1", completed: true });
    expect(typeof state.logs[0].client_event_id).toBe("string");
    await expect(page.getByTestId("sync-notice")).toContainText("기록을 다 보냈어요");
    await expect.poll(() => page.evaluate(() => localStorage.getItem("jobcard_outbox_v1:w1"))).toBeNull();
  });

  test("새로고침해도 주소의 단계에서 이어 가고, 다른 기기에서 한 단계는 홈 카드에 '이어서'로 보인다", async ({ page }) => {
    state.jobs[0].done_step_ids = ["s1"];
    state.jobs[0].status = "in_progress";
    await loginAsWorker(page);
    await page.goto("/w/today");
    await expect(page.getByTestId("job-card").first()).toContainText("2단계부터 이어서 해요");
    await page.getByTestId("job-card").first().click();
    await page.getByRole("button", { name: "이어서 하기" }).click();
    await expect(page).toHaveURL(/\/w\/job\/asg-1\/step\/2$/);
    await page.reload();
    await expect(page.getByTestId("step-sentence")).toHaveText("테이프를 붙여요");
  });
});

test("5. 근로자 화면 전체에 금지어·영어가 없다", async ({ page }) => {
  await loginAsWorker(page);
  await page.goto("/w/today");
  await expect(page.getByTestId("today-screen")).toBeVisible();
  await expectNoForbidden(page, "홈");
  await expectTouchTargets(page);
  await expectNoSeriousAxe(page);

  await page.getByTestId("job-card").first().click();
  await expect(page.getByTestId("job-start-screen")).toBeVisible();
  await expectNoForbidden(page, "직무 시작");
  await page.getByRole("button", { name: "시작하기" }).click();

  for (const sentence of ["박스 바닥 덮개를 접어요", "테이프를 붙여요", LONG_SENTENCE]) {
    await expect(page.getByTestId("step-sentence")).toHaveText(sentence);
    await expectNoForbidden(page, "단계");
    await doneButton(page).click();
  }
  await expect(page.getByTestId("job-done-screen")).toBeVisible();
  await expect(page.getByText("택배 상자 포장을 다 했어요")).toBeVisible();
  await expect(page.getByText("다음 일: 매장 바닥 청소")).toBeVisible();
  await expectNoForbidden(page, "직무 완료");
  await expectTouchTargets(page);
  await expectNoSeriousAxe(page);
  await expect.poll(() => state.logs.length).toBe(3);

  await page.goto("/w/history");
  await expect(page.getByText("오늘", { exact: true })).toBeVisible();
  await expectNoForbidden(page, "했던 일");

  // 나가기 확인 화면.
  await page.goto("/w/job/asg-2/step/1");
  await page.getByRole("button", { name: "나가기" }).click();
  await expect(page.getByText("일을 멈출까요?")).toBeVisible();
  await expectNoForbidden(page, "나가기 확인");
});

test("[다 했어요]를 600ms 안에 두 번 눌러도 한 단계만 넘어간다", async ({ page }) => {
  await loginAsWorker(page);
  await page.goto("/w/job/asg-1/step/1");
  await expect(page.getByTestId("step-sentence")).toHaveText("박스 바닥 덮개를 접어요");
  // 두 누름의 간격을 브라우저 안에서 정확히 450ms로 맞춘다(Playwright 클릭 대기 시간에 흔들리지 않게).
  await doneButton(page).evaluate((btn: HTMLElement) => {
    btn.click();
    window.setTimeout(() => btn.click(), 450);
  });
  await expect(page.getByTestId("step-sentence")).toHaveText("테이프를 붙여요");
  await page.waitForTimeout(700);
  await expect(page.getByTestId("step-sentence")).toHaveText("테이프를 붙여요");
  await expect(page).toHaveURL(/step\/2$/);
});

test("6. 움직임 줄이기를 켜면 전환 시간이 0이다", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await loginAsWorker(page);
  await page.goto("/w/job/asg-1/step/1");
  const cell = page.getByTestId("step-picture-cell");
  await expect(cell).toBeVisible();
  const { anim, trans } = await cell.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { anim: cs.animationDuration, trans: cs.transitionDuration };
  });
  expect(["0s", "0ms"]).toContain(anim);
  expect(["0s", "0ms"]).toContain(trans);
});
