import { test, expect, devices, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { emojiInText, horizontalOverflow, loginEmployer, makeHelp, mockEmployer } from "./employer-mock";
import { loginAsWorker, mockWorkerBackend, newState } from "./w-mock";

// (2c) 홈 · 오늘 현황(명세 5.2, tasks §6 시험): 갱신 시각이 바뀜, 서랍 Esc·초점 복귀, 코칭 카드·도움 띠 → 편집기 1번,
// 새 사업장 빈 상태, /w에 서비스 워커 없음, 두 화면(근로자 [도와주세요] → 사업주 [도와줬어요] → 근로자 '선생님이 확인했어요'),
// axe 1440·390(띠·서랍 열림), 완료율 % 없음. API는 employer-mock·w-mock의 가짜 백엔드다.
const { defaultBrowserType: _ignored, ...DESKTOP } = devices["Desktop Chrome"];
void _ignored;
test.use({ ...DESKTOP, locale: "ko-KR", viewport: { width: 1440, height: 900 } });

// 서랍(Sheet)은 열릴 때 animate-sheet-in으로 미끄러져 들어온다. 움직이는 동안 재면 폭·색이 중간값으로 나와
// (480.00006px, 흐린 글자 대비) 느린 기계에서 가끔 실패했다 — 애니메이션이 끝난 뒤에 잰다.
async function settled(page: Page) {
  await page.evaluate(() => Promise.all(document.getAnimations().map((a) => a.finished.catch(() => undefined))));
}

async function axe(page: Page) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const serious = r.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
  return { serious, buttonName: r.violations.filter((v) => v.id === "button-name") };
}

test("홈: 제목 줄 갱신 시각이 5초마다 바뀌고, 요약 4칸·표·코칭 카드가 보이며 완료율 %가 없다", async ({ page }) => {
  const m = await mockEmployer(page);
  await loginEmployer(page, "/manager");
  await expect(page.getByRole("heading", { level: 1, name: "오늘 현황" })).toBeVisible();
  const line = page.getByTestId("live-status-line");
  await expect(line).toHaveText(/\d+월 \d+일 .요일 · 마지막 갱신 \d\d:\d\d:\d\d/);
  const first = await line.textContent();
  await expect(line).not.toHaveText(first!, { timeout: 12_000 });
  expect(m.liveCalls).toBeGreaterThanOrEqual(2);

  await expect(page.getByTestId("summary-working")).toContainText("3/4명");
  await expect(page.getByTestId("summary-help")).toContainText("1건");
  await expect(page.getByTestId("summary-stuck")).toContainText("1단계");
  const table = page.getByRole("table", { name: "근로자 실시간 현황" });
  await expect(table.getByText("박하늘")).toBeVisible();
  await expect(table.getByText("마지막 신호 6분 전")).toBeVisible();
  await expect(page.getByTestId("coaching-card")).toHaveCount(2);
  expect(await page.locator("main").innerText()).not.toMatch(/%/);
  expect(await emojiInText(page)).toEqual([]);

  // 요약 '막힘 의심' → 표가 걸러진다
  await page.getByTestId("summary-stuck").click();
  await expect(table.getByTestId("live-worker-name")).toHaveText(["이수진"]);
  await page.getByTestId("summary-stuck").click();
  await expect(table.getByTestId("live-worker-name")).toHaveCount(4);
});

test("연결이 끊기면 토스트 없이 제목 줄에 '연결이 잠시 끊겼어요 · 마지막 갱신 …'", async ({ page }) => {
  const m = await mockEmployer(page);
  await loginEmployer(page, "/manager");
  await expect(page.getByTestId("live-status-line")).toContainText("마지막 갱신");
  m.liveDown = true;
  await expect(page.getByTestId("live-status-line")).toHaveText(/^연결이 잠시 끊겼어요 · 마지막 갱신 \d\d:\d\d:\d\d$/, { timeout: 12_000 });
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByRole("table", { name: "근로자 실시간 현황" }).getByText("김민지")).toBeVisible();
  m.liveDown = false;
  await expect(page.getByTestId("live-status-line")).not.toContainText("끊겼어요", { timeout: 12_000 });
});

test("오늘 기록 서랍: 이름을 누르면 열리고 Esc로 닫히면 그 이름으로 초점이 돌아온다, 표로 보기", async ({ page }) => {
  await mockEmployer(page);
  await loginEmployer(page, "/manager");
  const name = page.getByRole("table", { name: "근로자 실시간 현황" }).getByRole("button", { name: "이수진", exact: true });
  await name.click();
  const dialog = page.getByRole("dialog", { name: "이수진 님 오늘 기록" });
  await expect(dialog).toBeVisible();
  await settled(page);
  expect((await dialog.boundingBox())!.width).toBeCloseTo(480, 0);
  await dialog.getByRole("tab", { name: "표로 보기" }).click();
  await expect(dialog.getByRole("table", { name: /단계별 기록/ })).toContainText("2분 30초");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(name).toBeFocused();
});

test("코칭 카드 [이 단계 고치기] → 편집기 그 단계로 1번(?step=&fix=)", async ({ page }) => {
  await mockEmployer(page);
  await loginEmployer(page, "/manager");
  const card = page.getByTestId("coaching-card").first();
  await expect(card).toContainText("다시 듣기 평균 3.4번");
  await expect(card).toContainText("사진으로 바꾸기");
  await card.getByRole("link", { name: /^이 단계 고치기/ }).click();
  await expect(page).toHaveURL(/\/manager\/tasks\/t3\?step=src5&fix=photo$/);
});

test("도움 띠 [이 단계 고치기] → 편집기 그 단계로 1번(?step=)", async ({ page }) => {
  await mockEmployer(page);
  await loginEmployer(page, "/manager/tasks");
  const band = page.getByTestId("help-band");
  await expect(band).toContainText("김민지 님이 도움을 요청했어요 · 택배 상자 포장하고 운송장 붙이기 3단계");
  await band.getByRole("button", { name: "이 단계 고치기" }).click();
  await expect(page).toHaveURL(/\/manager\/tasks\/t3\?step=src3$/);
});

test("새 사업장: 시작 점검표 3단계 + [바로 하기]", async ({ page }) => {
  await mockEmployer(page, { workers: false, help: false, coaching: false });
  await loginEmployer(page, "/manager");
  const empty = page.getByTestId("home-empty");
  await expect(empty).toBeVisible();
  await expect(empty.getByRole("listitem")).toHaveCount(3);
  await empty.getByRole("link", { name: "근로자 추가 바로 하기" }).click();
  await expect(page).toHaveURL(/\/manager\/workers$/);
});

test("서비스 워커: /w에는 없고, /m도 알림을 켜기 전에는 등록하지 않는다", async ({ page }) => {
  await mockEmployer(page);
  await loginEmployer(page, "/manager");
  await expect(page.getByTestId("live-status-line")).toContainText("마지막 갱신");
  expect(await page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length)).toBe(0);
  await page.goto("/worker");
  await page.waitForLoadState("networkidle");
  expect(await page.evaluate(() => navigator.serviceWorker.controller === null)).toBe(true);
  expect(await page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length)).toBe(0);
  // m-sw.js는 fetch 처리기가 없다(화면·API 요청을 가로채지 않음).
  const sw = await (await page.request.get("/m-sw.js")).text();
  expect(sw).toContain('addEventListener("push"');
  expect(sw).not.toMatch(/addEventListener\(\s*["']fetch/);
});

test("두 화면: 근로자 [도와주세요] → 사업주 띠 → [도와줬어요] → 근로자 '선생님이 확인했어요'", async ({ browser }) => {
  test.setTimeout(120_000); // 화면 두 개 + 폴링 5초 두 번
  const wctx = await browser.newContext({ ...devices["Pixel 7"], locale: "ko-KR" });
  const ectx = await browser.newContext({ ...DESKTOP, locale: "ko-KR", viewport: { width: 1440, height: 900 } });
  const wpage = await wctx.newPage();
  const epage = await ectx.newPage();
  const ws = newState();
  await mockWorkerBackend(wpage, ws);
  const m = await mockEmployer(epage, { help: false });
  await loginEmployer(epage, "/manager");
  await expect(epage.getByTestId("live-status-line")).toContainText("마지막 갱신");
  await expect(epage.getByTestId("help-band")).toHaveCount(0);

  // 화면 두 개를 번갈아 앞으로 둔다(뒤에 있는 화면은 브라우저가 타이머를 늦추거나 숨은 탭으로 볼 수 있다).
  await wpage.bringToFront();
  await loginAsWorker(wpage);
  await wpage.goto("/worker/job/asg-1/step/1");
  await wpage.getByTestId("help-button").click();
  await expect(wpage.getByTestId("help-band")).toContainText("선생님을 불렀어요");
  // 가짜 서버: 근로자가 부른 요청이 사업주 현황에 들어간다.
  expect(ws.helpCreates).toBe(1);
  m.help.push({ ...makeHelp(), worker_name: "김민수" });

  await epage.bringToFront();
  const band = epage.getByTestId("help-band");
  await expect(band).toContainText("김민수 님이 도움을 요청했어요", { timeout: 12_000 });
  await band.getByRole("button", { name: "도와줬어요" }).click();
  await expect(band).toHaveCount(0);
  expect(m.help[m.help.length - 1].state).toBe("resolved");
  ws.helpState = "resolved";
  await wpage.bringToFront();
  await expect(wpage.getByTestId("help-band")).toContainText("선생님이 확인했어요", { timeout: 12_000 });
  // 근로자 기기가 지금 단계를 알렸다(presence).
  expect((ws.presence ?? []).some((p) => p.assignment_id === "asg-1" && p.step_id === "s1")).toBe(true);
  await wctx.close();
  await ectx.close();
});

for (const width of [1440, 390] as const) {
  test.describe(`${width}폭 접근성`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 } });

    test("홈(띠 있음)·서랍 열림: axe 심각 0·button-name 0, 가로 스크롤 0", async ({ page }) => {
      await mockEmployer(page);
      await loginEmployer(page, "/manager");
      await expect(page.getByTestId("help-band")).toBeVisible();
      await expect(page.getByTestId("coaching-card").first()).toBeVisible();
      expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0);
      let r = await axe(page);
      expect(r.serious).toEqual([]);
      expect(r.buttonName).toEqual([]);

      await page.getByRole("table", { name: "근로자 실시간 현황" }).getByRole("button", { name: "김민지", exact: true }).click();
      await expect(page.getByRole("dialog", { name: "김민지 님 오늘 기록" })).toBeVisible();
      await expect(page.getByTestId("timeline-bars")).toBeVisible();
      await settled(page);
      r = await axe(page);
      expect(r.serious).toEqual([]);
      expect(r.buttonName).toEqual([]);
    });
  });
}

test.describe("390 도움 띠", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  test("[이 단계 고치기]·[확인했어요]는 … 메뉴로, 보이는 버튼은 44 이상", async ({ page }) => {
    await mockEmployer(page);
    await loginEmployer(page, "/manager");
    const band = page.getByTestId("help-band");
    await expect(band.getByRole("button", { name: "도와줬어요" })).toBeVisible();
    await expect(band.getByRole("button", { name: "이 단계 고치기" })).toBeHidden();
    const small = await band.evaluate((el) =>
      Array.from(el.querySelectorAll<HTMLElement>("button"))
        .filter((b) => b.offsetParent !== null)
        .filter((b) => b.getBoundingClientRect().height < 44)
        .map((b) => b.textContent),
    );
    expect(small).toEqual([]);
    await band.getByRole("button", { name: "김민지 님 도움 요청 메뉴 더 보기" }).click();
    await page.getByRole("menuitem", { name: "이 단계 고치기" }).click();
    await expect(page).toHaveURL(/\/manager\/tasks\/t3\?step=src3$/);
  });
});

test("오늘 기록 서랍: Tab을 여러 번 눌러도 초점이 서랍 안에 있고, 그 뒤 Esc로 닫힌다(비활성 탭 tabindex=-1을 마지막으로 세지 않음)", async ({ page }) => {
  await mockEmployer(page);
  await loginEmployer(page, "/manager");
  const name = page.getByRole("table", { name: "근로자 실시간 현황" }).getByRole("button", { name: "이수진", exact: true });
  await name.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "이수진 님 오늘 기록" });
  await expect(dialog).toBeVisible();
  await settled(page);
  const inDialog = () => dialog.evaluate((el) => el.contains(document.activeElement));
  for (let i = 0; i < 4; i++) {
    await page.keyboard.press("Tab");
    expect(await inDialog()).toBe(true);
  }
  for (let i = 0; i < 4; i++) {
    await page.keyboard.press("Shift+Tab");
    expect(await inDialog()).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(name).toBeFocused();
});

test("마지막 도움 요청에서 [도와줬어요]를 누르면 초점이 body가 아니라 본문(main)으로 간다", async ({ page }) => {
  const m = await mockEmployer(page);
  m.help.push({ ...makeHelp(), id: "h2", worker_id: "w2", worker_name: "이수진", created_at: new Date(Date.now() - 120_000).toISOString() });
  await loginEmployer(page, "/manager");
  const band = page.getByTestId("help-band");
  await expect(band.getByRole("button", { name: "도와줬어요" })).toHaveCount(2);
  await band.getByRole("button", { name: "도와줬어요" }).first().click();
  await expect(band.getByRole("button", { name: "도와줬어요" })).toHaveCount(1);
  await page.waitForTimeout(600);
  expect(await page.evaluate(() => document.activeElement?.id)).toBe("help");
  await band.getByRole("button", { name: "도와줬어요" }).click();
  await expect(band).toBeHidden();
  await page.waitForTimeout(600);
  expect(await page.evaluate(() => document.activeElement?.id)).toBe("main");
});

for (const width of [390, 360] as const) {
  test.describe(`${width}폭 근로자 표`, () => {
    test.use({ viewport: { width, height: 844 }, hasTouch: true, isMobile: true });
    test("표가 상자 안에 다 들어가고 상태 배지·… 메뉴가 화면 안에 있다", async ({ page }) => {
      await mockEmployer(page);
      await loginEmployer(page, "/manager");
      const table = page.getByRole("table", { name: "근로자 실시간 현황" });
      await expect(table.getByText("김민지")).toBeVisible();
      const m = await page.getByTestId("live-table").evaluate((root) => {
        const box = root.firstElementChild as HTMLElement;
        const menus = Array.from(root.querySelectorAll<HTMLElement>("button[aria-haspopup]")).map((b) => b.getBoundingClientRect().right);
        const badges = Array.from(root.querySelectorAll<HTMLElement>(".badge")).map((b) => {
          const r = b.getBoundingClientRect();
          return { right: r.right, clipped: b.scrollWidth > b.clientWidth };
        });
        return { scroll: box.scrollWidth, client: box.clientWidth, boxRight: box.getBoundingClientRect().right, menus, badges, inner: window.innerWidth };
      });
      expect(m.scroll).toBeLessThanOrEqual(m.client);
      expect(m.menus.length).toBe(4);
      for (const r of m.menus) expect(r).toBeLessThanOrEqual(Math.min(m.inner, m.boxRight));
      for (const b of m.badges) {
        expect(b.right).toBeLessThanOrEqual(m.boxRight);
        expect(b.clipped).toBe(false);
      }
      expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0);
    });
  });
}
