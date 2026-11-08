import { test } from "@playwright/test";
import { loginAsWorker, mockWorkerBackend, newState, pairedDevice } from "./w-mock";

// 전후 비교용 스크린샷(검사 아님). SHOTS_DIR을 줄 때만 돈다:
//   SHOTS_DIR=../shots npx playwright test e2e/w-shots.spec.ts
const dir = process.env.SHOTS_DIR;
test.skip(!dir, "SHOTS_DIR이 없으면 건너뛴다");

const SIZES = [
  ["390x740", { width: 390, height: 740 }],
  ["360x560", { width: 360, height: 560 }],
  ["844x390", { width: 844, height: 390 }],
  ["820x1180", { width: 820, height: 1180 }],
] as const;

for (const [name, vp] of SIZES) {
  test(`screens ${name}`, async ({ page }) => {
    const state = newState();
    await mockWorkerBackend(page, state);
    await loginAsWorker(page);
    await page.setViewportSize(vp);
    await page.goto("/w/today");
    await page.getByTestId("today-screen").waitFor();
    await page.screenshot({ path: `${dir}/today-${name}.png` });
    await page.goto("/w/job/asg-1");
    await page.getByTestId("job-start-screen").waitFor();
    await page.screenshot({ path: `${dir}/start-${name}.png` });
    await page.goto("/w/job/asg-1/step/1");
    await page.getByTestId("step-player").waitFor();
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${dir}/step-${name}.png` });
    await page.getByTestId("help-button").click();
    await page.getByText("선생님을 불렀어요. 여기서 기다려요.").waitFor();
    await page.screenshot({ path: `${dir}/step-help-${name}.png` });
    await page.goto("/w/job/asg-1/step/3");
    await page.getByTestId("step-player").waitFor();
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${dir}/step-long-${name}.png` });
    await page.goto("/w/job/asg-2/done");
    await page.getByTestId("job-done-screen").waitFor();
    await page.screenshot({ path: `${dir}/done-${name}.png` });
    await page.goto("/w/history");
    await page.getByTestId("history-screen").waitFor();
    await page.screenshot({ path: `${dir}/history-${name}.png` });
  });

  test(`entry ${name}`, async ({ page }) => {
    const state = newState();
    await mockWorkerBackend(page, state);
    await pairedDevice(page);
    await page.setViewportSize(vp);
    await page.goto("/w");
    await page.getByTestId("entry-screen").waitFor();
    await page.screenshot({ path: `${dir}/entry-${name}.png` });
    for (const d of ["1", "2", "3", "5"]) await page.getByRole("button", { name: d, exact: true }).click();
    await page.getByTestId("login-notice").waitFor();
    await page.screenshot({ path: `${dir}/entry-wrong-${name}.png` });
  });
}
