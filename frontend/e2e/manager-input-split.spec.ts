import { test, expect, type Page, type Route } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// 입력 화면에서 나누기를 끝내는 흐름(한 줄 = 한 동작 = 그림 1장)을 실제 브라우저로 본다:
//   [단계로 나누기] → 나눈 줄이 입력칸 아래에 → 노란 줄 [합치기]·[더 나누기]·고치기 → [이대로 그림 고르기] →
//   확인한 줄로 초안 생성 → 편집기(나누기 알림 없음).
// 백엔드는 띄우지 않고 page.route로 목을 둔다(worker-a11y.spec.ts와 같은 방식). 실제 백엔드 경로는
// backend/tests/test_input_split.py가 확인한다.
// E2E_SHOTS_DIR을 주면 1280px·390px 화면 사진을 그 폴더에 남긴다(디자인 확인용).

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET,POST,PATCH,DELETE,OPTIONS",
};
const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);
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

async function mockBackend(page: Page, opts: { preview?: typeof PREVIEW; createFails?: boolean } = {}) {
  const state = { createBodies: [] as { steps: { sentence: string }[] }[], previewCalls: 0 };
  await page.route("https://cdn.jsdelivr.net/**", (route) => route.abort());
  await page.route("http://e2e-api.invalid/**", async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    const method = req.method();
    if (method === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, headers: { ...CORS, "content-type": "application/json" }, body: JSON.stringify(body) });
    if (url.pathname.startsWith("/media/")) {
      return route.fulfill({ status: 200, headers: { ...CORS, "content-type": "image/png" }, body: PNG_1X1 });
    }
    if (url.pathname === "/api/workers" && method === "GET") return json([]);
    if (url.pathname === "/api/tasks/split-preview" && method === "POST") {
      state.previewCalls += 1;
      return json(opts.preview ?? PREVIEW);
    }
    if (url.pathname === "/api/tasks" && method === "POST") {
      const body = req.postDataJSON() as { steps: { sentence: string }[] };
      state.createBodies.push(body);
      if (opts.createFails) return json({ detail: "초안을 만들지 못했어요. 잠시 뒤 다시 눌러 주세요." }, 502);
      return json({
        id: "task-1", title: "출근 준비", status: "draft",
        steps: body.steps.map((s, i) => ({
          id: `s${i + 1}`, order: i + 1, sentence: s.sentence, action_type: "other",
          symbol_url: `http://e2e-api.invalid/media/symbols/s${i + 1}.png`, symbol_source: "LOCAL_AAC",
          needs_fallback: false, tts_audio_url: null,
        })),
      }, 201);
    }
    return route.fulfill({ status: 599, headers: CORS, body: `unmocked ${method} ${url.pathname}` });
  });
  return state;
}

async function loginEmployer(page: Page) {
  await page.goto("/");
  await page.evaluate(() => {
    localStorage.setItem("jobcard_token", "e2e-employer-token");
    localStorage.setItem("jobcard_role", "employer");
    localStorage.setItem("jobcard_name", "테스트사장");
  });
  await page.goto("/manager");
}

async function splitInput(page: Page) {
  await page.getByLabel("직무 내용").fill(INPUT);
  await page.getByRole("button", { name: "단계로 나누기" }).click();
  await expect(page.getByRole("heading", { name: /이렇게 나눴어요/ })).toBeVisible();
}

test("입력 화면: 나눈 줄 확인 → 합치기 → 고치기 → 이대로 그림 고르기", async ({ page }) => {
  const state = await mockBackend(page);
  await loginEmployer(page);
  await splitInput(page);

  // 애매한 줄만 노랗다
  await expect(page.getByTestId("split-row-3")).toHaveAttribute("data-check", "true");
  await expect(page.getByTestId("split-row-1")).toHaveAttribute("data-check", "false");
  await expect(page.getByTestId("split-row-3")).toContainText(SOURCE);

  // 사업주 화면 버튼은 44px 이상
  const heights = await page.locator('[aria-labelledby="split-preview-title"] button').evaluateAll((els) =>
    els.map((el) => ({ name: el.getAttribute("aria-label") ?? el.textContent, h: el.getBoundingClientRect().height })));
  for (const b of heights) expect(b.h, `${b.name} 높이`).toBeGreaterThanOrEqual(44);

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
  await page.getByRole("button", { name: "이대로 그림 고르기 ›" }).click();

  await expect(page.getByRole("heading", { name: /검토 · 수정/ })).toBeVisible();
  expect(state.previewCalls).toBe(1);
  expect(state.createBodies).toHaveLength(1);
  expect(state.createBodies[0].steps.map((s) => s.sentence)).toEqual([
    "앞치마를 입어요.", "손을 비누로 씻어요.", SOURCE,
  ]);
  // 편집기에는 나누기 알림이 없다
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
  await mockBackend(page, { preview: many, createFails: true });
  await loginEmployer(page);
  await splitInput(page);
  const confirm = page.getByRole("button", { name: "이대로 그림 고르기 ›" });
  await confirm.scrollIntoViewIfNeeded();
  await confirm.click();
  const alert = page.locator('[aria-labelledby="split-preview-title"]').getByRole("alert");
  await expect(alert).toContainText("초안을 만들지 못했어요");
  await expect(alert).toBeInViewport();
  // 목록은 그대로 남아 다시 누를 수 있다
  await expect(page.getByLabel("9단계 문장")).toHaveValue("9번째 일을 천천히 해요.");
});
