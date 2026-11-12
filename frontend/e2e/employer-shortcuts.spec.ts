import { test, expect, devices, type Page } from "@playwright/test";
import { loginEmployer } from "./employer-mock";
import { FIXED_STEPS, fixedDraft, mockEditor } from "./editor-mock";

// 편집기 단축키·끌어서 순서 바꾸기(2b-2). 서버는 e2e/editor-mock.ts(유료 호출 없음).
const { defaultBrowserType: _d, ...DESKTOP } = devices["Desktop Chrome"];
void _d;
const blur = (page: Page) => page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
test.use({ ...DESKTOP, locale: "ko-KR", viewport: { width: 1440, height: 900 } });

test("J/K로 단계를 옮겨 다니고, 입력칸 안에서는 꺼지고, ?로 안내 창(창이 열린 동안 J 꺼짐)", async ({ page }) => {
  const t = fixedDraft();
  await mockEditor(page, { tasks: [t] });
  await loginEmployer(page, `/m/tasks/${t.id}`);
  await expect(page.getByTestId("step-row-1")).toHaveAttribute("data-selected", "true");
  await blur(page);

  await page.keyboard.press("j");
  await expect(page.getByTestId("step-row-2")).toHaveAttribute("data-selected", "true");
  await page.keyboard.press("j");
  await expect(page.getByTestId("step-row-3")).toHaveAttribute("data-selected", "true");
  await page.keyboard.press("k");
  await expect(page.getByTestId("step-row-2")).toHaveAttribute("data-selected", "true");

  // 입력칸에서는 글자가 들어가고 단계는 그대로
  await page.locator("#add-step-input").focus();
  await page.keyboard.type("jk");
  await expect(page.locator("#add-step-input")).toHaveValue("jk");
  await expect(page.getByTestId("step-row-2")).toHaveAttribute("data-selected", "true");
  await page.locator("#add-step-input").fill("");
  await blur(page);

  // ? → 안내 창, 창 안에서 J는 꺼짐
  await page.keyboard.press("Shift+Slash");
  const dlg = page.getByRole("dialog", { name: "단축키 안내" });
  await expect(dlg).toBeVisible();
  await expect(dlg.getByTestId("shortcut-help")).toContainText("단계 옮겨 다니기");
  await page.keyboard.press("j");
  await expect(page.getByTestId("step-row-2")).toHaveAttribute("data-selected", "true");
  await page.keyboard.press("Escape");
  await expect(dlg).toBeHidden();

  // E → 문장 칸, N → 새 단계 칸
  await blur(page);
  await page.keyboard.press("e");
  await expect(page.getByTestId("step-detail").locator("textarea")).toBeFocused();
  await blur(page);
  await page.keyboard.press("n");
  await expect(page.locator("#add-step-input")).toBeFocused();
  await expect(page.locator("#add-step-input")).toHaveValue("");

  // P → 1280 미리보기 서랍에 휴대폰 미리보기, 다시 P → 닫힘
  await blur(page);
  await page.keyboard.press("p");
  await expect(page.getByTestId("preview-drawer")).toHaveAttribute("data-state", "open");
  await expect(page.getByTestId("preview-drawer")).toHaveAttribute("data-layout", "side");
  await expect(page.getByTestId("preview-drawer").getByTestId("phone-preview")).toBeVisible();
  await blur(page);
  await page.keyboard.press("p");
  await expect(page.getByTestId("preview-drawer")).toHaveAttribute("data-state", "closed");
  await expect(page.getByTestId("phone-preview")).toHaveCount(0);
});

test("손잡이를 끌어 순서 바꾸기 → 서버에 새 순서", async ({ page }) => {
  const t = fixedDraft();
  const m = await mockEditor(page, { tasks: [t] });
  await loginEmployer(page, `/m/tasks/${t.id}`);
  const grip = page.getByTestId("step-grip-1");
  const target = page.getByTestId("step-row-3");
  const g = (await grip.boundingBox())!;
  const r = (await target.boundingBox())!;
  await page.mouse.move(g.x + g.width / 2, g.y + g.height / 2);
  await page.mouse.down();
  await page.mouse.move(g.x + g.width / 2, g.y + g.height / 2 + 20, { steps: 3 });
  await page.mouse.move(g.x + g.width / 2, r.y + r.height * 0.8, { steps: 8 });
  await page.mouse.up();
  await expect(page.getByTestId("step-row-3")).toContainText(FIXED_STEPS[0]);
  await expect(page.getByTestId("step-row-1")).toContainText(FIXED_STEPS[1]);
  await expect.poll(() => m.calls.filter((c) => c.includes("/steps/reorder")).length).toBeGreaterThan(0);
});
