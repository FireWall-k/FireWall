import { test, expect, devices, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { loginEmployer, mockEmployer } from "./employer-mock";
import { FIXED_SENTENCE, fixedDraft, fourStateDraft, mockEditor } from "./editor-mock";

// 사업주 접근성 자동 검사(명세 8.2·8.3, tasks §3.4·§4.4): 로그인·직무 목록·새 직무·편집기·그림 한눈에·보내기 시트를
// 1440·390 폭에서 axe로 본다.
// 기준: 심각(serious·critical) 위반 0, 이름 없는 버튼(button-name) 0.
const { defaultBrowserType: _ignored, ...DESKTOP } = devices["Desktop Chrome"];
void _ignored;
test.use({ ...DESKTOP, locale: "ko-KR" });

async function axe(page: Page) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const serious = r.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
  const buttonName = r.violations.filter((v) => v.id === "button-name");
  return { serious, buttonName };
}

for (const width of [1440, 390] as const) {
  test.describe(`${width}폭`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 } });

    test("로그인 화면: axe 심각 0·button-name 0", async ({ page }) => {
      await mockEmployer(page);
      await page.goto("/m/login");
      await expect(page.getByRole("button", { name: "로그인", exact: true })).toBeVisible();
      const r = await axe(page);
      expect(r.serious).toEqual([]);
      expect(r.buttonName).toEqual([]);
    });

    test("직무 목록: axe 심각 0·button-name 0(도움 띠·행 메뉴 포함)", async ({ page }) => {
      await mockEmployer(page);
      await loginEmployer(page, "/m/tasks");
      await expect(page.getByText("컵 씻기")).toBeVisible();
      await expect(page.getByTestId("help-band")).toBeVisible();
      let r = await axe(page);
      expect(r.serious).toEqual([]);
      expect(r.buttonName).toEqual([]);

      // 메뉴를 연 상태(꺼 둔 '고치기'와 그 이유 포함)
      await page.getByRole("button", { name: "컵 씻기 메뉴" }).click();
      await expect(page.getByRole("menu")).toBeVisible();
      r = await axe(page);
      expect(r.serious).toEqual([]);
    });

    // 2b-1: 새 직무 화면(NewTaskPage). 라벨은 '어떤 일을 시킬까요?'(옛 '직무 내용'). 1회차 검증에서 옛 화면 기준으로 늘 실패했다.
    test("새 직무(/m/tasks/new?example=1): axe 심각 0·button-name 0, 'AI' 글자 0", async ({ page }) => {
      await mockEmployer(page);
      await loginEmployer(page, "/m/tasks/new?example=1");
      await expect(page.getByLabel("어떤 일을 시킬까요?")).toHaveValue(/손을 깨끗이 씻어요/);
      await expect(page.getByTestId("example-note")).toBeVisible();
      await expect(page.getByTestId("help-band")).toBeVisible();
      const r = await axe(page);
      expect(r.serious).toEqual([]);
      expect(r.buttonName).toEqual([]);
      expect(await page.locator("main").innerText()).not.toMatch(/\bAI\b/);
    });

    test("새 직무 나눈 뒤('이렇게 나눴어요'): axe 심각 0·button-name 0, 'AI' 글자 0", async ({ page }) => {
      await mockEditor(page);
      await loginEmployer(page, "/m/tasks/new");
      await page.getByLabel("어떤 일을 시킬까요?").fill(FIXED_SENTENCE);
      await page.getByRole("button", { name: "단계로 나누기" }).click();
      await expect(page.getByRole("heading", { name: /이렇게 나눴어요/ })).toBeVisible();
      await page.waitForTimeout(500); // 등장 애니메이션이 끝난 뒤 대비를 잰다
      const r = await axe(page);
      expect(r.serious).toEqual([]);
      expect(r.buttonName).toEqual([]);
      expect(await page.locator("main").innerText()).not.toMatch(/\bAI\b/);
    });

    // 2b-1 1회차 검증: 편집기(그림 4상태)·그림 한눈에(확인 전·후)·보내기 시트를 axe로 본다(tasks §4.4·4.5).
    // 단계 행·한눈에 칸 단추는 보이는 글이 이름이다(aria-label로 덮으면 label-content-name-mismatch).
    test("편집기 상세 4상태: axe 심각 0·button-name 0", async ({ page }) => {
      const t = fourStateDraft();
      await mockEditor(page, { tasks: [t] });
      await loginEmployer(page, `/m/tasks/${t.id}`);
      await expect(page.getByTestId("task-editor")).toBeVisible();
      await page.waitForTimeout(400);
      let r = await axe(page);
      expect(r.serious).toEqual([]);
      for (let n = 1; n <= 4; n++) {
        if (width === 390) {
          await page.goto(`/m/tasks/${t.id}`);
          await expect(page.getByTestId("task-editor")).toBeVisible();
        }
        await page.getByTestId(`step-row-${n}`).getByRole("button").first().click();
        await expect(page.getByTestId("step-detail")).toHaveAttribute("data-step-id", t.steps[n - 1].id);
        await page.waitForTimeout(400);
        r = await axe(page);
        expect(r.serious, `${n}단계`).toEqual([]);
        expect(r.buttonName, `${n}단계`).toEqual([]);
      }
    });

    test("그림 한눈에(확인 전·후)와 보내기 시트: axe 심각 0", async ({ page }) => {
      const t = fixedDraft();
      await mockEditor(page, { tasks: [t] });
      await loginEmployer(page, `/m/tasks/${t.id}`);
      await expect(page.getByTestId("task-editor")).toBeVisible();
      await page.getByRole("button", { name: "그림 한눈에" }).first().click();
      await expect(page.getByRole("heading", { name: "그림 한눈에 보기" })).toBeVisible();
      await expect(page.getByTestId("confirm-all")).not.toHaveAttribute("aria-disabled", "true");
      await page.waitForTimeout(400);
      expect((await axe(page)).serious).toEqual([]);
      await page.getByTestId("confirm-all").click();
      await expect(page.getByTestId("picture-overview").getByText("모두 확인했어요").first()).toBeVisible();
      expect((await axe(page)).serious).toEqual([]);
      await page.getByTestId("picture-overview").getByRole("button", { name: "보내기" }).click();
      await expect(page.getByRole("dialog", { name: "보내기 전에 확인해요" })).toBeVisible();
      await page.waitForTimeout(400);
      const r = await axe(page);
      expect(r.serious).toEqual([]);
      expect(r.buttonName).toEqual([]);
    });

    test("직무 목록 빈 상태: axe 심각 0", async ({ page }) => {
      await mockEmployer(page, { tasks: [] });
      await loginEmployer(page, "/m/tasks");
      await expect(page.getByText("아직 만든 직무가 없어요")).toBeVisible();
      expect((await axe(page)).serious).toEqual([]);
      // [예시로 만들어 보기] → 예시로 채운 새 직무 화면
      // 키보드로 누르면 링크가 사라지므로 초점이 body로 빠지지 않고 본문(main)으로 간다(1회차 검증).
      await page.getByRole("link", { name: "예시로 만들어 보기" }).focus();
      await page.keyboard.press("Enter");
      await expect(page).toHaveURL(/\/m\/tasks\/new\?example=1$/);
      await expect(page.getByLabel("업종")).toHaveValue("카페");
      await expect.poll(() => page.evaluate(() => document.activeElement?.id ?? "")).toBe("main");
      await page.keyboard.press("Tab");
      expect(await page.evaluate(() => document.activeElement?.tagName)).not.toBe("BODY");
    });
  });
}

test("보관 걸러보기의 완전히 지우기 창: axe 심각 0", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockEmployer(page);
  await loginEmployer(page, "/m/tasks?filter=archived");
  await page.getByRole("button", { name: "옛 창고 정리 메뉴" }).click();
  await page.getByRole("menuitem", { name: "완전히 지우기" }).click();
  await expect(page.getByRole("alertdialog")).toBeVisible();
  expect((await axe(page)).serious).toEqual([]);
});

// ── 2회차 검증 반영: 초점이 body로 빠지지 않음, 토스트가 위험 창을 가리지 않음, 행동 뒤 다시 받기 ──

const activeTag = (page: Page) => page.evaluate(() => document.activeElement?.tagName ?? "");

async function archiveRow(page: Page, title: string) {
  await page.getByRole("button", { name: `${title} 메뉴` }).click();
  await page.getByRole("menuitem", { name: "보관하기" }).click();
  await expect(page.getByRole("button", { name: "실행 취소" })).toBeVisible();
}

test("토스트 [닫기](X)를 키보드로 누르면 초점이 body로 사라지지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockEmployer(page);
  await loginEmployer(page, "/m/tasks");
  await archiveRow(page, "앞치마 입기");
  const close = page.locator("[data-toast-layer] [role=status]").first().getByRole("button", { name: "닫기" });
  await close.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("[data-toast-layer] [role=status]")).toHaveCount(0);
  expect(await activeTag(page)).not.toBe("BODY");
});

test("키보드로 누른 [실행 취소]가 서버 오류로 실패해도 초점이 body로 빠지지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const m = await mockEmployer(page);
  await loginEmployer(page, "/m/tasks");
  await archiveRow(page, "컵 씻기");
  m.failPaths.add("/api/tasks/t1/unarchive");
  await page.getByRole("button", { name: "실행 취소" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("처리하지 못했어요. 잠시 뒤 다시 시도해 주세요.")).toBeVisible();
  await expect.poll(() => activeTag(page)).not.toBe("BODY");
  expect(await page.evaluate(() => document.activeElement?.getAttribute("data-task-menu"))).toBeTruthy();
});

test("완전히 지우기를 처리하는 동안에도 초점이 창 안에 있고 Tab도 창 안에서 돈다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockEmployer(page);
  // 지우기 요청을 2초 늦춘다(나중에 단 route가 먼저 받는다).
  await page.route("**/api/tasks/t9", async (route) => {
    await new Promise((r) => setTimeout(r, 2_000));
    await route.fallback();
  });
  await loginEmployer(page, "/m/tasks?filter=archived");
  await page.getByRole("button", { name: "옛 창고 정리 메뉴" }).click();
  await page.getByRole("menuitem", { name: "완전히 지우기" }).click();
  const dialog = page.getByRole("alertdialog");
  const confirm = dialog.getByRole("button", { name: "완전히 지우기" });
  await confirm.focus();
  await page.keyboard.press("Enter");
  await expect(confirm).toHaveAttribute("aria-busy", "true");
  const inside = () => page.evaluate(() => !!document.activeElement?.closest("[role=alertdialog]"));
  expect(await inside()).toBe(true);
  await page.keyboard.press("Tab");
  expect(await inside()).toBe(true);
  await expect(dialog).toHaveCount(0, { timeout: 5_000 });
});

test("390폭: 위험 창이 열린 동안 토스트는 창 아래로 내려가고(inert) 지워지는 것 목록을 가리지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockEmployer(page);
  await loginEmployer(page, "/m/tasks");
  await archiveRow(page, "앞치마 입기");
  await page.getByRole("tab", { name: /보관/ }).click();
  await page.getByRole("button", { name: "옛 창고 정리 메뉴" }).click();
  await page.getByRole("menuitem", { name: "완전히 지우기" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await expect(page.locator("[data-toast-layer] [role=status]")).toHaveCount(1); // 보관 토스트가 아직 떠 있다
  await expect(page.locator("[data-toast-layer]")).toHaveAttribute("inert", "");
  const covered = await dialog.locator("li").evaluateAll((lis) =>
    lis.map((li) => {
      const r = li.getBoundingClientRect();
      const top = document.elementFromPoint(r.left + 8, r.top + r.height / 2);
      return !!top?.closest("[data-toast-layer]");
    }),
  );
  expect(covered.length).toBe(4);
  expect(covered.every((c) => !c)).toBe(true);
});

test("보관 → '보관' 탭 → [실행 취소]: 목록이 불러오는 중에 멈추지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockEmployer(page);
  await loginEmployer(page, "/m/tasks");
  await archiveRow(page, "앞치마 입기");
  await page.getByRole("tab", { name: /보관/ }).click();
  await expect(page).toHaveURL(/filter=archived/);
  await expect(page.getByText("옛 창고 정리")).toBeVisible();
  await page.getByRole("button", { name: "실행 취소" }).click();
  await expect(page.getByRole("table")).not.toHaveAttribute("aria-busy", "true");
  await expect(page.getByText("옛 창고 정리")).toBeVisible();
  await expect(page.getByRole("table").getByText("앞치마 입기")).toHaveCount(0);
});

test("보관 요청이 끝나기 전에 '초안' 탭을 누르면 끝난 뒤에도 초안 목록이 보인다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockEmployer(page);
  await page.route("**/api/tasks/*/archive", async (route) => {
    await new Promise((r) => setTimeout(r, 1_500));
    await route.fallback();
  });
  await loginEmployer(page, "/m/tasks");
  await page.getByRole("button", { name: "앞치마 입기 메뉴" }).click();
  await page.getByRole("menuitem", { name: "보관하기" }).click();
  await page.getByRole("tab", { name: /초안/ }).click();
  await expect(page.getByRole("button", { name: "실행 취소" })).toBeVisible({ timeout: 5_000 });
  await expect(page.getByRole("table")).not.toHaveAttribute("aria-busy", "true");
  await expect(page.getByRole("table").getByText("컵 씻기")).toBeVisible();
});
