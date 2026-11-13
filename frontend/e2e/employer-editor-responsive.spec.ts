import { test, expect, devices, type Page } from "@playwright/test";
import { loginEmployer } from "./employer-mock";
import { FIXED_SENTENCE, fixedDraft, mockEditor } from "./editor-mock";

// 2b-2 편집기 넓은 화면(명세 5.5 반응형): 1280 세 칸(오른쪽 미리보기 서랍 자리), 820 두 칸 + 미리보기 아래 시트·[↑][↓] 늘 보임,
// 390 목록 → 상세 전체 화면, 320 가로 넘침 없음(불러오는 동안 포함). 그리고 ?fix= 딥링크, 새 직무에서 떠날 때 묻기.
// 서버는 e2e/editor-mock.ts(유료 호출 없음).
const { defaultBrowserType: _d, ...DESKTOP } = devices["Desktop Chrome"];
void _d;
const { defaultBrowserType: _p, ...PIXEL } = devices["Pixel 7"];
void _p;

const scrollW = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth);

test.describe("1280", () => {
  test.use({ ...DESKTOP, locale: "ko-KR", viewport: { width: 1280, height: 900 } });

  test("미리보기 서랍 자리는 접혀 있다가 [미리보기]로 상세 오른쪽 세 번째 칸에 열린다", async ({ page }) => {
    const t = fixedDraft();
    await mockEditor(page, { tasks: [t] });
    await loginEmployer(page, `/m/tasks/${t.id}`);
    const drawer = page.getByTestId("preview-drawer");
    await expect(drawer).toHaveAttribute("data-layout", "side");
    await expect(drawer).toHaveAttribute("data-state", "closed");
    await expect(drawer).toBeHidden();
    await expect(page.getByTestId("editor-panes")).toHaveAttribute("data-panes", "2");

    const toggle = page.getByTestId("preview-toggle");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(drawer).toBeVisible();
    await expect(drawer).toHaveAttribute("data-state", "open");
    await expect(page.getByTestId("editor-panes")).toHaveAttribute("data-panes", "3");
    const d = (await page.getByTestId("step-detail").boundingBox())!;
    const p = (await drawer.boundingBox())!;
    expect(p.x).toBeGreaterThanOrEqual(d.x + d.width);
    expect(p.x + p.width).toBeLessThanOrEqual(1280);
    expect(await scrollW(page)).toBeLessThanOrEqual(1280);

    await drawer.getByRole("button", { name: "미리보기 닫기" }).click();
    await expect(drawer).toBeHidden();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});

test.describe("820", () => {
  test.use({ ...DESKTOP, locale: "ko-KR", viewport: { width: 820, height: 1180 } });

  test("목록·상세 두 칸, 순서 손잡이는 늘 보이고, 미리보기는 아래 시트로 열린다", async ({ page }) => {
    const t = fixedDraft();
    await mockEditor(page, { tasks: [t] });
    await loginEmployer(page, `/m/tasks/${t.id}`);
    await expect(page.getByTestId("step-detail")).toBeVisible();
    await expect(page.getByTestId("editor-panes")).toHaveAttribute("data-panes", "2");
    const row = (await page.getByTestId("step-row-1").boundingBox())!;
    const det = (await page.getByTestId("step-detail").boundingBox())!;
    expect(det.x).toBeGreaterThan(row.x + row.width - 1);
    for (const n of [2, 3]) {
      await expect(page.getByRole("button", { name: `${n}단계 순서 바꾸기` })).toBeVisible();
    }
    expect(await scrollW(page)).toBeLessThanOrEqual(820);

    await page.getByTestId("preview-toggle").click();
    const drawer = page.getByTestId("preview-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer).toHaveAttribute("data-layout", "sheet");
    const box = (await drawer.boundingBox())!;
    expect(Math.round(box.y + box.height)).toBe(1180);
    expect(box.height).toBeLessThan(1180);
    // 시트가 열려도 두 칸은 그대로
    await expect(page.getByTestId("step-detail")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
  });
});

test.describe("휴대폰", () => {
  test.use({ ...PIXEL, locale: "ko-KR" });

  test("390: 목록만 보이고, 행을 누르면 상세가 전체 화면(한 칸)", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const t = fixedDraft();
    await mockEditor(page, { tasks: [t] });
    await loginEmployer(page, `/m/tasks/${t.id}`);
    await expect(page.getByTestId("step-row-1")).toBeVisible();
    await expect(page.getByTestId("step-detail")).toHaveCount(0);
    await expect(page.getByTestId("editor-panes")).toHaveAttribute("data-panes", "1");
    await page.getByTestId("step-row-1").getByRole("button").first().click();
    const det = page.getByTestId("step-detail");
    await expect(det).toBeVisible();
    await expect(page.getByTestId("step-row-1")).toHaveCount(0);
    const box = (await det.boundingBox())!;
    expect(box.width).toBeGreaterThan(390 - 40);
    await expect(page.getByTestId("editor-bottom-bar")).toBeVisible();
    expect(await scrollW(page)).toBeLessThanOrEqual(390);
  });

  test("320: 불러오는 동안과 첫 화면 모두 가로로 넘치지 않는다", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 800 });
    const t = fixedDraft();
    await mockEditor(page, { tasks: [t] });
    // 직무 불러오기를 늦춰 뼈대 화면을 붙잡아 둔다(부하가 걸린 병렬 실행과 같은 상황).
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    await page.route(`**/api/tasks/${t.id}`, async (route) => {
      if (route.request().method() === "GET") await gate;
      await route.fallback();
    });
    await loginEmployer(page, `/m/tasks/${t.id}`);
    await expect(page.getByTestId("editor-skeleton")).toBeVisible();
    expect(await scrollW(page), "뼈대 화면").toBeLessThanOrEqual(320);
    release();
    await expect(page.getByTestId("editor-bottom-bar").getByText("확인할 것 6개 남음")).toBeVisible();
    // 그린 뒤 몇 프레임 동안 매번 잰다(잠깐 넘쳤다 돌아오는 것도 잡게).
    const widths = await page.evaluate(
      () =>
        new Promise<number[]>((resolve) => {
          const out: number[] = [];
          const tick = () => {
            out.push(document.documentElement.scrollWidth);
            if (out.length >= 20) resolve(out);
            else requestAnimationFrame(tick);
          };
          tick();
        }),
    );
    expect(Math.max(...widths)).toBeLessThanOrEqual(320);
  });

  test("?step=&fix=picture로 오면 그 단계의 그림 찾기 창이 바로 열리고 주소에서 fix는 지워진다", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const t = fixedDraft();
    await mockEditor(page, { tasks: [t] });
    await loginEmployer(page, `/m/tasks/${t.id}?step=${t.steps[1].id}&fix=picture`);
    await expect(page.getByRole("dialog", { name: "2단계 그림 찾기" })).toBeVisible();
    await expect(page).not.toHaveURL(/fix=/);
    await expect(page).toHaveURL(new RegExp(`step=${t.steps[1].id}`));
  });

  test("새 직무에서 나눈 단계가 있을 때 아래 탭으로 떠나면 '적던 내용이 사라져요'를 묻는다", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockEditor(page);
    await loginEmployer(page, "/m/tasks/new");
    await page.getByLabel("어떤 일을 시킬까요?").fill(FIXED_SENTENCE);
    await page.getByRole("button", { name: "단계로 나누기" }).click();
    await expect(page.getByRole("heading", { name: /이렇게 나눴어요/ })).toBeVisible();
    await page.getByRole("link", { name: "홈" }).last().click();
    await expect(page.getByText("적던 내용이 사라져요")).toBeVisible();
    await expect(page).toHaveURL(/\/m\/tasks\/new$/);
  });
});
