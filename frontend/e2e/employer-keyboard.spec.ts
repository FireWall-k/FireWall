import { test, expect, devices, type Page } from "@playwright/test";
import { loginEmployer } from "./employer-mock";
import { FIXED_SENTENCE, mockEditor } from "./editor-mock";

// 키보드만으로 새 직무 → 확인 → 보내기(명세 8.3-8, WCAG 2.1.1). 마우스를 쓰지 않는다: Tab으로 옮기고 Enter·Space로 누른다.
// 순서 바꾸기도 손잡이(Space로 들고 ↑↓, Space로 놓기)로 한다(WCAG 2.5.7).
const { defaultBrowserType: _ignored, ...DESKTOP } = devices["Desktop Chrome"];
void _ignored;
test.use({ ...DESKTOP, locale: "ko-KR", viewport: { width: 1440, height: 900 } });

/** 초점이 이름(접근 이름) 조건에 맞는 요소에 갈 때까지 Tab을 누른다. */
async function tabTo(page: Page, name: RegExp, max = 80) {
  for (let i = 0; i < max; i++) {
    await page.keyboard.press("Tab");
    const got = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el) return "";
      const label = el.getAttribute("aria-label") ?? "";
      const byId = el.id ? document.querySelector(`label[for="${el.id}"]`)?.textContent ?? "" : "";
      return `${label}|${byId}|${(el.innerText ?? "").trim()}`;
    });
    if (name.test(got)) return;
  }
  throw new Error(`Tab ${max}번 안에 ${name}에 닿지 못했어요`);
}

test("키보드만으로: 새 직무 → 나누기 → 그림 고르기 → 순서 바꾸기 → Enter로 확인 → 그림 한눈에 일괄 확인 → 보내기", async ({ page }) => {
  const m = await mockEditor(page);
  await loginEmployer(page, "/m/tasks");
  await tabTo(page, /^\|\|새 직무$/);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/m\/tasks\/new$/);
  await tabTo(page, /어떤 일을 시킬까요\?/);
  await page.keyboard.type(FIXED_SENTENCE);
  await tabTo(page, /\|단계로 나누기$/);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: /이렇게 나눴어요/ })).toBeFocused();
  await tabTo(page, /\|이대로 그림 고르기$/);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("task-editor")).toBeVisible();

  // 순서 바꾸기: 2단계 손잡이 → Space → ↑ → Space
  await tabTo(page, /^2단계 순서 바꾸기/);
  await page.keyboard.press("Space");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("Space");
  await expect(page.getByTestId("reorder-live")).toHaveText("1번째 자리에 놓았어요");
  await expect(page.getByTestId("step-row-1")).toContainText("상품을 선반에 놓아요.");

  // 지금 연 단계(첫 확인할 단계)를 확인: [이 그림이 맞아요]에서 Enter → 초점은 [다음 ▶]
  await tabTo(page, /\|이 그림이 맞아요/);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("review-queue").first()).toHaveAttribute("data-remaining", "5");
  await expect(page.locator(":focus")).toHaveAccessibleName(/다음 ▶/);

  // 남은 5장은 그림 한눈에서 한꺼번에
  await tabTo(page, /\|그림 한눈에$/);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "그림 한눈에 보기" })).toBeFocused();
  await expect(page.getByTestId("confirm-all")).not.toHaveAttribute("aria-disabled", "true");
  await tabTo(page, /\|보이는 자동 그림 모두 맞아요$/);
  await page.keyboard.press("Enter");
  // 누른 단추가 사라지면 초점은 [보내기]로 간다(body로 빠지지 않음)
  await expect(page.getByTestId("picture-overview").getByRole("button", { name: "보내기" })).toBeFocused();
  await page.keyboard.press("Enter");
  const sheet = page.getByRole("dialog", { name: "보내기 전에 확인해요" });
  await expect(sheet).toBeVisible();
  await tabTo(page, /\|1명에게 보내기$/);
  await page.keyboard.press("Enter");
  await expect(page.getByText("1명에게 보냈어요")).toBeVisible();
  expect(m.sends).toHaveLength(1);
  // 시트가 닫히면 초점은 연 단추 쪽으로 돌아온다(body가 아님)
  expect(await page.evaluate(() => document.activeElement?.tagName)).not.toBe("BODY");
});
