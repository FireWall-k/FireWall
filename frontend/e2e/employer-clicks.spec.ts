import { test, expect, devices, type Locator, type Page } from "@playwright/test";
import { loginEmployer } from "./employer-mock";
import { FIXED_SENTENCE, fixedDraft, mockEditor } from "./editor-mock";

// 클릭 수(명세 3.4-A 목표 8번 이하, tasks §4.5): [새 직무]부터 센다. 확신 높은 6단계(고정 문장)·받는 사람 미리 체크.
// [새 직무] → [단계로 나누기] → [이대로 그림 고르기] → [그림 한눈에] → [보이는 자동 그림 모두 맞아요] → [보내기] →
// [1명에게 보내기] = 7번. 다시 보내기는 … → [다시 보내기] → [1명에게 보내기] = 3번. 글자 넣기는 클릭으로 세지 않는다.
const { defaultBrowserType: _ignored, ...DESKTOP } = devices["Desktop Chrome"];
void _ignored;
test.use({ ...DESKTOP, locale: "ko-KR", viewport: { width: 1440, height: 900 } });

function counter(page: Page) {
  let n = 0;
  const seen: string[] = [];
  return {
    async click(l: Locator, label: string) {
      await expect(l).toBeVisible();
      await l.click();
      n += 1;
      seen.push(label);
    },
    get count() {
      return n;
    },
    seen,
    page,
  };
}

test("새 직무 → 보내기: 클릭 7번, 퍼센트 글자 0건", async ({ page }) => {
  const m = await mockEditor(page);
  await loginEmployer(page, "/m/tasks");
  const c = counter(page);
  await c.click(page.getByRole("link", { name: "새 직무" }).first(), "새 직무");
  await page.getByLabel("어떤 일을 시킬까요?").fill(FIXED_SENTENCE);
  await c.click(page.getByRole("button", { name: "단계로 나누기" }), "단계로 나누기");
  await c.click(page.getByRole("button", { name: "이대로 그림 고르기" }), "이대로 그림 고르기");
  await expect(page.getByTestId("task-editor")).toBeVisible();
  await c.click(page.getByRole("button", { name: "그림 한눈에" }), "그림 한눈에");
  await expect(page.getByTestId("confirm-all")).not.toHaveAttribute("aria-disabled", "true");
  await c.click(page.getByTestId("confirm-all"), "보이는 자동 그림 모두 맞아요");
  await c.click(page.getByTestId("picture-overview").getByRole("button", { name: "보내기" }), "보내기");
  await c.click(page.getByRole("dialog").getByRole("button", { name: "1명에게 보내기" }), "1명에게 보내기");
  await expect(page.getByText("1명에게 보냈어요")).toBeVisible();
  expect(c.seen).toHaveLength(7);
  expect(c.count).toBeLessThanOrEqual(8);
  expect(m.sends).toHaveLength(1);
  expect(await page.evaluate(() => document.body.innerText)).not.toMatch(/\d+\s*%/);
});

test("다시 보내기: 클릭 3번(지난번 받은 사람 미리 체크, 점검표 모두 통과)", async ({ page }) => {
  const t = fixedDraft({ title: "매장 정리" });
  for (const s of t.steps) s.state = "confirmed";
  t.versionNo = 1;
  t.sentSnapshot = JSON.stringify(t.steps.map((s) => [s.sentence, s.url, s.safety, s.groupBreak]));
  t.recipients = ["w1"];
  t.lastBatch = ["w1"];
  const m = await mockEditor(page, {
    tasks: [t],
    workers: [
      { id: "w1", display_name: "김민지", access_code: "4821" },
      { id: "w2", display_name: "이서준", access_code: "7390" },
    ],
  });
  await loginEmployer(page, "/m/tasks");
  const c = counter(page);
  await c.click(page.getByRole("button", { name: "매장 정리 메뉴" }), "…");
  await c.click(page.getByRole("menuitem", { name: "다시 보내기" }), "다시 보내기");
  const sheet = page.getByRole("dialog", { name: "보내기 전에 확인해요" });
  await expect(sheet.getByRole("checkbox", { name: /김민지 님/ })).toBeChecked();
  await expect(sheet.getByText("지난번 받은 사람을 골라 두었어요")).toBeVisible();
  await c.click(sheet.getByRole("button", { name: "1명에게 보내기" }), "1명에게 보내기");
  await expect(page.getByText("1명에게 보냈어요")).toBeVisible();
  expect(c.count).toBe(3);
  expect(m.sends).toEqual([{ taskId: t.id, workerIds: ["w1"], day: "today" }]);
});

test("스켈레톤에도 퍼센트 숫자가 없다(그림을 고르고 있어요 → 목소리를 만들고 있어요)", async ({ page }) => {
  await mockEditor(page);
  // 초안 만들기를 늦춰 스켈레톤을 본다.
  await page.route("http://e2e-api.invalid/api/tasks", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    await new Promise((r) => setTimeout(r, 3500));
    return route.fallback();
  });
  await loginEmployer(page, "/m/tasks/new");
  await page.getByLabel("어떤 일을 시킬까요?").fill(FIXED_SENTENCE);
  await page.getByRole("button", { name: "단계로 나누기" }).click();
  await page.getByRole("button", { name: "이대로 그림 고르기" }).click();
  const sk = page.getByTestId("editor-skeleton");
  await expect(sk).toContainText("그림을 고르고 있어요");
  await expect(sk).toContainText("목소리를 만들고 있어요");
  expect(await sk.innerText()).not.toMatch(/%/);
  await expect(page.getByTestId("task-editor")).toBeVisible({ timeout: 10_000 });
});
