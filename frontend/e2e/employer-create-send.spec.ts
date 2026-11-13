import { test, expect, devices, type Page } from "@playwright/test";
import { horizontalOverflow, loginEmployer } from "./employer-mock";
import { FIXED_SENTENCE, fixedDraft, mockEditor } from "./editor-mock";

// 2b-1 만들고 보내기(tasks §4.4 Playwright): 1440 전체 흐름, 390에서 확인하고 보내기 끝까지(6단계 일괄 확인 포함),
// 새로고침해도 /manager/tasks/:id에 남고 초안이 다시 열림, VersionNotice 문구. 서버는 e2e/editor-mock.ts(유료 호출 없음).
const { defaultBrowserType: _ignored, ...DESKTOP } = devices["Desktop Chrome"];
void _ignored;

async function waitPictures(page: Page) {
  // 그림 한눈에 보기의 그림이 다 그려졌는지(decode) — [모두 맞아요]가 켜질 때까지.
  await expect(page.getByTestId("confirm-all")).not.toHaveAttribute("aria-disabled", "true");
}

test.describe("1440 전체 흐름", () => {
  test.use({ ...DESKTOP, locale: "ko-KR", viewport: { width: 1440, height: 900 } });

  test("[새 직무] → 나누기 → 그림 고르기 → 한 장은 Enter, 한 장은 후보로, 나머지는 일괄 확인 → 보내기 → 토스트 → 버전 안내", async ({ page }) => {
    const m = await mockEditor(page);
    await loginEmployer(page, "/manager/tasks");
    await page.getByRole("link", { name: "새 직무" }).first().click();
    await expect(page).toHaveURL(/\/manager\/tasks\/new$/);
    await page.getByLabel("어떤 일을 시킬까요?").fill(FIXED_SENTENCE);
    await page.getByRole("button", { name: "단계로 나누기" }).click();
    await expect(page.getByRole("heading", { name: /이렇게 나눴어요/ })).toBeVisible();
    await expect(page.getByLabel(/^\d+단계 문장$/)).toHaveCount(6);
    await page.getByRole("button", { name: "이대로 그림 고르기" }).click();

    await expect(page.getByTestId("task-editor")).toBeVisible();
    await expect(page).toHaveURL(/\/manager\/tasks\/task-\d+$/);
    const detail = page.getByTestId("step-detail");
    await expect(page.getByTestId("review-queue").first()).toHaveAttribute("data-remaining", "6");
    // 1단계: 자동 조심 제안(✦ 자동 제안)과 Enter 확인
    await expect(detail.getByText("✦ 자동 제안")).toBeVisible();
    await page.getByRole("heading", { name: /1단계 고치기/ }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("step-row-1")).toHaveAttribute("data-state", "confirmed");
    // 2단계: 다른 후보에서 고르기
    await page.getByTestId("step-row-2").getByRole("button").first().click();
    await detail.getByText("다른 후보 보기").click();
    await detail.getByRole("button", { name: /후보 2/ }).click();
    await expect(page.getByTestId("step-row-2")).toHaveAttribute("data-state", "confirmed");
    // 나머지 4장은 그림 한눈에서 한꺼번에
    await page.getByRole("button", { name: "그림 한눈에" }).click();
    await expect(page.getByRole("heading", { name: "그림 한눈에 보기" })).toBeVisible();
    await expect(page.getByRole("checkbox")).toHaveCount(4);
    await waitPictures(page);
    await page.getByTestId("confirm-all").click();
    await expect(page.getByText("모두 확인했어요").first()).toBeVisible();
    await page.getByTestId("picture-overview").getByRole("button", { name: "보내기" }).click();

    const sheet = page.getByRole("dialog", { name: "보내기 전에 확인해요" });
    await expect(sheet).toBeVisible();
    await expect(sheet.getByTestId("send-checklist")).toContainText("모든 단계에 그림이 있어요 6/6");
    await expect(sheet.getByTestId("send-checklist")).toContainText("✦ 자동으로 켠 조심 표시가 1개 있어요");
    await expect(sheet.getByRole("checkbox", { name: /김민지 님/ })).toBeChecked();
    expect(await sheet.innerText()).not.toMatch(/4821/);
    await sheet.getByRole("button", { name: "1명에게 보내기" }).click();
    await expect(sheet).toHaveCount(0);
    await expect(page.getByText("1명에게 보냈어요")).toBeVisible();
    await expect(page.getByRole("button", { name: "현황 보기" })).toBeVisible();
    expect(m.sends).toHaveLength(1);
    // 보낸 직무를 다시 열면 버전 안내(contract §3.7)
    // 하는 사람이 0명이고 고친 것이 없으면 '0명이 지금 하고 있어요'·'다음에 보낼 때부터 바뀌어요'를 붙이지 않는다(2회차 검증).
    await expect(page.getByTestId("version-notice")).toHaveText("이 직무를 받은 사람이 1명 있어요");
    expect(await horizontalOverflow(page)).toBe(0);
    expect(await page.locator("main").innerText()).not.toMatch(/\bAI\b|동작이 2개/);
  });

  test("새로고침해도 /manager/tasks/:id에 남고 초안이 다시 열린다", async ({ page }) => {
    await mockEditor(page);
    await loginEmployer(page, "/manager/tasks/new");
    await page.getByLabel("어떤 일을 시킬까요?").fill(FIXED_SENTENCE);
    await page.getByRole("button", { name: "단계로 나누기" }).click();
    await page.getByRole("button", { name: "이대로 그림 고르기" }).click();
    await expect(page.getByTestId("task-editor")).toBeVisible();
    const url = page.url();
    await page.reload();
    await expect(page).toHaveURL(url);
    await expect(page.getByTestId("task-editor")).toBeVisible();
    await expect(page.getByTestId(/^step-row-/)).toHaveCount(6);
    await expect(page.getByRole("heading", { level: 1, name: "상자 정리" })).toBeVisible();
  });

  test("입력 화면에서 새로고침해도 적던 원문이 남는다", async ({ page }) => {
    await mockEditor(page);
    await loginEmployer(page, "/manager/tasks/new");
    await page.getByLabel("어떤 일을 시킬까요?").fill("컵을 씻어요.");
    await page.reload();
    await expect(page.getByLabel("어떤 일을 시킬까요?")).toHaveValue("컵을 씻어요.");
  });
});

test.describe("390 확인하고 보내기 끝까지(사업주 휴대폰)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("목록 → 상세 전체 화면 → 아래 고정 줄 [그림 한눈에] → 6장 일괄 확인 → [보내기] → [1명에게 보내기]", async ({ page }) => {
    const draft = fixedDraft();
    const m = await mockEditor(page, { tasks: [draft] });
    await loginEmployer(page, `/manager/tasks/${draft.id}`);
    await expect(page.getByTestId("task-editor")).toBeVisible();
    // 390: 목록만, 상세는 행을 누르면 전체 화면
    await expect(page.getByTestId("step-detail")).toHaveCount(0);
    const bar = page.getByTestId("editor-bottom-bar");
    await expect(bar).toBeVisible();
    await expect(bar).toContainText("확인할 것 6개 남음");
    await page.getByTestId("step-row-3").getByRole("button").first().click();
    await expect(page.getByTestId("step-detail")).toBeVisible();
    await expect(page.getByTestId("step-row-1")).toHaveCount(0);
    await page.getByRole("button", { name: "단계 목록으로" }).click();
    await expect(page.getByTestId("step-row-1")).toBeVisible();
    expect(await horizontalOverflow(page)).toBe(0);

    await bar.getByRole("button", { name: "그림 한눈에" }).click();
    await expect(page.getByRole("checkbox")).toHaveCount(6);
    await waitPictures(page);
    await page.getByTestId("confirm-all").click();
    await expect(bar).toContainText("모두 확인했어요");
    expect(await horizontalOverflow(page)).toBe(0);
    await bar.getByRole("button", { name: "보내기" }).click();
    const sheet = page.getByRole("dialog", { name: "보내기 전에 확인해요" });
    const submit = sheet.getByRole("button", { name: "1명에게 보내기" });
    await expect(submit).toBeInViewport();
    await submit.click();
    await expect(page.getByText("1명에게 보냈어요")).toBeVisible();
    expect(m.sends).toEqual([{ taskId: draft.id, workerIds: ["w1"], day: "today" }]);
    // 아래 고정 줄의 단추는 화면 안(아래 탭바 위)에 있다
    const box = (await bar.boundingBox())!;
    const vh = page.viewportSize()!.height;
    expect(box.y + box.height).toBeLessThanOrEqual(vh);
  });
});
