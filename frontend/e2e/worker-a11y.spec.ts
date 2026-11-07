import { test, expect, type Page, type Route } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// 근로자 화면 접근성 회귀 방지(Phase 0.4).
// 예전에는 min-h-touch·text-worker가 tailwind.config.js에 정의되지 않아 CSS가 생성되지 않았고,
// 그 결과 근로자용 버튼이 글자 높이로 쪼그라들었다(수정 전 실측, Pixel 7 뷰포트: "오늘 할 일"·"지난 일 보기"·
// "✓ 완료" 24px, "🔊 다시 듣기"·"🙋 도움이 필요해요" 28px, 머리글 "로그아웃" 38px). jsdom 단위 테스트는 클래스 이름만 보므로
// 이걸 못 잡았다. 여기서는 실제 브라우저 레이아웃으로 버튼 높이를 재고, axe로 심각한 위반을 막는다.

const TOUCH_MIN_PX = 80;

// 테스트용 1x1 PNG. 상징 그림 자리에 실제 이미지가 뜨는 경로(그림 없음 대체 박스가 아닌)도 검사하려고 쓴다.
const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

function step(id: string, order: number, sentence: string, action_type: string, withImage: boolean) {
  return {
    id, order, sentence, action_type,
    symbol_url: withImage ? `http://e2e-api.invalid/media/symbols/${id}.png` : null,
    symbol_source: withImage ? "aac" : "fallback",
    needs_fallback: !withImage,
    tts_audio_url: null,
  };
}

const TODAY = [
  {
    assignment_id: "asg-1",
    task_id: "task-1",
    task_title: "택배 상자 정리",
    steps: [
      step("s1", 1, "상자를 선반으로 옮기세요", "move", true),
      step("s2", 2, "상자 수량을 확인하세요", "observe", false),
    ],
  },
  {
    assignment_id: "asg-2",
    task_id: "task-2",
    task_title: "매장 바닥 청소",
    steps: [step("s3", 1, "걸레로 바닥을 닦으세요", "clean", true)],
  },
];

const HISTORY = [
  {
    ...TODAY[0],
    assigned_date: "2026-11-06",
    status: "done",
    steps: TODAY[0].steps.map((s) => ({ ...s, completed: true })),
  },
  {
    ...TODAY[1],
    assigned_date: "2026-11-05",
    status: "in_progress",
    steps: TODAY[1].steps.map((s) => ({ ...s, completed: false })),
  },
];

// 프론트는 다른 출처(API_BASE)로 Authorization 헤더를 실어 보내므로 브라우저가 CORS를 검사한다.
// 실제 백엔드처럼 CORS 헤더를 붙여 응답해야 목킹이 브라우저에서 막히지 않는다.
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET,POST,PATCH,DELETE,OPTIONS",
};

async function mockBackend(page: Page) {
  // 외부 웹폰트(CDN)는 CI 네트워크 상태에 따라 느려질 수 있어 막는다 — 폰트는 레이아웃 판정과 무관하다.
  await page.route("https://cdn.jsdelivr.net/**", (route) => route.abort());
  await page.route("http://e2e-api.invalid/**", async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
    const json = (body: unknown) =>
      route.fulfill({ status: 200, headers: { ...CORS, "content-type": "application/json" }, body: JSON.stringify(body) });
    if (url.pathname.startsWith("/media/")) {
      return route.fulfill({ status: 200, headers: { ...CORS, "content-type": "image/png" }, body: PNG_1X1 });
    }
    if (url.pathname === "/api/worker/me/today") return json(TODAY);
    if (url.pathname === "/api/worker/me/history") return json(HISTORY);
    if (url.pathname === "/api/performance-logs") return json({ ok: true });
    // 목킹하지 않은 API를 화면이 부르기 시작하면 조용히 넘어가지 않고 테스트를 실패시킨다.
    return route.fulfill({ status: 599, headers: CORS, body: `unmocked ${req.method()} ${url.pathname}` });
  });
  // 근로자 로그인 상태로 시작한다(로그인 화면은 이 테스트의 대상이 아니다). 키는 src/api.ts와 같다.
  await page.addInitScript(() => {
    localStorage.setItem("jobcard_token", "e2e-worker-token");
    localStorage.setItem("jobcard_role", "worker");
    localStorage.setItem("jobcard_name", "테스트근로자");
  });
}

// 근로자 화면 전체(머리글 포함)의 보이는 상호작용 요소가 모두 80px 이상인지 잰다.
// 예전에는 <main> 안 버튼만 쟀고 머리글 "로그아웃"(38px)을 빼 두었는데, 근로자가 실제로 누르는 버튼이라
// 잘못 누르거나 못 누르면 똑같이 막힌다. 그래서 버튼뿐 아니라 링크·입력·role=button까지 화면 전체를 본다.
const INTERACTIVE = [
  "button", "a[href]", "input:not([type=hidden])", "select", "textarea", "summary",
  "[role=button]", "[role=link]", "[role=tab]", "[tabindex]:not([tabindex='-1'])",
].map((sel) => `${sel}:visible`).join(", ");

async function expectTouchTargets(page: Page) {
  const targets = page.locator(INTERACTIVE);
  const count = await targets.count();
  expect(count, "검사할 요소가 하나도 없으면 화면이 제대로 안 뜬 것").toBeGreaterThan(0);
  // 머리글이 실제로 측정 범위에 들어오는지(로그아웃이 빠지면 예전처럼 <main>만 재는 것과 같다).
  await expect(page.getByRole("button", { name: "로그아웃" })).toBeVisible();
  for (let i = 0; i < count; i++) {
    const el = targets.nth(i);
    const box = await el.boundingBox();
    const label = ((await el.getAttribute("aria-label")) || (await el.innerText())).trim();
    expect(box, `"${label}" 위치를 잴 수 없음`).not.toBeNull();
    expect(box!.height, `"${label}" 높이 ${box!.height}px < ${TOUCH_MIN_PX}px`).toBeGreaterThanOrEqual(TOUCH_MIN_PX);
  }
}

// serious·critical 위반만 실패로 본다 — 발달장애 근로자가 실제로 쓰지 못하게 되는 수준의 문제.
async function expectNoSeriousAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  const summary = serious.map((v) => `${v.id}(${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
  expect(serious, summary.join("\n")).toEqual([]);
}

test.beforeEach(async ({ page }) => {
  await mockBackend(page);
});

test("오늘 할 일: 단계 화면 버튼이 80px 이상이고 axe 심각 위반이 없다", async ({ page }) => {
  await page.goto("/worker");
  await expect(page.getByText("상자를 선반으로 옮기세요")).toBeVisible();
  // 큰 글씨가 실제로 적용됐는지도 본다(text-worker-lg = 32px). 정의가 없으면 기본 16px로 떨어진다.
  const fontSize = await page.getByText("상자를 선반으로 옮기세요").evaluate((el) => getComputedStyle(el).fontSize);
  expect(parseFloat(fontSize)).toBeGreaterThanOrEqual(32);
  await expectTouchTargets(page);
  await expectNoSeriousAxeViolations(page);

  // 그림이 없는 단계(대체 박스)도 같은 기준을 지킨다.
  await page.getByRole("button", { name: "✓ 완료" }).click();
  await expect(page.getByText("상자 수량을 확인하세요")).toBeVisible();
  await expectTouchTargets(page);
  await expectNoSeriousAxeViolations(page);
});

test("오늘 할 일: 직무 완료 화면의 '다음 일 시작하기'도 80px 이상", async ({ page }) => {
  await page.goto("/worker");
  await page.getByRole("button", { name: "✓ 완료" }).click();
  await expect(page.getByText("상자 수량을 확인하세요")).toBeVisible();
  await page.getByRole("button", { name: "✓ 완료" }).click();
  await expect(page.getByRole("button", { name: /다음 일 시작하기/ })).toBeVisible();
  await expectTouchTargets(page);
  await expectNoSeriousAxeViolations(page);
});

test("지난 일 보기: 목록과 상세 화면 버튼이 80px 이상이고 axe 심각 위반이 없다", async ({ page }) => {
  await page.goto("/worker");
  await page.getByRole("button", { name: "지난 일 보기" }).click();
  await expect(page.getByText("매장 바닥 청소")).toBeVisible();
  await expectTouchTargets(page);
  await expectNoSeriousAxeViolations(page);

  await page.getByRole("button", { name: /택배 상자 정리/ }).click();
  await expect(page.getByRole("button", { name: "← 목록으로" })).toBeVisible();
  await expectTouchTargets(page);
  await expectNoSeriousAxeViolations(page);
});
