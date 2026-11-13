import { test, expect, devices, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { API, loginEmployer } from "./employer-mock";
import { fourStateDraft, mockEditor, type EditorMock } from "./editor-mock";

// 2b-2 편집기 휴대폰 미리보기(tasks §5): [미리보기] → iframe(/manager/preview/:taskId) 안 근로자 StepPlayer(review).
// 미리보기 동안 기록·도움·신호·측정 요청(performance-logs·worker/help·worker/presence·events)이 0건이어야 한다.
const { defaultBrowserType: _ignored, ...DESKTOP } = devices["Desktop Chrome"];
void _ignored;

const BANNED = /\/api\/(performance-logs|worker\/help|worker\/presence|events)(\/|\?|$)/;

async function mockPreview(page: Page, m: EditorMock) {
  // editor-mock보다 나중에 단 route가 먼저 받는다.
  await page.route(/\/api\/tasks\/[^/]+\/preview$/, async (route) => {
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split("/")[3]);
    const t = m.tasks.find((x) => x.id === id);
    if (!t) return route.fulfill({ status: 404, headers: { "access-control-allow-origin": "*" }, body: "{}" });
    m.calls.push(`GET /api/tasks/${id}/preview`);
    return route.fulfill({
      status: 200,
      headers: { "access-control-allow-origin": "*", "content-type": "application/json" },
      body: JSON.stringify({
        title: t.title,
        steps: t.steps.map((s, i) => ({
          id: s.id, order: i + 1, sentence: s.sentence, action_type: "other", symbol_url: s.url,
          symbol_source: s.url ? "LOCAL_AAC" : "fallback", needs_fallback: s.state === "none", tts_audio_url: null,
          picture_state: s.state, safety_flag: s.safety, group_break: s.groupBreak,
        })),
      }),
    });
  });
}

test.describe("편집기 미리보기 1440", () => {
  test.use({ ...DESKTOP, locale: "ko-KR", viewport: { width: 1440, height: 900 } });

  test("[미리보기] → 다음·이전·처음부터 → 경고 배지, 금지 요청 0건, axe 심각 0", async ({ page }) => {
    const draft = fourStateDraft();
    draft.steps[2].groupBreak = true;
    const m = await mockEditor(page, { tasks: [draft] });
    await mockPreview(page, m);
    const banned: string[] = [];
    page.on("request", (r) => {
      if (r.url().startsWith(API) && BANNED.test(new URL(r.url()).pathname)) banned.push(`${r.method()} ${r.url()}`);
    });

    await loginEmployer(page, `/manager/tasks/${draft.id}`);
    await expect(page.getByTestId("task-editor")).toBeVisible();
    await page.getByTestId("preview-toggle").click();
    await expect(page.getByTestId("preview-toggle")).toHaveAttribute("aria-expanded", "true");

    const panel = page.getByTestId("phone-preview");
    const frame = page.frameLocator('[data-testid="phone-preview-frame"]');
    const sentence = frame.locator("h1").first();
    await expect(sentence).toContainText("앞치마를 입어요.");
    await expect(panel.getByTestId("preview-position")).toHaveText("1/4단계");
    await expect(panel.getByTestId("preview-prev")).toBeDisabled();
    await expect(panel.getByText("고칠 것이 없어요")).toBeVisible();

    await panel.getByTestId("preview-next").click();
    await expect(sentence).toContainText("컵을 물에 넣어요.");
    await expect(panel.getByTestId("preview-position")).toHaveText("2/4단계");
    await panel.getByTestId("preview-next").click();
    await expect(sentence).toContainText("컵을 수세미로 닦아요.");
    await expect(panel.getByText("여기서 묶음이 나뉘어요")).toBeVisible();
    await panel.getByTestId("preview-next").click();
    await expect(sentence).toContainText("컵을 건조대에 엎어요.");
    await expect(panel.getByText("그림이 없어요")).toBeVisible();
    await expect(panel.getByTestId("preview-next")).toBeDisabled();

    await panel.getByTestId("preview-prev").click();
    await expect(sentence).toContainText("컵을 수세미로 닦아요.");
    await expect(panel.getByTestId("preview-position")).toHaveText("3/4단계");

    // 휴대폰 안의 근로자 [이전] 버튼도 바깥 위치 표시와 맞는다.
    await frame.getByRole("button", { name: /이전/ }).first().click();
    await expect(sentence).toContainText("컵을 물에 넣어요.");
    await expect(panel.getByTestId("preview-position")).toHaveText("2/4단계");

    await panel.getByTestId("preview-restart").click();
    await expect(sentence).toContainText("앞치마를 입어요.");
    await expect(panel.getByTestId("preview-position")).toHaveText("1/4단계");

    // 소리 자동 재생 없음: 미리보기 안에서 재생 중인 audio가 없다.
    const playing = await page
      .frame({ url: /\/manager\/preview\// })!
      .evaluate(() => Array.from(document.querySelectorAll("audio")).some((a) => !a.paused));
    expect(playing).toBe(false);

    // axe: 미리보기를 연 편집기(심각·치명 0).
    const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
    const serious = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id);
    expect(serious).toEqual([]);

    expect(m.calls.filter((c) => c.endsWith("/preview")).length).toBeGreaterThan(0);
    expect(banned).toEqual([]);

    // 닫기
    await page.getByTestId("preview-drawer").getByRole("button", { name: "미리보기 닫기" }).click();
    await expect(page.getByTestId("phone-preview")).toHaveCount(0);
  });
});

// 2b-2 병합 검증: 390(768 미만)에서는 오른쪽 단추 묶음이 숨고 P 단축키도 꺼져 있어 미리보기를 열 길이 없었다.
// 머리의 [미리보기](preview-toggle-mobile)를 실제로 눌러 목록·단계 상세 두 화면에서 전체 화면 서랍이 열려야 한다.
const { defaultBrowserType: _ignoredPixel, ...PIXEL } = devices["Pixel 7"];
void _ignoredPixel;

test.describe("편집기 미리보기 390", () => {
  test.use({ ...PIXEL, locale: "ko-KR", viewport: { width: 390, height: 844 } });

  test("목록·상세에서 [미리보기]를 눌러 전체 화면으로 열고 닫는다 — 금지 요청 0건, axe 심각 0, 가로 넘침 없음", async ({ page }) => {
    const draft = fourStateDraft();
    const m = await mockEditor(page, { tasks: [draft] });
    await mockPreview(page, m);
    const banned: string[] = [];
    page.on("request", (r) => {
      if (r.url().startsWith(API) && BANNED.test(new URL(r.url()).pathname)) banned.push(`${r.method()} ${r.url()}`);
    });

    await loginEmployer(page, `/manager/tasks/${draft.id}`);
    await expect(page.getByTestId("step-row-1")).toBeVisible();
    await expect(page.getByTestId("preview-toggle")).toBeHidden();
    const toggle = page.getByTestId("preview-toggle-mobile");
    const drawer = page.getByTestId("preview-drawer");

    for (const where of ["목록", "상세"] as const) {
      if (where === "상세") await page.getByTestId("step-row-1").getByRole("button").first().click();
      if (where === "상세") await expect(page.getByTestId("step-detail")).toBeVisible();
      await expect(toggle, where).toBeVisible();
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      await expect(drawer).toBeVisible();
      await expect(drawer).toHaveAttribute("data-layout", "full");
      const box = (await drawer.boundingBox())!;
      expect(Math.round(box.width), where).toBe(390);
      await expect(page.frameLocator('[data-testid="phone-preview-frame"]').locator("h1").first()).toContainText("앞치마를 입어요.");
      expect(await page.evaluate(() => document.documentElement.scrollWidth), where).toBeLessThanOrEqual(390);

      const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
      const serious = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id);
      expect(serious, where).toEqual([]);

      await drawer.getByRole("button", { name: "미리보기 닫기" }).click();
      await expect(drawer).toBeHidden();
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
    }
    expect(banned).toEqual([]);
  });
});
