import { test, expect, type Page, type Route } from "@playwright/test";

// 근로자 단계 화면 배치 회귀 방지(2026-11 UI 진단).
// 진단 때 휴대폰(390×844)에서 그림이 화면의 4분의 1(190px)뿐이었고, "✓ 완료"가 첫 화면 밖(스크롤 아래)이었다.
// 문장은 "접 / 으세요"처럼 낱말 중간에서 끊겼고, 진행 표시가 두 벌("오늘 할 일 2개 중 1번째"·"1 / 4"),
// 상자를 접는 그림 밑에 "담기" 꼬리표가 붙었다. jsdom은 레이아웃을 계산하지 않으므로 실제 브라우저로 잰다.

const PHONE = { width: 390, height: 844 };
const TABLET = { width: 820, height: 1180 };
// 그림이 화면의 주인공이어야 한다 — 휴대폰 가로의 60% 이상(수정 전 49%).
const MIN_PICTURE_RATIO = 0.6;
// 긴 문장이라도 그림이 이보다 작아지지는 않는다(맞추기 3단계의 그림 바닥 min(8rem, 15dvh)) — rem 기준이라 글자를
// 키우면 같이 커진다. 작은 휴대폰(667px)에서는 100px.
const minPicturePx = (vpHeight: number, rootPx = 16) => Math.min(8 * rootPx, 0.15 * vpHeight) - 1;
// 작은 휴대폰(2차 검증): 390×844만 맞추면 360×740·375×667(아이폰 SE)에서는 "완료"가 화면 밖이었다.
const SMALL_PHONES = [
  ["360×740", { width: 360, height: 740 }],
  ["360×800", { width: 360, height: 800 }],
  ["375×667", { width: 375, height: 667 }],
] as const;

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
// 100자가 넘는 문장 — 작은 화면·큰 글자에서는 한 화면에 넣지 못하고 스크롤한다(맞추기 4단계).
const VERY_LONG = LONG + ". 상자가 넘어지지 않게 끈으로 묶고 카트를 천천히 밀어서 창고 앞까지 가져가세요";

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

// 직무 사이 화면 검사용: 오늘 할 일이 5개(3차 검증 — 목록이 "다음 일 시작하기"를 첫 화면 밖으로 밀었다).
const FIVE_TASKS = [
  { ...TODAY[0], steps: [step("s1", 1, "박스 바닥 덮개를 접으세요", "pack")] },
  ...["매장 바닥 청소", "진열대 물건 채우기", "분리수거 하기", "창고 재고 세기"].map((title, i) => ({
    assignment_id: `asg-${i + 2}`, task_id: `task-${i + 2}`, task_title: title,
    steps: [step(`t${i}`, 1, "밀대로 바닥을 닦으세요", "clean")],
  })),
];

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET,POST,PATCH,DELETE,OPTIONS",
};

async function mockBackend(page: Page, today: unknown = TODAY) {
  await page.unrouteAll({ behavior: "ignoreErrors" });
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
    if (url.pathname === "/api/worker/me/today") return json(today);
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
  const rootPx = await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize));
  expect(Math.abs(pic.width - pic.height), "그림은 정사각형").toBeLessThanOrEqual(1);
  expect(pic.width).toBeGreaterThanOrEqual(minPicturePx(vp.height, rootPx));
  // 문장은 근로자 글씨 크기(text-worker = 1.5rem, 기본 24px) 아래로 줄이지 않는다(Phase 0.4 큰 글씨).
  const size = await page.getByText(sentence).evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
  expect(size, `문장 글씨 ${size}px`).toBeGreaterThanOrEqual(1.5 * rootPx);
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

// 낱말 중간에서 줄이 바뀐 곳(앞뒤가 모두 글자인데 줄이 바뀜). 없으면 null.
async function brokenInsideWord(locator: ReturnType<Page["locator"]>) {
  return locator.evaluate((root) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let prevTop: number | null = null;
    let prevCh = "";
    let node: Node | null;
    while ((node = walker.nextNode())) {
      const text = node as Text;
      // <wbr>은 일부러 둔 줄바꿈 자리다("요청<wbr>했어요" → "요청 / 했어요").
      if (text.previousSibling?.nodeName === "WBR") prevTop = null;
      for (let i = 0; i < text.length; i++) {
        const range = document.createRange();
        range.setStart(text, i);
        range.setEnd(text, i + 1);
        const r = range.getClientRects()[0];
        const ch = text.data[i];
        if (!r) { prevCh = ch; continue; }
        if (prevTop != null && r.top > prevTop + 4 && /[가-힣]/.test(prevCh) && /[가-힣]/.test(ch)) {
          return text.data.slice(Math.max(0, i - 3), i) + "|" + text.data.slice(i, i + 3);
        }
        prevTop = r.top;
        prevCh = ch;
      }
    }
    return null;
  });
}

// 글자 크기를 125%로 키운 휴대폰(접근성 설정). 처음부터 큰 글씨로 그려지게 문서 시작 때 건다.
// 주의: init 스크립트가 도는 시점에는 document.documentElement가 아직 없다(null). 예전에는 여기서 바로 스타일을
// 걸어 아무 효과가 없었고, "글자 크기 125%" 테스트는 실제로는 16px로 돌았다. <html>이 생기는 순간 건다.
async function useLargeRootFont(page: Page) {
  await page.addInitScript(() => {
    const apply = () => {
      if (!document.documentElement) return false;
      document.documentElement.style.fontSize = "125%";
      return true;
    };
    if (!apply()) {
      const mo = new MutationObserver(() => { if (apply()) mo.disconnect(); });
      mo.observe(document, { childList: true });
    }
  });
}

async function expectRootFont(page: Page, px: number) {
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).fontSize)).toBe(`${px}px`);
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

  test("오늘 일을 모두 마치면 '지난 일 보기'가 첫 화면에 보인다", async ({ page }) => {
    await page.goto("/worker");
    for (let i = 0; i < 3; i++) await done(page).click();
    await page.getByRole("button", { name: /다음 일 시작하기/ }).click();
    await done(page).click();
    await expect(page.getByText("오늘 일을 모두 마쳤어요!")).toBeVisible();
    await expectInFirstScreen(page, "지난 일 보기", page.getByRole("button", { name: "지난 일 보기" }));
  });
});

// 직무 사이 화면(3차 검증): 오늘 할 일 목록이 "다음 일 시작하기" 위에 있어, 할 일이 4~5개이거나 글자를 키운
// 작은 휴대폰에서 유일한 진행 버튼이 첫 화면 밖으로 밀렸다. 버튼은 축하 문구 바로 아래, 목록보다 위에 있다.
for (const [label, viewport, largeFont] of [
  ["360×740", { width: 360, height: 740 }, false],
  ["360×740 · 글자 125%", { width: 360, height: 740 }, true],
  ["390×844 · 글자 125%", PHONE, true],
] as const) {
  test.describe(`직무 사이 화면 ${label} · 오늘 할 일 5개`, () => {
    test.use({ viewport });

    test("'다음 일 시작하기'가 스크롤 없이 첫 화면 안이고 목록보다 위에 있다", async ({ page }) => {
      await mockBackend(page, FIVE_TASKS);
      if (largeFont) await useLargeRootFont(page);
      await page.goto("/worker");
      await done(page).click();
      const next = page.getByRole("button", { name: /다음 일 시작하기/ });
      await expect(next).toBeVisible();
      if (largeFont) await expectRootFont(page, 20);
      await expectInFirstScreen(page, "다음 일 시작하기", next);
      const list = page.getByRole("list", { name: "오늘 할 일" });
      await expect(list.getByRole("listitem")).toHaveCount(5);
      const [btn, ol] = [await next.boundingBox(), await list.boundingBox()];
      expect(btn!.y + btn!.height, "버튼이 목록보다 위").toBeLessThanOrEqual(ol!.y);
      expect(btn!.height).toBeGreaterThanOrEqual(80);
    });
  });
}

for (const [label, viewport] of SMALL_PHONES) {
  test.describe(`작은 휴대폰 ${label}`, () => {
    test.use({ viewport });

    test("보통 문장: 그림·문장·다시 듣기·완료가 스크롤 없이 한 화면에 들어간다", async ({ page }) => {
      await page.goto("/worker");
      await expect(page.getByText("박스 바닥 덮개를 접으세요")).toBeVisible();
      await expectStepScreenFits(page, "박스 바닥 덮개를 접으세요", 0.45);
    });

    test("긴 문장(worker-05)도 한 화면에 들어가고, 문장은 24px 아래로 줄이지 않는다", async ({ page }) => {
      await page.goto("/worker");
      await done(page).click();
      await done(page).click();
      await expect(page.getByText(LONG)).toBeVisible();
      // 글씨 크기 바닥(text-worker 24px)은 expectStepScreenFits가 함께 본다 — 자리는 꼬리표와 그림이 양보한다.
      await expectStepScreenFits(page, LONG, null);
    });

    test("머리글은 한 줄이다(로그아웃은 그대로, 화면 읽기에는 '오늘 할 일'까지 읽힌다)", async ({ page }) => {
      await page.goto("/worker");
      const h1 = page.getByRole("heading", { level: 1 });
      await expect(h1).toHaveAccessibleName(/오늘 할 일/);
      const lines = await h1.evaluate((el) => Math.round(el.getBoundingClientRect().height / parseFloat(getComputedStyle(el).lineHeight)));
      expect(lines).toBe(1);
      await expect(page.getByRole("button", { name: "로그아웃" })).toBeVisible();
    });
  });
}

for (const [label, viewport] of [["휴대폰 390×844", PHONE], ["작은 휴대폰 360×740", { width: 360, height: 740 }]] as const) {
test.describe(`${label} · 글자 크기 125%`, () => {
  test.use({ viewport });

  test("보통 문장·긴 문장·도움 요청 뒤에도 완료가 첫 화면 안이다", async ({ page }) => {
    await useLargeRootFont(page);
    await page.goto("/worker");
    await expect(page.getByText("박스 바닥 덮개를 접으세요")).toBeVisible();
    await expectRootFont(page, 20);
    await expectStepScreenFits(page, "박스 바닥 덮개를 접으세요", null);
    await page.getByRole("button", { name: /도움이 필요해요/ }).click();
    await expect(page.getByRole("button", { name: /요청했어요/ })).toBeVisible();
    await expectInFirstScreen(page, "완료(도움 요청 뒤)", done(page));
    await done(page).click();
    await done(page).click();
    await expect(page.getByText(LONG)).toBeVisible();
    await expectStepScreenFits(page, LONG, null);
  });

  test("누른 도움 버튼 글자가 낱말 중간에서 끊기지 않는다", async ({ page }) => {
    await useLargeRootFont(page);
    await page.goto("/worker");
    await page.getByRole("button", { name: /도움이 필요해요/ }).click();
    const pressed = page.getByRole("button", { name: /요청했어요/ });
    await expect(pressed).toBeVisible();
    expect(await brokenInsideWord(pressed)).toBeNull();
    expect(await brokenInsideWord(page.getByRole("button", { name: /다시 듣기/ }))).toBeNull();
  });

  test("100자가 넘는 문장은 스크롤하되, 그림은 작게 줄이지 않는다", async ({ page }) => {
    await mockBackend(page, [{ ...TODAY[0], steps: [step("v1", 1, VERY_LONG, "move")] }]);
    await useLargeRootFont(page);
    await page.goto("/worker");
    const sentence = page.getByText(VERY_LONG);
    await expect(sentence).toBeVisible();
    await expectRootFont(page, 20);
    // 한 화면에 넣기를 포기한 단계(4)에서는 그림 바닥을 처음 크기 min(10rem, 20dvh)로 되돌린다.
    await expect(sentence).toHaveAttribute("data-fit", "4");
    const pic = await pictureBox(page);
    expect(pic.width).toBeGreaterThanOrEqual(Math.min(200, 0.2 * viewport.height) - 1);
    expect(parseFloat(await sentence.evaluate((el) => getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(30);
    await expect(page.getByTestId("action-chip")).toHaveCount(0); // 놓기 앞에 '묶고'·'밀어서' — 동작이 여럿
    await done(page).scrollIntoViewIfNeeded();
    await expect(done(page)).toBeInViewport();
  });
});
}

test.describe("좁은 화면 312×675(휴대폰 125% 확대와 같은 폭)", () => {
  test.use({ viewport: { width: 312, height: 675 } });

  // 3차 검증: 쌓으면 버튼 한 개만큼 그림 자리를 잃어 긴 문장에서 "완료"가 화면 밖(731/675)이었다. 지금은 반쪽에
  // 나란히 두고, 글자는 낱말 경계("다시 / 듣기")나 말의 마디("요청 / 했어요", <wbr>)에서만 넘긴다.
  test("다시 듣기·도움 버튼은 나란히 두고 낱말이 쪼개지지 않으며 80px을 지킨다", async ({ page }) => {
    await page.goto("/worker");
    const replay = page.getByRole("button", { name: /다시 듣기/ });
    const help = page.getByRole("button", { name: /도움이 필요해요/ });
    expect(await brokenInsideWord(help)).toBeNull();
    await help.click();
    const pressed = page.getByRole("button", { name: /요청했어요/ });
    expect(await brokenInsideWord(pressed)).toBeNull();
    expect(await brokenInsideWord(replay)).toBeNull();
    const [a, b] = [await replay.boundingBox(), await pressed.boundingBox()];
    expect(Math.abs(a!.y - b!.y), "같은 줄").toBeLessThanOrEqual(1);
    expect(a!.height).toBeGreaterThanOrEqual(80);
    expect(b!.height).toBeGreaterThanOrEqual(80);
    // 그림 글자(🙋)가 혼자 한 줄을 차지해 버튼이 세 줄로 커지지 않는다.
    expect(b!.height).toBeLessThan(110);
  });

  test("긴 문장(worker-05)도 완료가 첫 화면 안이다", async ({ page }) => {
    await page.goto("/worker");
    await done(page).click();
    await done(page).click();
    await expect(page.getByText(LONG)).toBeVisible();
    await expectStepScreenFits(page, LONG, null);
  });
});

// 로그인 화면(3차 검증): 사업주/근로자 탭 36px·로그인 버튼 44px이 48px 터치 기준보다 작았다.
test.describe("로그인 화면 390×844", () => {
  test.use({ viewport: PHONE });

  test("사업주/근로자 탭과 로그인 버튼이 48px 이상이다", async ({ page }) => {
    await page.addInitScript(() => localStorage.clear());
    await page.goto("/");
    for (const name of ["사업주", "근로자", "로그인"]) {
      const box = await page.getByRole("button", { name, exact: true }).boundingBox();
      expect(box!.height, `${name} ${box!.height}px`).toBeGreaterThanOrEqual(48);
    }
  });
});

test.describe("스크롤해 완료를 누른 뒤", () => {
  test.use({ viewport: PHONE });

  test("다음 단계와 직무 완료 화면은 맨 위(제목·진행 막대)부터 보인다", async ({ page }) => {
    await page.goto("/worker");
    await expect(page.getByText("박스 바닥 덮개를 접으세요")).toBeVisible();
    // 맨 아래 "지난 일 보기"까지 내려간 채로 완료를 누른다.
    await page.getByRole("button", { name: "지난 일 보기" }).scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    await done(page).click();
    await expect(page.getByText("손님께 인사하세요")).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
    await expectInFirstScreen(page, "진행 표시", page.getByTestId("step-progress"));

    await done(page).click();
    await page.getByRole("button", { name: "지난 일 보기" }).scrollIntoViewIfNeeded();
    await done(page).click();
    await expect(page.getByRole("button", { name: /다음 일 시작하기/ })).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  });
});

test.describe("가로 태블릿 1024×768", () => {
  test.use({ viewport: { width: 1024, height: 768 } });

  test("그림을 왼쪽에 크게, 버튼을 오른쪽에 두고 한 화면에 들어간다", async ({ page }) => {
    await page.goto("/worker");
    await expect(page.getByText("박스 바닥 덮개를 접으세요")).toBeVisible();
    await expectStepScreenFits(page, "박스 바닥 덮개를 접으세요", 0.4);
    const pic = await pictureBox(page);
    const doneBox = (await done(page).boundingBox())!;
    expect(doneBox.x, "완료는 그림 오른쪽").toBeGreaterThanOrEqual(pic.x + pic.width);
    // 예전(세로로 쌓기)에는 그림이 268px(가로의 26%)이었다.
    expect(pic.height).toBeGreaterThanOrEqual(400);
  });
});
