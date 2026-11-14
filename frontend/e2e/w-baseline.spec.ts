import { expect, test, type Page } from "@playwright/test";
import { HC_LEFT, loginAsWorker, mockWorkerBackend, newState, pairedDevice } from "./w-mock";

// 근로자 화면 기준 이미지(2a-0 §2.1). cfa5396 화면을 기준으로 삼아, 이후 2a-0·2a-1·2b-1·2d가
// 근로자 화면을 바꾸지 않았는지 비교한다(띠 없는 단계 화면 포함).
//   비교:   npx playwright test e2e/w-baseline.spec.ts
//   다시 찍기(화면을 일부러 바꿨을 때만): npx playwright test e2e/w-baseline.spec.ts --update-snapshots
// 기준 이미지는 e2e/w-baseline.spec.ts-snapshots/ 에 있다(파일 이름 끝에 운영체제가 붙는다).

const SIZES = [
  ["360x560", { width: 360, height: 560 }],
  ["390x740", { width: 390, height: 740 }],
  ["844x390", { width: 844, height: 390 }],
] as const;

const SCALES = [
  ["100", false],
  ["130", true],
] as const;

/** 시스템 글자 130%(html 글자 크기) — w-layout.spec의 bigText와 같다. */
async function bigText(page: Page, pct = 130) {
  await page.addInitScript((p) => {
    const set = () => {
      document.documentElement.style.fontSize = `${p}%`;
    };
    if (document.documentElement) set();
    document.addEventListener("DOMContentLoaded", set);
  }, pct);
}

/** 글꼴·그림이 다 그려진 뒤에 찍는다(글꼴 늦게 오는 실패 제거). */
async function settle(page: Page) {
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() =>
    Promise.all(
      Array.from(document.images)
        .filter((img) => !img.complete)
        .map((img) => new Promise((r) => { img.onload = img.onerror = r; })),
    ),
  );
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
}

/**
 * 단계 화면 문장 글자 크기 맞추기(useSentenceFit)는 글꼴이 오기 전 대체 글꼴로 한 번 재고, fonts.ready 뒤 다시 재려고
 * 화면 크기 문자열을 다시 넣는데 값이 같아 다시 재지 않는다 — 그래서 글꼴이 늦게 오면 한 단계 작은 글자로 남는다
 * (기준 이미지 3회 반복에서 130% 단계 화면이 가끔 달랐다). 기준은 '글꼴이 다 온 뒤 맞춘 크기'로 고정하려고, 글꼴이
 * 준비된 뒤 화면 높이를 1px 바꿨다 되돌려 다시 재게 한다(화면 코드는 바꾸지 않음 — 2a-0은 근로자 화면 변경 없음).
 */
async function refit(page: Page) {
  const vp = page.viewportSize();
  if (!vp) return;
  await page.evaluate(() => document.fonts.ready);
  await page.setViewportSize({ width: vp.width, height: vp.height + 1 });
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  await page.setViewportSize(vp);
}

async function shot(page: Page, name: string, opts: { refit?: boolean } = {}) {
  if (opts.refit) await refit(page);
  await settle(page);
  await expect(page).toHaveScreenshot(name, { animations: "disabled", caret: "hide" });
}

for (const [sizeName, vp] of SIZES) {
  for (const [scaleName, big] of SCALES) {
    const tag = `${sizeName}-${scaleName}`;

    test.describe(`근로자 기준 이미지 ${tag}`, () => {
      test.beforeEach(async ({ page }) => {
        if (big) await bigText(page);
        await page.setViewportSize(vp);
      });

      test("번호 넣기(키패드)", async ({ page }) => {
        await mockWorkerBackend(page, newState());
        await pairedDevice(page);
        await page.goto("/worker");
        await page.getByTestId("keypad").waitFor();
        await shot(page, `keypad-${tag}.png`);
      });

      test("오늘 할 일", async ({ page }) => {
        await mockWorkerBackend(page, newState());
        await loginAsWorker(page);
        await page.goto("/worker/today");
        await page.getByTestId("today-screen").waitFor();
        await shot(page, `today-${tag}.png`);
      });

      test("시작", async ({ page }) => {
        await mockWorkerBackend(page, newState());
        await loginAsWorker(page);
        await page.goto("/worker/job/asg-1");
        await page.getByTestId("job-start-screen").waitFor();
        await shot(page, `start-${tag}.png`);
      });

      test("단계(띠 없음) 짧은 문장·긴 문장", async ({ page }) => {
        await mockWorkerBackend(page, newState());
        await loginAsWorker(page);
        await page.goto("/worker/job/asg-1/step/1");
        await page.getByTestId("step-player").waitFor();
        await shot(page, `step-${tag}.png`, { refit: true });
        await page.goto("/worker/job/asg-1/step/3");
        await page.getByTestId("step-player").waitFor();
        await shot(page, `step-long-${tag}.png`, { refit: true });
      });

      test("완료", async ({ page }) => {
        await mockWorkerBackend(page, newState());
        await loginAsWorker(page);
        await page.goto("/worker/job/asg-2/done");
        await page.getByTestId("job-done-screen").waitFor();
        await shot(page, `done-${tag}.png`);
      });

      test("지난 기록", async ({ page }) => {
        // 날짜 이름('오늘'·'어제')이 실행하는 날에 따라 바뀌지 않게 목 데이터 날짜로 고정한다.
        await page.clock.setFixedTime(new Date("2026-11-09T10:00:00"));
        await mockWorkerBackend(page, { ...newState(), historyDate: "2026-11-09" });
        await loginAsWorker(page);
        await page.goto("/worker/history");
        await page.getByTestId("history-screen").waitFor();
        await shot(page, `history-${tag}.png`);
      });
    });
  }
}

// (3b-1) 고대비 + 왼손 + 글자 130%·200% 조합 화면 사진(명세 4.12·6.1). 기존 기준 이미지와 따로 둔다(hcleft-*).
// 처음 찍기: npx playwright test e2e/w-baseline.spec.ts -g 고대비 --update-snapshots=missing
// 주의: 200% 글자는 360·390 폭과 가로 844×390에서 기록용이다. 명세 4.0이 약속하는 범위(확대 뒤 CSS 폭 320px 이상)를
// 넘어서 위 띠 버튼이 겹치고 [다 했어요] 글자가 잘린다 — 지금 모습을 남겨 두고 고칠지는 창업자가 정한다(3b-1 보고).
const HC_SCALES = [130, 200] as const;

for (const [sizeName, vp] of SIZES) {
  for (const pct of HC_SCALES) {
    const tag = `${sizeName}-${pct}`;

    test.describe(`근로자 기준 이미지 고대비·왼손 ${tag}`, () => {
      test.beforeEach(async ({ page }) => {
        await bigText(page, pct);
        await page.setViewportSize(vp);
        await mockWorkerBackend(page, newState(HC_LEFT));
        await loginAsWorker(page);
      });

      test("오늘 할 일", async ({ page }) => {
        await page.goto("/worker/today");
        await page.getByTestId("today-screen").waitFor();
        await shot(page, `hcleft-today-${tag}.png`);
      });

      test("단계·도움 띠", async ({ page }) => {
        await page.goto("/worker/job/asg-1/step/2");
        await page.getByTestId("step-player").waitFor();
        await shot(page, `hcleft-step-${tag}.png`, { refit: true });
        await page.getByTestId("help-button").click();
        await page.getByTestId("help-band").waitFor();
        // 띠가 뜬 뒤 문장 칸을 내리는 일(requestAnimationFrame)과 글자 맞춤이 끝난 뒤 찍는다(병렬 실행에서 454px 차이가 났다).
        await page.waitForTimeout(400);
        await shot(page, `hcleft-step-help-${tag}.png`, { refit: true });
      });
    });
  }
}
