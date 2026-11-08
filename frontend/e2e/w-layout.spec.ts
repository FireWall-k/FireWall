import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { loginAsWorker, mockWorkerBackend, newState, pairedDevice, type MockState } from "./w-mock";

// 1차 검증에서 찾은 배치·흐름 문제의 회귀 방지. 실제 브라우저 배치로 잰다(API는 w-mock.ts 가짜 백엔드).

let state: MockState;

test.beforeEach(async ({ page }) => {
  state = newState();
  await mockWorkerBackend(page, state);
});

const SMALL = [
  ["360×640", { width: 360, height: 640 }],
  ["360×560", { width: 360, height: 560 }],
  ["844×390", { width: 844, height: 390 }],
  ["390×740", { width: 390, height: 740 }],
] as const;

async function expectAllKeysVisible(page: Page, label: string) {
  const inner = await page.evaluate(() => window.innerHeight);
  const keys = page.getByTestId("keypad").locator("button");
  await expect(keys).toHaveCount(12);
  for (let i = 0; i < 12; i++) {
    const box = (await keys.nth(i).boundingBox())!;
    const name = (await keys.nth(i).innerText()).trim();
    expect(box.y, `${label}: '${name}' 위끝`).toBeGreaterThanOrEqual(0);
    expect(box.y + box.height, `${label}: '${name}' 아래끝 ${box.y + box.height} > ${inner}`).toBeLessThanOrEqual(inner + 0.5);
    expect(box.height, `${label}: '${name}' 높이`).toBeGreaterThanOrEqual(63.5);
  }
}

test.describe("번호 넣기: 작은·가로 휴대폰에서도 키패드 4줄이 다 보인다", () => {
  for (const [name, vp] of SMALL) {
    test(name, async ({ page }) => {
      await pairedDevice(page);
      await page.setViewportSize(vp);
      await page.goto("/w");
      await page.getByTestId("keypad").waitFor();
      await expectAllKeysVisible(page, `${name} 처음`);
      // 틀린 번호 세 번 → 안내가 세 줄로 늘어도 키패드는 그대로 보인다.
      for (let k = 0; k < 3; k++) {
        for (const d of ["1", "2", "3", "5"]) await page.getByRole("button", { name: d, exact: true }).click();
        await expect.poll(() => state.loginAttempts.length).toBe(k + 1);
        await page.getByTestId("login-notice").waitFor();
      }
      await expect(page.getByTestId("login-notice")).toContainText("선생님께 번호를 물어봐요.");
      await expectAllKeysVisible(page, `${name} 세 번 틀림`);
      // 안내가 떠 있어도 0이 들어간 번호를 스크롤 없이 끝까지 누를 수 있다.
      for (const d of ["1", "2", "3", "0"]) await page.getByRole("button", { name: d, exact: true }).click();
      await expect.poll(() => state.loginAttempts.at(-1)).toBe("1230");
    });
  }
});

/** 가운데 칸(main)의 첫 내용이 위로 잘려 스크롤로도 못 보는 일이 없는지(justify-content: safe center). */
async function expectNotClippedTop(page: Page, label: string) {
  const r = await page.getByTestId("worker-main").evaluate((m) => {
    m.scrollTop = 0;
    const first = m.firstElementChild as HTMLElement;
    return { mainTop: m.getBoundingClientRect().top, firstTop: first.getBoundingClientRect().top };
  });
  expect(r.firstTop, `${label}: 첫 내용 위끝 ${r.firstTop} < 가운데 칸 위끝 ${r.mainTop}`).toBeGreaterThanOrEqual(r.mainTop - 0.5);
}

test.describe("완료 화면: '정말 잘했어요'가 맨 위·가장 크게·근로자 초록", () => {
  test("다음 일이 있을 때와 모두 끝났을 때 둘 다", async ({ page }) => {
    await loginAsWorker(page);
    await page.goto("/w/job/asg-2/done");
    const praise = page.getByTestId("done-praise");
    await expect(praise).toHaveText("정말 잘했어요");
    const st = await praise.evaluate((el) => {
      const cs = getComputedStyle(el);
      const status = el.closest("[role=status]")!;
      return { fs: parseFloat(cs.fontSize), fw: Number(cs.fontWeight), color: cs.color, first: status.firstElementChild === el };
    });
    // 근로자 초록 중 진한 pressed(#1E4D33): 바탕 #FFF8EC에서 7:1 넘게(2차 검증: primary는 6.82:1).
    expect(st).toMatchObject({ fs: 32, first: true, color: "rgb(30, 77, 51)" });
    expect(st.fw).toBeGreaterThanOrEqual(700);
    const title = page.getByRole("heading", { level: 1 });
    await expect(title).toHaveText("매장 바닥 청소를 다 했어요");
    expect(await title.evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeLessThan(32);

    for (const j of state.jobs) {
      j.done_step_ids = j.steps.map((s) => s.id);
      j.status = "done";
    }
    await page.reload();
    await expect(page.getByTestId("done-praise")).toHaveText("정말 잘했어요");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("오늘 일을 다 했어요");
  });

  for (const [name, vp] of [["360×560", { width: 360, height: 560 }], ["844×390", { width: 844, height: 390 }]] as const) {
    test(`${name}: 위가 잘리지 않는다(완료·시작 화면)`, async ({ page }) => {
      await loginAsWorker(page);
      await page.setViewportSize(vp);
      await page.goto("/w/job/asg-2/done");
      await page.getByTestId("job-done-screen").waitFor();
      await expectNotClippedTop(page, `${name} 완료`);
      await page.goto("/w/job/asg-1");
      await page.getByTestId("job-start-screen").waitFor();
      await expectNotClippedTop(page, `${name} 시작`);
      // 대표 그림은 정사각형(가로 휴대폰에서 300×156 빈 띠가 생기던 문제).
      const box = (await page.getByTestId("job-start-screen").locator("img").first().boundingBox())!;
      expect(Math.abs(box.width - box.height), `${name}: 대표 그림 ${box.width}×${box.height}`).toBeLessThanOrEqual(1);
    });
  }
});

test("가로 휴대폰 844×390: 긴 문장 + 도움 띠에서도 문장 글자는 24px 이상", async ({ page }) => {
  await loginAsWorker(page);
  await page.setViewportSize({ width: 844, height: 390 });
  await page.goto("/w/job/asg-1/step/3");
  const sentence = page.getByTestId("step-sentence");
  await expect(sentence).toBeVisible();
  const fs = () => sentence.evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
  expect(await fs()).toBeGreaterThanOrEqual(24);
  await page.getByTestId("help-button").click();
  await expect(page.getByTestId("help-band")).toContainText("선생님을 불렀어요");
  await page.waitForTimeout(300);
  expect(await fs()).toBeGreaterThanOrEqual(24);
  // 문장 칸이 넘치면 따로 스크롤되고, 아래가 흐려져 "더 있다"를 보인다.
  const cap = page.getByTestId("step-caption");
  const over = await cap.evaluate((el) => el.scrollHeight > el.clientHeight + 1);
  if (over) await expect(cap).toHaveAttribute("data-more", "true");
});

test("도움 띠 [취소]는 소리 [멈춤]과 다른 그림을 쓴다", async ({ page }) => {
  await loginAsWorker(page);
  await page.goto("/w/job/asg-1/step/1");
  await page.getByTestId("help-button").click();
  const cancel = page.getByTestId("help-band").getByRole("button", { name: "취소" });
  await expect(cancel).toBeVisible();
  const icon = await cancel.locator("svg").first().getAttribute("class");
  expect(icon).toContain("lucide-undo");
  expect(icon).not.toContain("lucide-square");
});

test("옛 주소 /worker(·/worker/아무거나)는 새 근로자 화면으로 간다", async ({ page }) => {
  await loginAsWorker(page);
  await page.goto("/worker");
  await expect(page).toHaveURL(/\/w\/today$/);
  await page.goto("/worker/t1");
  await expect(page).toHaveURL(/\/w\/today$/);
  await expect(page.getByTestId("today-screen")).toBeVisible();
});

test("보낸 뒤 인터넷이 끊긴 채 새로고침해도, 보낸 단계는 다 한 것으로 남는다", async ({ page }) => {
  await loginAsWorker(page);
  await page.goto("/w/today");
  await page.getByTestId("today-screen").waitFor();
  // 오늘 할 일을 받아 둔 뒤(기기 저장본: 아직 안 함) 서버에 기록을 보낸다.
  await page.goto("/w/job/asg-2/step/1");
  await page.getByRole("button", { name: "다 했어요" }).click();
  await expect(page.getByTestId("job-done-screen")).toBeVisible();
  await expect.poll(() => state.logs.length).toBe(1);
  await expect.poll(() => page.evaluate(() => localStorage.getItem("jobcard_outbox_v1:w1"))).toBeNull();
  // 끊긴 채 새로고침: 기기 저장본으로 그린다.
  state.offline = true;
  await page.goto("/w/today");
  await page.getByTestId("today-screen").waitFor();
  const card = page.getByTestId("job-card").filter({ hasText: "매장 바닥 청소" });
  await expect(card).toContainText("다 했어요");
  expect(state.logs).toHaveLength(1);
});

test("두 단계를 보낸 뒤 끊긴 채 새로고침하면, 시작 화면이 3단계부터 이어서 하자고 한다", async ({ page }) => {
  await loginAsWorker(page);
  await page.goto("/w/today");
  await page.getByTestId("today-screen").waitFor();
  await page.goto("/w/job/asg-1/step/1");
  await page.getByRole("button", { name: "다 했어요" }).click();
  await expect(page).toHaveURL(/step\/2$/);
  await page.getByRole("button", { name: "다 했어요" }).click();
  await expect(page).toHaveURL(/step\/3$/);
  await expect.poll(() => state.logs.length).toBe(2);
  await expect.poll(() => page.evaluate(() => localStorage.getItem("jobcard_outbox_v1:w1"))).toBeNull();
  state.offline = true;
  await page.goto("/w/job/asg-1");
  await expect(page.getByTestId("job-start-screen")).toContainText("3단계부터 이어서 해요");
});

test("홈 인사는 360px에서도 말줄임 없이 보인다", async ({ page }) => {
  await loginAsWorker(page);
  await page.setViewportSize({ width: 360, height: 640 });
  await page.goto("/w/today");
  const h1 = page.getByTestId("today-screen").getByRole("heading", { level: 1 }).first();
  await expect(h1).toHaveText("김민수 님, 안녕하세요");
  const cut = await h1.evaluate((el) => el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1);
  expect(cut).toBe(false);
});

test("새 화면 axe: 시작·완료·했던 일에 심각 위반이 없다", async ({ page }) => {
  await loginAsWorker(page);
  for (const url of ["/w/job/asg-1", "/w/job/asg-2/done", "/w/history"]) {
    await page.goto(url);
    await page.waitForTimeout(300);
    const results = await new AxeBuilder({ page }).analyze();
    const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious, `${url}: ${serious.map((v) => v.id).join(", ")}`).toEqual([]);
  }
});

// --- 3차 검증 ---------------------------------------------------------------------------------------------

/** 요소가 화면 안에 다 보이고, 아래 막대(footer) 위끝보다 위에 있는지. */
async function expectAboveBottomBar(page: Page, testId: string, label: string) {
  const r = await page.evaluate((id) => {
    const el = document.querySelector(`[data-testid="${id}"]`)!.getBoundingClientRect();
    const footer = document.querySelector('[data-testid="step-player"] footer')!.getBoundingClientRect();
    return { top: el.top, bottom: el.bottom, footerTop: footer.top, inner: window.innerHeight, inner_w: window.innerWidth, right: el.right };
  }, testId);
  expect(r.top, `${label}: ${testId} 위끝`).toBeGreaterThanOrEqual(0);
  expect(r.bottom, `${label}: ${testId} 아래끝 ${r.bottom} > 아래 막대 ${r.footerTop}`).toBeLessThanOrEqual(r.footerTop + 0.5);
  expect(r.right, `${label}: ${testId} 오른쪽 넘침`).toBeLessThanOrEqual(r.inner_w + 0.5);
}

const LANDSCAPE_PHONES = [
  ["640×360", { width: 640, height: 360 }],
  ["667×375", { width: 667, height: 375 }],
  ["740×360", { width: 740, height: 360 }],
  ["844×390", { width: 844, height: 390 }],
] as const;

test.describe("가로 휴대폰: 단계 화면은 두 칸, 문장 첫 줄과 [듣기]가 늘 보인다(도움 띠가 떠도)", () => {
  for (const [name, vp] of LANDSCAPE_PHONES) {
    test(name, async ({ page }) => {
      await loginAsWorker(page);
      await page.setViewportSize(vp);
      for (const n of [3, 2]) {
        await page.goto(`/w/job/asg-1/step/${n}`);
        await page.getByTestId("step-sentence").waitFor();
        await page.waitForTimeout(300); // 단계 넘김 움직임(200ms)이 끝난 뒤 잰다
        // 두 칸: 문장은 그림 오른쪽에 있다.
        const pic = (await page.getByTestId("step-picture").boundingBox())!;
        const sen = (await page.getByTestId("step-sentence").boundingBox())!;
        expect(sen.x, `${name} ${n}단계: 문장이 그림 오른쪽`).toBeGreaterThanOrEqual(pic.x + pic.width - 1);
        await expectAboveBottomBar(page, "speak-button", `${name} ${n}단계`);
        // 문장 첫 줄이 문장 칸 안에 보인다.
        const cap = (await page.getByTestId("step-caption").boundingBox())!;
        expect(cap.height, `${name} ${n}단계: 문장 칸 높이`).toBeGreaterThanOrEqual(32);
        const done = (await page.getByRole("button", { name: "다 했어요" }).boundingBox())!;
        expect(done.y + done.height).toBeLessThanOrEqual(vp.height + 0.5);
      }
      // 도움 띠: 진행 점과 [듣기]는 위 띠 가운데로 옮겨 가 늘 다 보이고, 오른쪽 칸은 문장만 쓴다.
      await page.getByTestId("help-button").click();
      await expect(page.getByTestId("help-band")).toContainText("선생님을 불렀어요");
      await page.waitForTimeout(300);
      await expectAboveBottomBar(page, "speak-button", `${name} 도움 띠`);
      await expect(page.getByTestId("top-dots").getByTestId("speak-button")).toBeVisible();
      await expect(page.getByTestId("speak-button")).toHaveCount(1);
      const sp = (await page.getByTestId("speak-button").boundingBox())!;
      expect(sp.height).toBeGreaterThanOrEqual(79.5);
      // [듣기]와 [불렀어요]는 다른 행동이라 24px 넘게 떨어져 있다(명세 8.1).
      const hb = (await page.getByTestId("help-button").boundingBox())!;
      expect(hb.x - (sp.x + sp.width), `${name}: [듣기]~[불렀어요] 간격`).toBeGreaterThanOrEqual(24);
      const cap = (await page.getByTestId("step-caption").boundingBox())!;
      expect(cap.height, `${name} 도움 띠: 문장 칸 높이`).toBeGreaterThanOrEqual(32);
      const band = page.getByTestId("help-band");
      const cancel = (await band.getByRole("button", { name: "취소" }).boundingBox())!;
      const text = (await page.getByTestId("help-band-text").boundingBox())!;
      // 결정 8: 문장과 [취소]는 한 줄(문장 왼쪽, 버튼 오른쪽).
      expect(cancel.x).toBeGreaterThan(text.x + text.width - 1);
    });
  }
});

test("가로 휴대폰 홈: 강조된 다음 카드의 '시작하기'와 두 번째 카드가 첫 화면에 보인다", async ({ page }) => {
  await loginAsWorker(page);
  for (const vp of [{ width: 844, height: 390 }, { width: 640, height: 360 }]) {
    await page.setViewportSize(vp);
    await page.goto("/w/today");
    await page.getByTestId("today-screen").waitFor();
    const footerTop = await page.evaluate(() => document.querySelector('[data-testid="today-screen"] footer')!.getBoundingClientRect().top);
    const cards = page.getByTestId("job-card");
    await expect(cards).toHaveCount(2);
    for (let i = 0; i < 2; i++) {
      const b = (await cards.nth(i).boundingBox())!;
      expect(b.y + b.height, `${vp.width}×${vp.height}: ${i + 1}번째 카드 아래끝`).toBeLessThanOrEqual(footerTop + 0.5);
    }
    const start = (await page.getByText("시작하기").boundingBox())!;
    expect(start.y + start.height).toBeLessThanOrEqual(footerTop + 0.5);
  }
});

test("작은 화면에서도 번호 틀림 안내와 도움 띠 글씨는 24px, 문서 제목은 '잡카드'", async ({ page }) => {
  for (const vp of [{ width: 360, height: 640 }, { width: 844, height: 390 }]) {
    state = newState();
    await mockWorkerBackend(page, state);
    await pairedDevice(page);
    await page.setViewportSize(vp);
    await page.goto("/w");
    await page.getByTestId("keypad").waitFor();
    expect(await page.title()).toBe("잡카드");
    for (const d of ["1", "2", "3", "5"]) await page.getByRole("button", { name: d, exact: true }).click();
    const notice = page.getByTestId("login-notice");
    await notice.waitFor();
    const fs = await notice.locator("p").first().evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    expect(fs, `${vp.width}: 번호 틀림 글씨`).toBe(24);
    await expectAllKeysVisible(page, `${vp.width}×${vp.height} 틀림 24px`);
  }
  await loginAsWorker(page);
  await page.setViewportSize({ width: 360, height: 640 });
  await page.goto("/w/job/asg-1/step/1");
  await page.getByTestId("help-button").click();
  const fs = await page.getByTestId("help-band-text").evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
  expect(fs).toBe(24);
  expect(await page.title()).toBe("잡카드");
});
