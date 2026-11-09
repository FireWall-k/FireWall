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
