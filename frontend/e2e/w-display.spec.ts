import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { HC_LEFT, HIGH_CONTRAST, LEFT_HAND, loginAsWorker, mockWorkerBackend, newState, pairedDevice, type MockState } from "./w-mock";

// 3b-1 고대비·왼손 검증(명세 4.12·6.1·8.1). 화면 설정은 /me a11y_prefs로 받는다(w-mock newState(prefs)).
// - 왼손: 아래 막대만 좌우를 바꾼다. 위 띠 [나가기](왼쪽)·[도와주세요](오른쪽)는 제자리.
// - 고대비: 흰 바탕·검정 글자, 모든 버튼 3px 검정 테두리, 주 버튼 #1E4D33, axe 심각 위반 0.
// - 로그인 전 화면(번호 넣기)은 앞 근로자의 설정을 기억하지 않는다(기본 화면).
// - 근로자 버튼은 80px 이상(명세 4.0). 글자 130%에서도 [다 했어요]는 화면 안.

const SIZES = [
  ["360×560", { width: 360, height: 560 }],
  ["390×740", { width: 390, height: 740 }],
  ["844×390", { width: 844, height: 390 }],
] as const;

/** 시스템 글자 130%(html 글자 크기) — w-layout·w-baseline의 bigText와 같다. */
async function bigText(page: Page, pct = 130) {
  await page.addInitScript((p) => {
    const set = () => {
      document.documentElement.style.fontSize = `${p}%`;
    };
    if (document.documentElement) set();
    document.addEventListener("DOMContentLoaded", set);
  }, pct);
}

async function start(page: Page, state: MockState, url: string) {
  await mockWorkerBackend(page, state);
  await loginAsWorker(page);
  await page.goto(url);
}

const box = async (page: Page, name: string, exact = true) =>
  (await page.getByRole("button", { name, exact }).first().boundingBox())!;

async function expectNoSeriousAxe(page: Page, label: string) {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious, `${label}: ${serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`).join("\n")}`).toEqual([]);
}

/** 보이는 근로자 버튼(밑줄 글자 링크·선생님용 링크 제외)의 높이·테두리. */
async function workerButtons(page: Page) {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll("button"))
      .filter((b) => {
        const r = b.getBoundingClientRect();
        const s = getComputedStyle(b);
        return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && !b.hasAttribute("data-teacher-only")
          && s.textDecorationLine !== "underline";
      })
      .map((b) => {
        const s = getComputedStyle(b);
        return {
          label: (b.getAttribute("aria-label") || b.innerText).trim().replace(/\s+/g, " "),
          height: b.getBoundingClientRect().height,
          border: Math.min(...["Top", "Right", "Bottom", "Left"].map((k) => parseFloat(s.getPropertyValue(`border-${k.toLowerCase()}-width`)))),
          color: s.borderTopColor,
          bg: s.backgroundColor,
        };
      }),
  );
}

async function expectHighContrastButtons(page: Page, label: string) {
  const list = await workerButtons(page);
  expect(list.length, `${label}: 버튼`).toBeGreaterThan(0);
  for (const b of list) {
    expect(b.height, `${label}: "${b.label}" 높이 ${b.height}`).toBeGreaterThanOrEqual(80);
    expect(b.border, `${label}: "${b.label}" 테두리 ${b.border}px`).toBeGreaterThanOrEqual(3);
    expect(b.color, `${label}: "${b.label}" 테두리 색`).toBe("rgb(0, 0, 0)");
  }
}

test.describe("왼손: 아래 막대만 뒤집고 위 띠는 제자리", () => {
  for (const [name, vp] of SIZES) {
    for (const big of [false, true]) {
      test(`${name} ${big ? "130%" : "100%"}`, async ({ page }) => {
        if (big) await bigText(page);
        await page.setViewportSize(vp);
        await start(page, newState(LEFT_HAND), "/worker/job/asg-1/step/2");
        await page.getByTestId("step-sentence").waitFor();
        const done = await box(page, "다 했어요");
        const prev = await box(page, "이전");
        expect(done.x + done.width, `${name}: [다 했어요]가 [이전] 왼쪽`).toBeLessThanOrEqual(prev.x + 0.5);
        const exit = await box(page, "나가기");
        const help = (await page.getByTestId("help-button").boundingBox())!;
        expect(exit.x + exit.width, `${name}: [나가기]는 왼쪽 그대로`).toBeLessThanOrEqual(help.x + 0.5);
        expect(help.x + help.width).toBeGreaterThan(vp.width / 2);
        // [다 했어요]는 화면 안, 버튼은 80px 이상.
        expect(done.y + done.height).toBeLessThanOrEqual(vp.height + 0.5);
        for (const b of await workerButtons(page)) expect(b.height, b.label).toBeGreaterThanOrEqual(80);
      });
    }
  }

  test("오른손(기본)은 [이전] 왼쪽·[다 했어요] 오른쪽", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 740 });
    await start(page, newState(), "/worker/job/asg-1/step/2");
    await page.getByTestId("step-sentence").waitFor();
    expect((await box(page, "이전")).x).toBeLessThan((await box(page, "다 했어요")).x);
  });

  test("완료 화면 가로(두 버튼 나란히)도 왼손이면 뒤집는다, 위 띠는 그대로", async ({ page }) => {
    await page.setViewportSize({ width: 844, height: 390 });
    const right = await (async () => {
      await start(page, newState(), "/worker/job/asg-2/done");
      await page.getByTestId("job-done-screen").waitFor();
      return page.evaluate(() => Array.from(document.querySelectorAll("footer button")).map((b) => (b as HTMLElement).innerText.trim()));
    })();
    const p2 = await page.context().newPage();
    await p2.setViewportSize({ width: 844, height: 390 });
    await start(p2, newState(LEFT_HAND), "/worker/job/asg-2/done");
    await p2.getByTestId("job-done-screen").waitFor();
    const pos = await p2.evaluate(() =>
      Array.from(document.querySelectorAll("footer button")).map((b) => ({ t: (b as HTMLElement).innerText.trim(), x: b.getBoundingClientRect().x })));
    expect(pos).toHaveLength(2);
    // 가로 휴대폰에서 오른손은 DOM 순서대로 왼→오, 왼손은 거꾸로.
    const sorted = [...pos].sort((a, b) => a.x - b.x).map((p) => p.t);
    expect(sorted).toEqual([...right].reverse());
    await p2.close();
  });
});

test.describe("고대비: 흰 바탕·검정 글자, 버튼 3px 검정 테두리, 주 버튼 #1E4D33, axe 심각 0", () => {
  for (const [name, vp] of SIZES) {
    test(`${name} 단계·도움 띠·나가기 확인`, async ({ page }) => {
      await page.setViewportSize(vp);
      await start(page, newState(HIGH_CONTRAST), "/worker/job/asg-1/step/1");
      await page.getByTestId("step-sentence").waitFor();
      await page.waitForTimeout(300);
      const root = await page.getByTestId("step-player").evaluate((el) => {
        const s = getComputedStyle(el);
        return { bg: s.backgroundColor, fg: s.color };
      });
      expect(root).toEqual({ bg: "rgb(255, 255, 255)", fg: "rgb(0, 0, 0)" });
      const doneBg = await page.getByRole("button", { name: "다 했어요" }).evaluate((el) => getComputedStyle(el).backgroundColor);
      expect(doneBg).toBe("rgb(30, 77, 51)"); // #1E4D33
      const pic = await page.getByTestId("step-picture").evaluate((el) => {
        const s = getComputedStyle(el);
        return { w: s.borderTopWidth, c: s.borderTopColor };
      });
      expect(pic).toEqual({ w: "2px", c: "rgb(0, 0, 0)" });
      await expectHighContrastButtons(page, `${name} 단계`);
      await expectNoSeriousAxe(page, `${name} 단계`);

      await page.getByTestId("help-button").click();
      await expect(page.getByTestId("help-band")).toBeVisible();
      await page.waitForTimeout(300);
      const band = await page.getByTestId("help-band").evaluate((el) => {
        const s = getComputedStyle(el);
        return { bg: s.backgroundColor, fg: s.color, line: s.borderBottomColor };
      });
      expect(band).toEqual({ bg: "rgb(255, 255, 255)", fg: "rgb(0, 0, 0)", line: "rgb(0, 0, 0)" });
      await expectHighContrastButtons(page, `${name} 도움 띠`);
      await expectNoSeriousAxe(page, `${name} 도움 띠`);

      await page.getByRole("button", { name: "나가기" }).click();
      await expect(page.getByRole("button", { name: "멈출래요" })).toBeVisible();
      await expectHighContrastButtons(page, `${name} 나가기 확인`);
      await expectNoSeriousAxe(page, `${name} 나가기 확인`);
    });
  }

  test("홈·시작·완료 화면", async ({ page }) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width: 390, height: 740 });
    await start(page, newState(HIGH_CONTRAST), "/worker/today");
    for (const [url, id] of [["/worker/today", "today-screen"], ["/worker/job/asg-1", "job-start-screen"], ["/worker/job/asg-2/done", "job-done-screen"]] as const) {
      await page.goto(url);
      await page.getByTestId(id).waitFor();
      await page.waitForTimeout(200);
      await expectHighContrastButtons(page, id);
      await expectNoSeriousAxe(page, id);
    }
  });

  test("초점 고리: 4px 검정 + 바깥 간격(짙은 초록 버튼 옆에서도 흰 틈)", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 740 });
    await start(page, newState(HIGH_CONTRAST), "/worker/job/asg-1/step/2");
    await page.getByTestId("step-sentence").waitFor();
    const done = page.getByRole("button", { name: "다 했어요" });
    // 키보드 초점(:focus-visible)을 [다 했어요]까지 옮긴다.
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press("Tab");
      if (await done.evaluate((el) => el === document.activeElement)) break;
    }
    const ring = await done.evaluate((el) => {
      const s = getComputedStyle(el);
      return { w: s.outlineWidth, c: s.outlineColor, st: s.outlineStyle, off: parseFloat(s.outlineOffset), visible: el.matches(":focus-visible") };
    });
    expect(ring.visible).toBe(true);
    expect(ring).toMatchObject({ w: "4px", c: "rgb(0, 0, 0)", st: "solid" });
    expect(ring.off).toBeGreaterThanOrEqual(2);
  });
});

test.describe("로그인 전 화면은 앞 근로자 설정을 기억하지 않는다", () => {
  test("고대비·왼손 근로자가 [끝내기] 한 뒤 번호 넣기는 기본 화면", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 740 });
    const state = newState(HC_LEFT);
    await mockWorkerBackend(page, state);
    await loginAsWorker(page);
    await page.goto("/worker/today");
    await page.getByTestId("today-screen").waitFor();
    expect(await page.locator('[data-contrast="high"][data-hand="left"]').count()).toBe(1);
    await page.getByRole("button", { name: "끝내기" }).click();
    await page.getByRole("button", { name: "네, 끝낼래요" }).click();
    await page.getByTestId("keypad").waitFor();
    expect(await page.locator("[data-contrast], [data-hand], [data-font]").count()).toBe(0);
    const keyBorder = await page.getByTestId("keypad").locator("button").first().evaluate((el) => getComputedStyle(el).borderTopColor);
    expect(keyBorder).not.toBe("rgb(0, 0, 0)");
    // 기기에도 앞사람 화면 설정이 남지 않는다(내 정보 사본을 지움).
    const stored = await page.evaluate(() => JSON.stringify(Object.fromEntries(Object.entries(localStorage))));
    expect(stored).not.toContain('"contrast":"high"');
  });

  test("연결만 된 기기의 번호 넣기도 기본 화면", async ({ page }) => {
    await mockWorkerBackend(page, newState(HC_LEFT));
    await pairedDevice(page);
    await page.goto("/worker");
    await page.getByTestId("keypad").waitFor();
    expect(await page.locator("[data-contrast], [data-hand]").count()).toBe(0);
  });
});

test.describe("사용 측정 이벤트(3b-1)", () => {
  test("step_done(배정 id·머문 초)·tap_debounced·exit_cancel·exit_confirm, 개인정보 칸 없음", async ({ page }) => {
    const state = newState();
    await start(page, state, "/worker/job/asg-1/step/1");
    await page.getByTestId("step-sentence").waitFor();
    const done = page.getByRole("button", { name: "다 했어요" });
    // 600ms 안의 두 번째 누름(Playwright click 두 번은 사이에 기다림이 있어 600ms를 넘길 수 있다).
    await done.evaluate((el) => {
      (el as HTMLButtonElement).click();
      (el as HTMLButtonElement).click();
    });
    await expect(page.getByTestId("step-sentence")).toHaveText("테이프를 붙여요");
    await page.waitForTimeout(700);
    await page.getByRole("button", { name: "나가기" }).click();
    await page.getByRole("button", { name: "계속할래요" }).click();
    await page.waitForTimeout(700);
    await page.getByRole("button", { name: "나가기" }).click();
    await page.getByRole("button", { name: "멈출래요" }).click();
    await page.getByTestId("today-screen").waitFor();
    await expect.poll(() => (state.events ?? []).map((e) => e.name), { timeout: 8000 }).toEqual(
      expect.arrayContaining(["step_view", "step_done", "tap_debounced", "exit_cancel", "exit_confirm"]),
    );
    const evs = state.events!;
    const stepDone = evs.find((e) => e.name === "step_done")!;
    expect(stepDone).toMatchObject({ assignment_id: "asg-1", task_id: "t1", step_id: "s1" });
    expect(typeof stepDone.value_num).toBe("number");
    for (const e of evs) {
      expect(e.assignment_id).toBe("asg-1");
      for (const k of Object.keys(e)) expect(["name", "task_id", "step_id", "assignment_id", "value_num", "at"]).toContain(k);
    }
    expect(JSON.stringify(evs)).not.toContain("김민수");
  });

  test("끊긴 동안 끝낸 단계: offline_queued·step_done은 연결 뒤 보내고, 기록을 다 보내면 offline_flushed", async ({ page }) => {
    const state = newState();
    await start(page, state, "/worker/job/asg-2/step/1");
    await page.getByTestId("step-sentence").waitFor();
    state.offline = true;
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await expect(page.getByTestId("offline-band")).toBeVisible();
    await page.getByRole("button", { name: "다 했어요" }).click();
    await expect(page.getByTestId("job-done-screen")).toBeVisible();
    state.offline = false;
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await expect.poll(() => state.logs.length).toBe(1);
    await expect.poll(() => (state.events ?? []).map((e) => e.name), { timeout: 8000 }).toEqual(
      expect.arrayContaining(["offline_queued", "step_done", "offline_flushed"]),
    );
    const flushed = state.events!.find((e) => e.name === "offline_flushed")!;
    expect(flushed.value_num).toBe(1);
    expect(state.events!.find((e) => e.name === "offline_queued")).toMatchObject({ assignment_id: "asg-2", step_id: "c1" });
  });

  test("도움 띠 [취소]는 help_cancel", async ({ page }) => {
    const state = newState();
    await start(page, state, "/worker/job/asg-1/step/1");
    await page.getByTestId("help-button").click();
    await expect(page.getByTestId("help-band")).toBeVisible();
    await page.getByTestId("help-band").getByRole("button", { name: "취소" }).click();
    await expect.poll(() => (state.events ?? []).map((e) => e.name), { timeout: 8000 }).toEqual(
      expect.arrayContaining(["help_open", "help_cancel"]),
    );
    expect(state.events!.find((e) => e.name === "help_cancel")).toMatchObject({ assignment_id: "asg-1", step_id: "s1" });
  });
});
