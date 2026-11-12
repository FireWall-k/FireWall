import { test, expect, devices, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { loginEmployer } from "./employer-mock";
import { fourStateDraft, mockEditor } from "./editor-mock";

// 그림 정확도 ② (2026-11-13): '그림 없음' 단계에 비슷한 후보 3장을 바로 펼친다(예전 검토 화면처럼).
// 서버 순서(직무를 만들 때 순서가 맨 앞) 그대로, 한 번 눌러(마우스·키보드) 붙이면 확인함. 1440·390에서 axe 심각 0.
// 서버는 e2e/editor-mock.ts(유료 호출 없음) — /candidates는 단계마다 '{id}c1·c2·c3' 순서로 준다.
const { defaultBrowserType: _d, ...DESKTOP } = devices["Desktop Chrome"];
void _d;
test.use({ ...DESKTOP, locale: "ko-KR" });

const HEADING = "비슷한 그림을 찾았어요. 맞는 그림을 눌러 붙여요";

async function axeSerious(page: Page) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  return r.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical" || v.id === "button-name")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

for (const width of [1440, 390] as const) {
  test.describe(`${width}폭`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 } });

    test("그림 없음 단계: 후보 3장을 서버 순서로 펼치고 axe 심각 0, Enter 한 번으로 붙어 확인함", async ({ page }) => {
      const t = fourStateDraft();
      const none = t.steps[3];
      await mockEditor(page, { tasks: [t] });
      await loginEmployer(page, `/m/tasks/${t.id}`);
      await page.getByTestId("step-row-4").getByRole("button").first().click();
      const detail = page.getByTestId("step-detail");
      await expect(detail).toHaveAttribute("data-state", "none");

      const group = detail.getByRole("group", { name: HEADING });
      await expect(group).toBeVisible();
      const buttons = group.getByRole("button");
      await expect(buttons).toHaveCount(3);
      expect(await buttons.evaluateAll((els) => els.map((e) => e.getAttribute("data-candidate"))))
        .toEqual([`${none.id}c1`, `${none.id}c2`, `${none.id}c3`]);
      await expect(buttons.first()).toHaveAccessibleName("후보 1 후보 그림 1");
      await expect(detail.getByTestId("none-box")).toHaveCount(0);
      // 찾기·사진 단추는 그대로.
      await expect(detail.getByRole("button", { name: "다른 그림 찾기" })).toBeVisible();

      // 후보 단추는 눌러 쓸 만큼 크다(44px 이상)·화면 밖으로 넘치지 않는다.
      const box = (await buttons.first().boundingBox())!;
      expect(box.height).toBeGreaterThanOrEqual(44);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      expect(await page.locator("body").innerText()).not.toMatch(/\bAI\b/);

      expect(await axeSerious(page)).toEqual([]);

      // 키보드: 첫 후보에 초점 → Enter 한 번.
      await buttons.first().focus();
      await expect(buttons.first()).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(detail).toHaveAttribute("data-state", "confirmed");
      await expect(detail.locator("img").first()).toHaveAttribute("src", new RegExp(`${none.id}c1`));
      expect(await axeSerious(page)).toEqual([]);
    });
  });
}
