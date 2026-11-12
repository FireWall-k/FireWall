import { test, expect, devices, type Page } from "@playwright/test";
import { loginEmployer } from "./employer-mock";
import { FIXED_SENTENCE, fixedDraft, fourStateDraft, mockEditor } from "./editor-mock";

// 2b-1 1회차 검증에서 실제 브라우저로 재현한 편집기 문제를 고정한다(jsdom은 배치·초점 이동을 다 재현하지 못한다).
// 서버는 e2e/editor-mock.ts(유료 호출 없음).
const { defaultBrowserType: _d, ...DESKTOP } = devices["Desktop Chrome"];
void _d;
const { defaultBrowserType: _p, ...PIXEL } = devices["Pixel 7"];
void _p;

const onBody = (page: Page) => page.evaluate(() => !document.activeElement || document.activeElement === document.body);

test.describe("1440", () => {
  test.use({ ...DESKTOP, locale: "ko-KR", viewport: { width: 1440, height: 900 } });

  test("새 직무를 만든 뒤 [+ 새 직무] → 뒤로 가기: 편집기는 서버의 지금 상태를 보인다(만들 때 초안 아님)", async ({ page }) => {
    await mockEditor(page);
    await loginEmployer(page, "/m/tasks/new");
    await page.getByLabel("어떤 일을 시킬까요?").fill(FIXED_SENTENCE);
    await page.getByRole("button", { name: "단계로 나누기" }).click();
    await page.getByRole("button", { name: "이대로 그림 고르기" }).click();
    await expect(page.getByTestId("task-editor")).toBeVisible();
    await page.getByTestId("step-detail").getByRole("button", { name: "이 그림이 맞아요" }).click();
    await expect(page.getByTestId("review-queue").first()).toHaveAttribute("data-remaining", "5");
    await page.getByRole("link", { name: "새 직무" }).first().click();
    await expect(page).toHaveURL(/\/m\/tasks\/new$/);
    await page.goBack();
    await expect(page.getByTestId("task-editor")).toBeVisible();
    await expect(page.getByTestId("review-queue").first()).toHaveAttribute("data-remaining", "5");
    await expect(page.getByTestId("step-row-1")).toHaveAttribute("data-state", "confirmed");
  });

  test("확인한 자동 그림의 설명에는 ✦가 없다", async ({ page }) => {
    const t = fourStateDraft();
    await mockEditor(page, { tasks: [t] });
    await loginEmployer(page, `/m/tasks/${t.id}`);
    await page.getByTestId("step-row-1").getByRole("button").first().click();
    const cap = page.getByTestId("step-detail").locator("figcaption");
    await expect(cap).toContainText("확인한 그림");
    await expect(cap).not.toContainText("✦");
    await page.getByTestId("step-row-2").getByRole("button").first().click();
    await expect(cap).toContainText("✦ 자동으로 고른 그림");
    await page.getByTestId("step-detail").getByRole("button", { name: "이 그림이 맞아요" }).click();
    await expect(page.getByTestId("step-row-2")).toHaveAttribute("data-state", "confirmed");
    await expect(cap).not.toContainText("✦");
  });

  test("문장 칸에서 Enter로 저장하면 초점은 상세 제목(body로 빠지지 않음)", async ({ page }) => {
    const t = fourStateDraft();
    await mockEditor(page, { tasks: [t] });
    await loginEmployer(page, `/m/tasks/${t.id}`);
    await page.getByTestId("step-row-1").getByRole("button").first().click();
    const field = page.getByTestId("step-detail").getByLabel("문장", { exact: true });
    await field.fill("앞치마를 단단히 입어요.");
    await field.press("Enter");
    await expect(page.getByRole("heading", { name: /1단계 고치기/ })).toBeFocused();
    expect(await onBody(page)).toBe(false);
  });

  test("[↑][↓]로 옮겨도 초점이 body로 빠지지 않고, 끝에 닿으면 반대 방향 단추로 간다", async ({ page }) => {
    const t = fourStateDraft();
    await mockEditor(page, { tasks: [t] });
    await loginEmployer(page, `/m/tasks/${t.id}`);
    await page.getByRole("button", { name: "2단계 위로" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "1단계 아래로" })).toBeFocused();
    await page.getByRole("button", { name: "3단계 아래로" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "4단계 위로" })).toBeFocused();
    await page.getByRole("button", { name: "2단계 아래로" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "3단계 아래로" })).toBeFocused();
    await page.waitForTimeout(800);
    expect(await onBody(page)).toBe(false);
  });

  test("그림 한눈에: 그림 하나를 못 불러와도 나머지로 [모두 맞아요]를 누를 수 있다", async ({ page }) => {
    const t = fixedDraft();
    await mockEditor(page, { tasks: [t] });
    const broken = t.steps[2].url as string;
    await page.route(broken, (r) => r.abort());
    await loginEmployer(page, `/m/tasks/${t.id}`);
    await page.getByRole("button", { name: "그림 한눈에" }).first().click();
    await expect(page.getByTestId("overview-card-3")).toHaveAttribute("data-broken", "true");
    await expect(page.getByTestId("overview-broken-note")).toHaveText("불러오지 못한 그림 1장은 빼고 확인해요");
    await expect(page.getByTestId("confirm-all")).not.toHaveAttribute("aria-disabled", "true");
    await expect(page.getByRole("checkbox")).toHaveCount(5);
    await expect(page.getByRole("button", { name: "3단계 그림 다시 불러오기" })).toBeVisible();
    await page.getByTestId("confirm-all").click();
    await expect(page.getByTestId("overview-card-1")).toHaveAttribute("data-state", "confirmed");
    await expect(page.getByTestId("overview-card-3")).toHaveAttribute("data-state", "auto_high");
  });

  test("보내기 시트: 막힌 줄 없이 경고만 있으면 '막힌 줄' 안내 대신 막지 않는다는 안내", async ({ page }) => {
    const t = fixedDraft();
    for (const s of t.steps) s.state = "confirmed";
    await mockEditor(page, { tasks: [t] });
    await loginEmployer(page, `/m/tasks/${t.id}`);
    await page.getByTestId("editor-send").click();
    const sheet = page.getByRole("dialog", { name: "보내기 전에 확인해요" });
    await expect(sheet.getByTestId("send-checklist")).toContainText("✦ 자동으로 켠 조심 표시가 1개 있어요");
    await expect(sheet).toContainText("줄을 누르면 그 단계로 가요. 보내기는 그대로 할 수 있어요");
    await expect(sheet).not.toContainText("막힌 줄을 누르면");
  });

  test("새 직무에 적던 중 계정 메뉴 → 설정으로 가면 먼저 묻는다", async ({ page }) => {
    await mockEditor(page);
    await loginEmployer(page, "/m/tasks/new");
    await page.getByLabel("어떤 일을 시킬까요?").fill(FIXED_SENTENCE);
    await page.getByRole("button", { name: "단계로 나누기" }).click();
    await expect(page.getByRole("heading", { name: /이렇게 나눴어요/ })).toBeVisible();
    await page.getByRole("button", { name: /계정 메뉴/ }).click();
    await page.getByRole("menuitem", { name: "설정" }).click();
    await expect(page.getByText("적던 내용이 사라져요")).toBeVisible();
    await expect(page).toHaveURL(/\/m\/tasks\/new$/);
  });
});

test.describe("휴대폰", () => {
  test.use({ ...PIXEL, locale: "ko-KR" });

  for (const width of [390, 360, 320] as const) {
    test(`${width}: 아래 고정 줄의 [다음 ▶]는 가려지지 않고 '확인할 것 n개 남음'도 다 보인다`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      const t = fixedDraft();
      await mockEditor(page, { tasks: [t] });
      await loginEmployer(page, `/m/tasks/${t.id}`);
      const bar = page.getByTestId("editor-bottom-bar");
      const next = bar.getByRole("button", { name: /다음/ });
      await expect(next).toBeVisible();
      const hit = await next.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const ys = r.top + r.height / 2;
        return [r.left + 2, r.left + r.width / 2, r.right - 2].every((x) => el.contains(document.elementFromPoint(x, ys)));
      });
      expect(hit, "다음 단추 위에 다른 것이 없다").toBe(true);
      const text = bar.getByText("확인할 것 6개 남음");
      await expect(text).toBeVisible();
      const box = await text.boundingBox();
      expect(box!.x + box!.width).toBeLessThanOrEqual(width);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    });
  }

  test("390: 꺼진 [보내기]를 누르면 이유를 알려 주고 [다음 ▶]로 데려간다", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const t = fixedDraft();
    await mockEditor(page, { tasks: [t] });
    await loginEmployer(page, `/m/tasks/${t.id}`);
    // aria-disabled라 Playwright는 '꺼짐'으로 보고 기다린다 — 사람은 누를 수 있으므로 force로 누른다.
    await page.getByTestId("editor-send-mobile").tap({ force: true });
    const toast = page.getByText("확인할 것 6개가 남았어요. 확인하면 보낼 수 있어요").filter({ visible: true }).last();
    await expect(toast).toBeVisible();
    await page.getByRole("button", { name: "다음 ▶" }).filter({ hasNotText: "다음 확인할" }).last().click();
    await expect(page.getByRole("heading", { name: /1단계 고치기/ })).toBeVisible();
  });

  test("390: 단계를 지우면 초점은 이웃 단계 행(body로 빠지지 않음)", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const t = fourStateDraft();
    const neighbor = t.steps[3].id;
    await mockEditor(page, { tasks: [t] });
    await loginEmployer(page, `/m/tasks/${t.id}`);
    await page.getByTestId("step-row-3").getByRole("button").first().click();
    await page.getByRole("button", { name: "이 단계 지우기" }).click();
    await page.getByRole("button", { name: "지우기", exact: true }).click();
    await expect(page.getByTestId("step-row-3")).toBeVisible();
    await expect.poll(() => onBody(page)).toBe(false);
    const focused = await page.evaluate(() => document.activeElement?.closest("[data-step-id]")?.getAttribute("data-step-id"));
    expect(focused).toBe(neighbor);
  });

  test("휴대폰(pointer:coarse): 순서 손잡이는 44×44", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const t = fourStateDraft();
    await mockEditor(page, { tasks: [t] });
    await loginEmployer(page, `/m/tasks/${t.id}`);
    const box = await page.getByRole("button", { name: "1단계 순서 바꾸기" }).boundingBox();
    expect(box!.width).toBeGreaterThanOrEqual(44);
    expect(box!.height).toBeGreaterThanOrEqual(44);
  });

  // ── 2회차 검증 ──
  for (const width of [390, 360, 320] as const) {
    test(`${width}: 꺼진 [보내기]를 누르면 토스트는 아래 고정 줄 위에 뜨고, 툴팁은 화면 안에 있다`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      const t = fixedDraft();
      await mockEditor(page, { tasks: [t] });
      await loginEmployer(page, `/m/tasks/${t.id}`);
      await page.getByTestId("editor-send-mobile").tap({ force: true });
      const toast = page.locator("[data-toast-layer] > *").last();
      await expect(toast).toBeVisible();
      const barTop = (await page.getByTestId("editor-bottom-bar").boundingBox())!.y;
      const tb = (await toast.boundingBox())!;
      expect(tb.y + tb.height, "토스트가 고정 줄을 덮지 않는다").toBeLessThanOrEqual(barTop);
      // 고정 줄 단추를 그대로 누를 수 있다(토스트가 가로채지 않음).
      await page.getByTestId("editor-bottom-bar").getByRole("button", { name: "그림 한눈에" }).tap();
      await expect(page.getByTestId("picture-overview")).toBeVisible();
      await page.goto(`/m/tasks/${t.id}`);
      await page.getByTestId("editor-send-mobile").tap({ force: true });
      const tip = page.getByRole("tooltip").filter({ visible: true });
      if (await tip.count()) {
        const b = (await tip.first().boundingBox())!;
        expect(b.x).toBeGreaterThanOrEqual(0);
        expect(b.x + b.width, "툴팁이 오른쪽으로 잘리지 않는다").toBeLessThanOrEqual(width);
      }
    });
  }

  test("390: 보내기 시트 받는 사람·그림 한눈에 체크·조심 스위치·경로 링크는 손가락으로 누를 곳이 44px", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const t = fixedDraft();
    await mockEditor(page, { tasks: [t] });
    await loginEmployer(page, `/m/tasks/${t.id}`);
    const hitHeight = (sel: import("@playwright/test").Locator) =>
      sel.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const x = r.left + r.width / 2;
        const owns = (y: number) => {
          const at = document.elementFromPoint(x, y);
          return !!at && (at === el || el.contains(at) || (at instanceof HTMLLabelElement && at.control === el) || at.closest("label")?.control === el);
        };
        let top = r.top + r.height / 2;
        let bottom = top;
        while (owns(top - 1)) top -= 1;
        while (owns(bottom + 1)) bottom += 1;
        return bottom - top + 1;
      });
    const crumb = page.getByRole("link", { name: "직무", exact: true }).first();
    expect((await crumb.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await page.getByTestId("step-row-1").getByRole("button").first().click();
    const sw = page.getByTestId("step-detail").getByRole("switch");
    await sw.scrollIntoViewIfNeeded();
    expect(await hitHeight(sw)).toBeGreaterThanOrEqual(44);
    await page.goto(`/m/tasks/${t.id}`);
    await page.getByTestId("editor-bottom-bar").getByRole("button", { name: "그림 한눈에" }).tap();
    const box = page.getByTestId("picture-overview").getByRole("checkbox").first();
    await box.scrollIntoViewIfNeeded();
    expect(await hitHeight(box)).toBeGreaterThanOrEqual(44);
    // 보내기 시트 받는 사람 줄
    const done = fixedDraft();
    for (const st of done.steps) st.state = "confirmed";
    await mockEditor(page, { tasks: [done] });
    await page.goto(`/m/tasks/${done.id}`);
    await page.getByTestId("editor-send-mobile").tap();
    const who = page.getByRole("dialog", { name: "보내기 전에 확인해요" }).getByRole("checkbox", { name: /김민지 님/ });
    await who.scrollIntoViewIfNeeded();
    expect(await hitHeight(who)).toBeGreaterThanOrEqual(44);
  });

  test("390: 새 직무에서 나눈 뒤 [뒤로] → [앞으로]로 돌아와도 나눈 단계 목록이 남는다", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockEditor(page);
    await loginEmployer(page, "/m/tasks");
    await page.goto("/m/tasks/new");
    await page.getByLabel("어떤 일을 시킬까요?").fill(FIXED_SENTENCE);
    await page.getByRole("button", { name: "단계로 나누기" }).click();
    await expect(page.getByRole("button", { name: "이대로 그림 고르기" })).toBeVisible();
    await page.goBack();
    await page.goForward();
    await expect(page).toHaveURL(/\/m\/tasks\/new$/);
    await expect(page.getByRole("button", { name: "이대로 그림 고르기" })).toBeVisible();
  });
});

