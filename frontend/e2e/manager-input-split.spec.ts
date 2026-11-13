import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { loginEmployer } from "./employer-mock";
import { mockEditor } from "./editor-mock";

// 입력 화면에서 나누기를 끝내는 흐름(한 줄 = 한 동작 = 그림 1장)을 실제 브라우저로 본다:
//   [단계로 나누기] → 나눈 줄이 입력칸 아래에 → 노란 줄 [합치기]·[더 나누기]·고치기 → [이대로 그림 고르기] →
//   확인한 줄로 초안 생성 → 편집기(/manager/tasks/:id, 나누기 알림 없음).
// 2b-1 1회차 검증: 옛 화면(ManagerPage) 라벨('직무 내용'·'이대로 그림 고르기 ›'·'검토 · 수정')에 맞춘 채 남아 4개가 늘 실패했다.
// 새 직무(NewTaskPage)·편집기(TaskEditorPage) 기준으로 옮겼다. 백엔드는 e2e/editor-mock.ts(유료 호출 없음).
// 실제 백엔드 경로는 backend/tests/test_input_split.py와 e2e-real이 확인한다.
// E2E_SHOTS_DIR을 주면 1280px·390px 화면 사진을 그 폴더에 남긴다(디자인 확인용).

const INPUT = "출근하면 앞치마 입고 손 씻고, 컵 씻어서 건조대에 올려 놔.";
const SOURCE = "컵 씻어서 건조대에 올려 놔";

const PREVIEW = {
  task_title: "출근 준비",
  job: "cafe",
  steps: [
    { order: 1, sentence: "앞치마를 입어요.", action_type: "wear", symbol_query: ["앞치마"],
      split_group: null, split_check: false, source_text: null },
    { order: 2, sentence: "손을 씻어요.", action_type: "clean", symbol_query: ["손"],
      split_group: null, split_check: false, source_text: null },
    { order: 3, sentence: "컵을 씻어요.", action_type: "clean", symbol_query: ["컵"],
      split_group: 1, split_check: true, source_text: SOURCE },
    { order: 4, sentence: "컵을 건조대에 올려요.", action_type: "move", symbol_query: ["건조대"],
      split_group: 1, split_check: true, source_text: SOURCE },
  ],
};

async function splitInput(page: Page) {
  await page.getByLabel("어떤 일을 시킬까요?").fill(INPUT);
  await page.getByRole("button", { name: "단계로 나누기" }).click();
  await expect(page.getByRole("heading", { name: /이렇게 나눴어요/ })).toBeVisible();
}

test("입력 화면: 나눈 줄 확인 → 합치기 → 고치기 → 이대로 그림 고르기 → 편집기", async ({ page }) => {
  const m = await mockEditor(page, { preview: PREVIEW });
  await loginEmployer(page, "/manager/tasks/new");
  await splitInput(page);

  // 애매한 줄만 노랗다
  await expect(page.getByTestId("split-row-3")).toHaveAttribute("data-check", "true");
  await expect(page.getByTestId("split-row-1")).toHaveAttribute("data-check", "false");
  await expect(page.getByTestId("split-row-3")).toContainText(SOURCE);

  // 심각한 접근성 위반 없음
  const axe = await new AxeBuilder({ page }).include('[aria-labelledby="split-preview-title"]').analyze();
  expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);

  const shots = process.env.E2E_SHOTS_DIR;
  if (shots) {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.screenshot({ path: `${shots}/input-split-1280.png`, fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: `${shots}/input-split-390.png`, fullPage: true });
  }

  // 키보드로 합치기 → 초점은 합친 줄
  await page.getByRole("button", { name: "3단계와 4단계 합치기" }).focus();
  await page.keyboard.press("Enter");
  // 한 원래 문장에서 나온 줄을 모두 합치면 두 문장을 잇지 않고 원래 문장 한 줄로 되돌린다
  await expect(page.getByLabel("3단계 문장")).toHaveValue(SOURCE);
  await expect(page.getByLabel("3단계 문장")).toBeFocused();

  // 그 자리에서 고치기
  await page.getByLabel("2단계 문장").fill("손을 비누로 씻어요.");
  await page.getByRole("button", { name: "이대로 그림 고르기" }).click();

  await expect(page.getByTestId("task-editor")).toBeVisible();
  await expect(page).toHaveURL(/\/manager\/tasks\/task-\d+$/);
  expect(m.calls.filter((c) => c === "POST /api/tasks/split-preview")).toHaveLength(1);
  expect(m.creates).toHaveLength(1);
  expect(m.creates[0].steps.map((s) => s.sentence)).toEqual(["앞치마를 입어요.", "손을 비누로 씻어요.", SOURCE]);
  // 편집기에는 나누기 알림('동작이 n개')이 없다
  await expect(page.getByText(/동작이 \d개/)).toHaveCount(0);
});

test("390px 긴 목록: [이대로 그림 고르기]가 실패하면 버튼 아래 알림이 화면 안에 보인다", async ({ page }) => {
  const many = {
    ...PREVIEW,
    steps: Array.from({ length: 9 }, (_, i) => ({
      order: i + 1, sentence: `${i + 1}번째 일을 천천히 해요.`, action_type: "other", symbol_query: [],
      split_group: null, split_check: false, source_text: null,
    })),
  };
  await page.setViewportSize({ width: 390, height: 844 });
  await mockEditor(page, { preview: many, createFails: true });
  await loginEmployer(page, "/manager/tasks/new");
  await splitInput(page);
  const confirm = page.getByRole("button", { name: "이대로 그림 고르기" });
  await confirm.scrollIntoViewIfNeeded();
  await confirm.click();
  const alert = page.locator('[aria-labelledby="split-preview-title"]').getByRole("alert");
  await expect(alert).toContainText("초안을 만들지 못했어요");
  await expect(alert).toBeInViewport();
  // 목록은 그대로 남아 다시 누를 수 있다
  await expect(page.getByLabel("9단계 문장")).toHaveValue("9번째 일을 천천히 해요.");
});

// 키보드로 누른 단추가 꺼지거나 사라지면 실제 브라우저에서는 초점이 body로 빠졌다(jsdom은 재현 못 함).
test("키보드: [단계로 나누기] 뒤 초점은 '이렇게 나눴어요' 제목, [이대로 그림 고르기] 뒤에도 초점이 body로 빠지지 않는다", async ({ page }) => {
  await mockEditor(page, { preview: { ...PREVIEW, steps: PREVIEW.steps.slice(0, 2) } });
  await loginEmployer(page, "/manager/tasks/new");
  await page.getByLabel("어떤 일을 시킬까요?").fill(INPUT);
  await page.getByRole("button", { name: "단계로 나누기" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: /이렇게 나눴어요/ })).toBeFocused();

  await page.getByRole("button", { name: "이대로 그림 고르기" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("task-editor")).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.activeElement === document.body)).toBe(false);
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => document.activeElement?.tagName)).not.toBe("BODY");
});

test("390px 편집기: 긴 문장은 잘리지 않고 가로로 넘치지 않는다", async ({ page }) => {
  const long = {
    ...PREVIEW,
    steps: [
      { order: 1, sentence: "컵을 건조대에 올려 두고 물기가 마르면 선반 위 칸에 차례로 넣어요.", action_type: "move",
        symbol_query: ["컵"], split_group: null, split_check: false, source_text: null },
      { order: 2, sentence: "손을 씻어요.", action_type: "clean", symbol_query: ["손"],
        split_group: null, split_check: false, source_text: null },
    ],
  };
  await page.setViewportSize({ width: 390, height: 844 });
  await mockEditor(page, { preview: long });
  await loginEmployer(page, "/manager/tasks/new");
  await splitInput(page);
  await page.getByRole("button", { name: "이대로 그림 고르기" }).click();
  await expect(page.getByTestId("task-editor")).toBeVisible();
  await page.getByTestId("step-row-1").getByRole("button").first().click();
  await expect(page.getByRole("heading", { name: /1단계 고치기/ })).toBeVisible();

  const field = page.getByTestId("step-detail").getByLabel("문장", { exact: true });
  await expect(field).toHaveValue(long.steps[0].sentence);
  const fit = await field.evaluate((el) => ({ sh: el.scrollHeight, ch: el.clientHeight, w: el.clientWidth }));
  expect(fit.sh, "문장 칸이 글을 자르지 않는다").toBeLessThanOrEqual(fit.ch + 1);
  expect(fit.w, "문장 칸이 좁은 화면 폭을 거의 다 쓴다").toBeGreaterThan(250);
  const scroll = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scroll).toBeLessThanOrEqual(390);
  if (process.env.E2E_SHOTS_DIR) {
    await page.screenshot({ path: `${process.env.E2E_SHOTS_DIR}/editor-390.png`, fullPage: true });
  }
});
