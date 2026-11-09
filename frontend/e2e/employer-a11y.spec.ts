import { test, expect, devices, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { loginEmployer, mockEmployer } from "./employer-mock";

// 사업주 접근성 자동 검사(명세 8.2·8.3, tasks §3.4): 로그인·직무 목록을 1440·390 폭에서 axe로 본다.
// 기준: 심각(serious·critical) 위반 0, 이름 없는 버튼(button-name) 0.
const { defaultBrowserType: _ignored, ...DESKTOP } = devices["Desktop Chrome"];
void _ignored;
test.use({ ...DESKTOP, locale: "ko-KR" });

async function axe(page: Page) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const serious = r.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
  const buttonName = r.violations.filter((v) => v.id === "button-name");
  return { serious, buttonName };
}

for (const width of [1440, 390] as const) {
  test.describe(`${width}폭`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 } });

    test("로그인 화면: axe 심각 0·button-name 0", async ({ page }) => {
      await mockEmployer(page);
      await page.goto("/m/login");
      await expect(page.getByRole("button", { name: "로그인", exact: true })).toBeVisible();
      const r = await axe(page);
      expect(r.serious).toEqual([]);
      expect(r.buttonName).toEqual([]);
    });

    test("직무 목록: axe 심각 0·button-name 0(도움 띠·행 메뉴 포함)", async ({ page }) => {
      await mockEmployer(page);
      await loginEmployer(page, "/m/tasks");
      await expect(page.getByText("컵 씻기")).toBeVisible();
      await expect(page.getByTestId("help-alert-strip")).toBeVisible();
      let r = await axe(page);
      expect(r.serious).toEqual([]);
      expect(r.buttonName).toEqual([]);

      // 메뉴를 연 상태(꺼 둔 '고치기'와 그 이유 포함)
      await page.getByRole("button", { name: "컵 씻기 메뉴" }).click();
      await expect(page.getByRole("menu")).toBeVisible();
      r = await axe(page);
      expect(r.serious).toEqual([]);
    });

    test("직무 목록 빈 상태: axe 심각 0", async ({ page }) => {
      await mockEmployer(page, { tasks: [] });
      await loginEmployer(page, "/m/tasks");
      await expect(page.getByText("아직 만든 직무가 없어요")).toBeVisible();
      expect((await axe(page)).serious).toEqual([]);
    });
  });
}

test("보관 걸러보기의 완전히 지우기 창: axe 심각 0", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockEmployer(page);
  await loginEmployer(page, "/m/tasks?filter=archived");
  await page.getByRole("button", { name: "옛 창고 정리 메뉴" }).click();
  await page.getByRole("menuitem", { name: "완전히 지우기" }).click();
  await expect(page.getByRole("alertdialog")).toBeVisible();
  expect((await axe(page)).serious).toEqual([]);
});

// ── 2회차 검증 반영: 초점이 body로 빠지지 않음, 토스트가 위험 창을 가리지 않음, 행동 뒤 다시 받기 ──

const activeTag = (page: Page) => page.evaluate(() => document.activeElement?.tagName ?? "");

async function archiveRow(page: Page, title: string) {
  await page.getByRole("button", { name: `${title} 메뉴` }).click();
  await page.getByRole("menuitem", { name: "보관하기" }).click();
  await expect(page.getByRole("button", { name: "실행 취소" })).toBeVisible();
}

test("토스트 [닫기](X)를 키보드로 누르면 초점이 body로 사라지지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockEmployer(page);
  await loginEmployer(page, "/m/tasks");
  await archiveRow(page, "앞치마 입기");
  const close = page.locator("[data-toast-layer] [role=status]").first().getByRole("button", { name: "닫기" });
  await close.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("[data-toast-layer] [role=status]")).toHaveCount(0);
  expect(await activeTag(page)).not.toBe("BODY");
});

test("완전히 지우기를 처리하는 동안에도 초점이 창 안에 있고 Tab도 창 안에서 돈다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockEmployer(page);
  // 지우기 요청을 2초 늦춘다(나중에 단 route가 먼저 받는다).
  await page.route("**/api/tasks/t9", async (route) => {
    await new Promise((r) => setTimeout(r, 2_000));
    await route.fallback();
  });
  await loginEmployer(page, "/m/tasks?filter=archived");
  await page.getByRole("button", { name: "옛 창고 정리 메뉴" }).click();
  await page.getByRole("menuitem", { name: "완전히 지우기" }).click();
  const dialog = page.getByRole("alertdialog");
  const confirm = dialog.getByRole("button", { name: "완전히 지우기" });
  await confirm.focus();
  await page.keyboard.press("Enter");
  await expect(confirm).toHaveAttribute("aria-busy", "true");
  const inside = () => page.evaluate(() => !!document.activeElement?.closest("[role=alertdialog]"));
  expect(await inside()).toBe(true);
  await page.keyboard.press("Tab");
  expect(await inside()).toBe(true);
  await expect(dialog).toHaveCount(0, { timeout: 5_000 });
});

test("390폭: 위험 창이 열린 동안 토스트는 창 아래로 내려가고(inert) 지워지는 것 목록을 가리지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockEmployer(page);
  await loginEmployer(page, "/m/tasks");
  await archiveRow(page, "앞치마 입기");
  await page.getByRole("tab", { name: /보관/ }).click();
  await page.getByRole("button", { name: "옛 창고 정리 메뉴" }).click();
  await page.getByRole("menuitem", { name: "완전히 지우기" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await expect(page.locator("[data-toast-layer] [role=status]")).toHaveCount(1); // 보관 토스트가 아직 떠 있다
  await expect(page.locator("[data-toast-layer]")).toHaveAttribute("inert", "");
  const covered = await dialog.locator("li").evaluateAll((lis) =>
    lis.map((li) => {
      const r = li.getBoundingClientRect();
      const top = document.elementFromPoint(r.left + 8, r.top + r.height / 2);
      return !!top?.closest("[data-toast-layer]");
    }),
  );
  expect(covered.length).toBe(4);
  expect(covered.every((c) => !c)).toBe(true);
});

test("보관 → '보관' 탭 → [실행 취소]: 목록이 불러오는 중에 멈추지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockEmployer(page);
  await loginEmployer(page, "/m/tasks");
  await archiveRow(page, "앞치마 입기");
  await page.getByRole("tab", { name: /보관/ }).click();
  await expect(page).toHaveURL(/filter=archived/);
  await expect(page.getByText("옛 창고 정리")).toBeVisible();
  await page.getByRole("button", { name: "실행 취소" }).click();
  await expect(page.getByRole("table")).not.toHaveAttribute("aria-busy", "true");
  await expect(page.getByText("옛 창고 정리")).toBeVisible();
  await expect(page.getByRole("table").getByText("앞치마 입기")).toHaveCount(0);
});

test("보관 요청이 끝나기 전에 '초안' 탭을 누르면 끝난 뒤에도 초안 목록이 보인다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockEmployer(page);
  await page.route("**/api/tasks/*/archive", async (route) => {
    await new Promise((r) => setTimeout(r, 1_500));
    await route.fallback();
  });
  await loginEmployer(page, "/m/tasks");
  await page.getByRole("button", { name: "앞치마 입기 메뉴" }).click();
  await page.getByRole("menuitem", { name: "보관하기" }).click();
  await page.getByRole("tab", { name: /초안/ }).click();
  await expect(page.getByRole("button", { name: "실행 취소" })).toBeVisible({ timeout: 5_000 });
  await expect(page.getByRole("table")).not.toHaveAttribute("aria-busy", "true");
  await expect(page.getByRole("table").getByText("컵 씻기")).toBeVisible();
});
