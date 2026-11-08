import { test, expect, type Page, type Route } from "@playwright/test";

// 근로자 단계 화면 배치 회귀 방지(2026-11 UI 진단).
// 진단 때 휴대폰(390×844)에서 그림이 화면의 4분의 1(190px)뿐이었고, "✓ 완료"가 첫 화면 밖(스크롤 아래)이었다.
// 문장은 "접 / 으세요"처럼 낱말 중간에서 끊겼고, 진행 표시가 두 벌("오늘 할 일 2개 중 1번째"·"1 / 4"),
// 상자를 접는 그림 밑에 "담기" 꼬리표가 붙었다. jsdom은 레이아웃을 계산하지 않으므로 실제 브라우저로 잰다.

const PHONE = { width: 390, height: 844 };
const TABLET = { width: 820, height: 1180 };
// 그림이 화면의 주인공이어야 한다 — 휴대폰 가로의 60% 이상(수정 전 49%).
const MIN_PICTURE_RATIO = 0.6;
// 긴 문장이라도 그림이 이보다 작아지지는 않는다(StepCard의 min-h-40).
const MIN_PICTURE_PX = 160;

const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

function step(id: string, order: number, sentence: string, action_type: string, withImage = true) {
  return {
    id, order, sentence, action_type,
    symbol_url: withImage ? `http://e2e-api.invalid/media/symbols/${id}.png` : null,
    symbol_source: withImage ? "aac" : "fallback",
    needs_fallback: !withImage,
    tts_audio_url: null,
  };
}

const LONG = "포장된 상자를 카트에 놓으세요. 큰 상자는 아래쪽에, 작은 상자는 위쪽에 놓으세요";

const TODAY = [
  {
    assignment_id: "asg-1", task_id: "task-1", task_title: "택배 상자 포장",
    steps: [
      // 저장된 계열이 pack이어도 근로자에게는 문장의 동사("접기")가 보여야 한다.
      step("s1", 1, "박스 바닥 덮개를 접으세요", "pack"),
      // 사전에 없는 동사 — 저장된 계열(observe)이 있어도 꼬리표를 숨긴다.
      step("s2", 2, "손님께 인사하세요", "observe"),
      step("s3", 3, LONG, "move"),
    ],
  },
  {
    assignment_id: "asg-2", task_id: "task-2", task_title: "매장 바닥 청소",
    steps: [step("c1", 1, "밀대로 바닥을 닦으세요", "clean")],
  },
];

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET,POST,PATCH,DELETE,OPTIONS",
};

async function mockBackend(page: Page) {
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
    if (url.pathname === "/api/worker/me/history") return json([]);
    if (url.pathname === "/api/performance-logs") return json({ ok: true });
    return route.fulfill({ status: 599, headers: CORS, body: `unmocked ${req.method()} ${url.pathname}` });
  });
  await page.addInitScript(() => {
    localStorage.setItem("jobcard_token", "e2e-worker-token");
    localStorage.setItem("jobcard_role", "worker");
    localStorage.setItem("jobcard_name", "테스트근로자");
  });
}

const done = (page: Page) => page.getByRole("button", { name: "✓ 완료" });

// 스크롤하지 않은 첫 화면에 요소가 통째로 들어와 있는가.
async function expectInFirstScreen(page: Page, name: string, locator: ReturnType<Page["locator"]>) {
  const box = await locator.boundingBox();
  const vp = page.viewportSize()!;
  expect(box, `${name} 위치를 잴 수 없음`).not.toBeNull();
  expect(await page.evaluate(() => window.scrollY), "화면이 스크롤된 상태에서 재면 안 된다").toBe(0);
  expect(box!.y, `${name} 위쪽이 화면 밖`).toBeGreaterThanOrEqual(0);
  expect(box!.y + box!.height, `${name} 아래쪽 ${Math.round(box!.y + box!.height)}px > 화면 ${vp.height}px`)
    .toBeLessThanOrEqual(vp.height);
}

async function pictureBox(page: Page) {
  const box = await page.getByTestId("step-picture").locator("img, div").first().boundingBox();
  expect(box).not.toBeNull();
  return box!;
}

async function expectStepScreenFits(page: Page, sentence: string, minRatio: number | null) {
  const vp = page.viewportSize()!;
  await expectInFirstScreen(page, "그림", page.getByTestId("step-picture"));
  await expectInFirstScreen(page, "문장", page.getByText(sentence));
  await expectInFirstScreen(page, "다시 듣기", page.getByRole("button", { name: /다시 듣기/ }));
  await expectInFirstScreen(page, "완료", done(page));
  const pic = await pictureBox(page);
  expect(Math.abs(pic.width - pic.height), "그림은 정사각형").toBeLessThanOrEqual(1);
  expect(pic.width).toBeGreaterThanOrEqual(MIN_PICTURE_PX);
  if (minRatio != null) {
    expect(pic.width / vp.width, `그림 ${Math.round(pic.width)}px = 화면 가로의 ${Math.round(pic.width / vp.width * 100)}%`)
      .toBeGreaterThanOrEqual(minRatio);
  }
  // 터치 영역은 줄이지 않는다(Phase 0.4: 80px).
  for (const name of [/다시 듣기/, /도움이 필요해요/, /✓ 완료/]) {
    const b = await page.getByRole("button", { name }).boundingBox();
    expect(b!.height).toBeGreaterThanOrEqual(80);
  }
}

test.beforeEach(async ({ page }) => {
  await mockBackend(page);
});

for (const [label, viewport] of [["휴대폰 390×844", PHONE], ["태블릿 820×1180", TABLET]] as const) {
  test.describe(label, () => {
    test.use({ viewport });

    test("그림·문장·다시 듣기·완료가 스크롤 없이 한 화면에 보이고 그림이 가장 크다", async ({ page }) => {
      await page.goto("/worker");
      await expect(page.getByText("박스 바닥 덮개를 접으세요")).toBeVisible();
      await expectStepScreenFits(page, "박스 바닥 덮개를 접으세요", MIN_PICTURE_RATIO);
    });

    test("긴 문장도 그림을 줄여 한 화면에 들어간다", async ({ page }) => {
      await page.goto("/worker");
      await done(page).click();
      await done(page).click();
      await expect(page.getByText(LONG)).toBeVisible();
      await page.evaluate(() => window.scrollTo(0, 0));
      await expectStepScreenFits(page, LONG, null);
    });
  });
}

test.describe("휴대폰 390×844 표시 규칙", () => {
  test.use({ viewport: PHONE });

  test("한국어는 낱말 단위로 줄바꿈한다(keep-all) — 문장·제목·버튼 모두", async ({ page }) => {
    await page.goto("/worker");
    const sentence = page.getByText("박스 바닥 덮개를 접으세요");
    await expect(sentence).toBeVisible();
    const targets = [
      sentence,
      page.getByTestId("step-progress").getByRole("heading"),
      done(page),
      page.getByRole("button", { name: /도움이 필요해요/ }),
      page.getByRole("heading", { name: /오늘 할 일/ }),
    ];
    for (const t of targets) {
      const wb = await t.evaluate((el) => getComputedStyle(el).wordBreak);
      expect(wb).toBe("keep-all");
    }
    // 아주 긴 낱말이 화면을 넘지 않게 하는 짝(overflow-wrap:anywhere)도 붙어 있다.
    expect(await sentence.evaluate((el) => getComputedStyle(el).overflowWrap)).toBe("anywhere");
    // 실제로 "접 / 으세요"처럼 낱말이 쪼개지지 않았는지: 각 줄이 공백 경계에서 끝나는지 글자 위치로 확인한다.
    const brokenInsideWord = await sentence.evaluate((el) => {
      const text = el.firstChild as Text;
      const range = document.createRange();
      let prevTop: number | null = null;
      for (let i = 0; i < text.length; i++) {
        range.setStart(text, i);
        range.setEnd(text, i + 1);
        const r = range.getClientRects()[0];
        if (!r) continue;
        if (prevTop != null && r.top > prevTop + 1) {
          // 새 줄의 첫 글자 바로 앞 글자는 공백이어야 한다(낱말 경계).
          if (text.data[i - 1] !== " ") return text.data.slice(Math.max(0, i - 3), i + 3);
        }
        prevTop = r.top;
      }
      return null;
    });
    expect(brokenInsideWord, `낱말 중간 줄바꿈: ${brokenInsideWord}`).toBeNull();
  });

  test("진행 표시는 하나다 — 이 일의 단계 막대와 '1 / 3', '몇 번째 일'은 단계 화면에 없다", async ({ page }) => {
    await page.goto("/worker");
    await expect(page.getByText("박스 바닥 덮개를 접으세요")).toBeVisible();
    await expect(page.getByTestId("step-progress")).toHaveCount(1);
    await expect(page.getByRole("progressbar")).toHaveCount(1);
    await expect(page.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "1");
    await expect(page.getByTestId("step-progress")).toContainText("1 / 3");
    await expect(page.getByText(/번째/)).toHaveCount(0);
  });

  test("동작 꼬리표: 문장의 동사를 보여 주고, 확실하지 않으면 숨긴다", async ({ page }) => {
    await page.goto("/worker");
    await expect(page.getByText("박스 바닥 덮개를 접으세요")).toBeVisible();
    await expect(page.getByTestId("action-chip")).toHaveText("접기");
    await expect(page.getByText("담기")).toHaveCount(0);

    await done(page).click();
    await expect(page.getByText("손님께 인사하세요")).toBeVisible();
    await expect(page.getByTestId("action-chip")).toHaveCount(0);
    await expect(page.getByText("확인하기")).toHaveCount(0);
  });

  test("몇 번째 일인지는 직무 사이 화면의 목록에서 보여 준다", async ({ page }) => {
    await page.goto("/worker");
    for (let i = 0; i < 3; i++) await done(page).click();
    await expect(page.getByRole("button", { name: /다음 일 시작하기/ })).toBeVisible();
    await expect(page.getByText("오늘 할 일 2개 중 1개를 마쳤어요.")).toBeVisible();
    const list = page.getByRole("list", { name: "오늘 할 일" });
    await expect(list.getByRole("listitem")).toHaveCount(2);
  });
});
