import { test, expect, devices, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { horizontalOverflow, loginEmployer, mockEmployer } from "./employer-mock";
import { minFontPx, mockWorkers } from "./workers-mock";

// (2d) 근로자 목록·상세 4탭·설정·홈 자리를 1440·390 폭에서 본다(tasks §7 시험, 명세 8.2·8.3).
// 기준: axe 심각(serious·critical) 0, 보이는 글자 12px 이상, 가로 스크롤 0, 'AI' 글자 0.
// 로그인·직무 목록·새 직무는 employer-a11y.spec이 본다(편집기·보내기 시트는 2b-1이 그 파일에 더함).
const { defaultBrowserType: _ignored, ...DESKTOP } = devices["Desktop Chrome"];
void _ignored;
test.use({ ...DESKTOP, locale: "ko-KR" });

async function check(page: Page, label: string) {
  await page.waitForTimeout(300); // 등장 애니메이션이 끝난 뒤 대비를 잰다
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const serious = r.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
  expect(serious, label).toEqual([]);
  const min = await minFontPx(page);
  expect(min.px, `${label} 가장 작은 글자: ${min.text}`).toBeGreaterThanOrEqual(12);
  expect(await horizontalOverflow(page), `${label} 가로 스크롤`).toBe(0);
  expect(await page.locator("body").innerText(), label).not.toMatch(/\bAI\b/);
}

for (const width of [1440, 390] as const) {
  test.describe(`${width}폭`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 } });

    test("근로자 목록·번호 보기·행 메뉴·추가 창·지우기 창", async ({ page }) => {
      await mockEmployer(page);
      await mockWorkers(page);
      await loginEmployer(page, "/m/workers");
      await expect(page.getByRole("link", { name: "김민지" })).toBeVisible();
      await expect(page.getByRole("button", { name: "근로자 추가하기" })).toBeVisible();
      await check(page, "목록");

      await page.getByRole("button", { name: "김민지 님 번호 5초 보기" }).click();
      await expect(page.getByRole("row").filter({ hasText: "김민지" }).getByTestId("access-code")).toHaveText("4821");
      await check(page, "번호 보임");

      await page.getByRole("button", { name: "김민지 님 메뉴" }).click();
      await expect(page.getByRole("menu")).toBeVisible();
      await check(page, "행 메뉴");
      await page.getByRole("menuitem", { name: "지우기" }).click();
      const del = page.getByRole("alertdialog");
      await expect(del).toBeVisible();
      await expect(del.getByRole("button", { name: "지우기" })).toBeDisabled();
      await check(page, "지우기 창");
      await del.getByRole("button", { name: "취소" }).click();

      await page.getByRole("button", { name: "근로자 추가하기" }).click();
      await page.getByRole("dialog").getByLabel(/이름/).fill("한별");
      await page.getByRole("dialog").getByRole("button", { name: "추가하기" }).click();
      await expect(page.getByTestId("new-worker-code")).toHaveText("0712");
      await check(page, "추가 결과");
      await page.getByRole("button", { name: "인쇄용 카드 만들기" }).click();
      await expect(page.getByTestId("qr-code")).toBeVisible();
      await check(page, "인쇄 카드");
    });

    test("근로자 상세 4탭(현황·화면 설정·접속 코드·동의·개인정보)", async ({ page }) => {
      await mockEmployer(page);
      await mockWorkers(page);
      await loginEmployer(page, "/m/workers/w1");
      await expect(page.getByRole("heading", { level: 1, name: "김민지 님" })).toBeVisible();
      await expect(page.getByText("2분 28초")).toBeVisible();
      await check(page, "현황");
      await page.getByRole("button", { name: "표로 보기" }).click();
      await expect(page.getByRole("table", { name: "단계별 기록" })).toBeVisible();
      await check(page, "현황 표");

      await page.getByRole("tab", { name: "화면 설정" }).click();
      await expect(page.getByRole("group", { name: "말 속도" })).toBeVisible();
      await check(page, "화면 설정");

      await page.getByRole("tab", { name: "접속 코드" }).click();
      await expect(page.getByRole("button", { name: "새 번호 만들기" })).toBeVisible();
      await check(page, "접속 코드");

      await page.getByRole("tab", { name: "동의·개인정보" }).click();
      await expect(page.getByText("자동 처리 동의 아직 없음")).toBeVisible();
      await check(page, "동의");
      await page.getByRole("heading", { name: "자동 처리·국외 이전 동의" }).locator("xpath=../..").getByRole("button", { name: "당사자에게 받았어요" }).click();
      await expect(page.getByRole("dialog", { name: "자동 처리·국외 이전 동의를 받았나요?" })).toBeVisible();
      await check(page, "동의 창");
    });

    test("설정(사업장·기기 연결 QR·기본값·호칭 미리보기·알림·계정)", async ({ page }) => {
      await mockEmployer(page);
      await mockWorkers(page);
      await loginEmployer(page, "/m/settings");
      await expect(page.getByRole("heading", { level: 1, name: "설정" })).toBeVisible();
      await expect(page.getByTestId("qr-code")).toBeVisible();
      await expect(page.getByTestId("device-link")).toHaveText("http://localhost:5173/w?site=AB12CD");
      await check(page, "설정");
      await page.getByRole("button", { name: "인쇄용 카드 만들기" }).click();
      await expect(page.getByRole("dialog", { name: "기기 연결 카드" })).toBeVisible();
      await check(page, "기기 연결 카드");
    });

    test("홈 자리(2c 전까지)·빈 근로자 목록", async ({ page }) => {
      await mockEmployer(page);
      await mockWorkers(page, { empty: true });
      await loginEmployer(page, "/m");
      await expect(page.getByRole("heading", { level: 1, name: "홈" })).toBeVisible();
      await check(page, "홈");
      await page.goto("/m/workers");
      await expect(page.getByText("아직 근로자가 없어요")).toBeVisible();
      await check(page, "빈 목록");
    });
  });
}

test("키보드만으로: 근로자 추가 → 번호 확인 → 닫으면 초점이 [근로자 추가하기]로", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockEmployer(page);
  await mockWorkers(page);
  await loginEmployer(page, "/m/workers");
  const add = page.getByRole("button", { name: "근로자 추가하기" });
  await add.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  // 초점은 창 안에 있다.
  expect(await page.evaluate(() => !!document.activeElement?.closest("[role=dialog]"))).toBe(true);
  await dialog.getByLabel(/이름/).focus();
  await page.keyboard.type("한별");
  await page.keyboard.press("Enter"); // 폼 제출
  await expect(page.getByTestId("new-worker-code")).toHaveText("0712");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => document.activeElement?.textContent ?? "")).toContain("근로자 추가하기");
});

test("키보드만으로: 근로자 지우기는 이름을 똑같이 적어야 눌린다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockEmployer(page);
  const m = await mockWorkers(page);
  await loginEmployer(page, "/m/workers");
  await page.getByRole("button", { name: "박서연 님 메뉴" }).focus();
  await page.keyboard.press("Enter");
  await page.getByRole("menuitem", { name: "지우기" }).focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("alertdialog");
  await dialog.getByRole("textbox").fill("박서현");
  await expect(dialog.getByRole("button", { name: "지우기" })).toBeDisabled();
  await dialog.getByRole("textbox").fill("박서연");
  await dialog.getByRole("button", { name: "지우기" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("박서연 님을 지웠어요")).toBeVisible();
  expect(m.calls).toContain("POST /api/workers/w3/delete");
  await expect(page.getByRole("link", { name: "박서연" })).toHaveCount(0);
  expect(await page.evaluate(() => document.activeElement?.tagName)).not.toBe("BODY");
});

test("설정: 호칭을 '코치'로 바꾸면 미리보기가 '코치를 불렀어요'로 바뀌고 저장된다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockEmployer(page);
  const m = await mockWorkers(page);
  await loginEmployer(page, "/m/settings");
  const input = page.getByLabel(/^호칭/);
  await input.fill("코치");
  await expect(page.getByTestId("title-preview")).toContainText("코치를 불렀어요. 여기서 기다려요.");
  await page.getByRole("button", { name: "호칭 저장하기" }).click();
  await expect(page.getByText("호칭을 저장했어요")).toBeVisible();
  expect(m.workplace.teacher_title).toBe("코치");
});

test("근로자 상세: 말 속도 '느리게 0.8'을 고르면 바로 저장된다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockEmployer(page);
  const m = await mockWorkers(page);
  await loginEmployer(page, "/m/workers/w1?tab=prefs");
  await page.getByText("느리게 0.8").click();
  await expect(page.getByText("저장했어요")).toBeVisible();
  expect(m.workers.find((w) => w.id === "w1")!.a11y_prefs.tts_rate).toBe(0.8);
});
