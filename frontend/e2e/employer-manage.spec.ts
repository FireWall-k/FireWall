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

// (2d 검증 1회차) 인쇄용 카드가 Dialog 패널(최대 높이·스크롤) 안에서 잘리고, 고정 오버레이라 쪽마다 반복되던 문제.
// 인쇄 모드에서 카드 전체(번호·사업장 코드·안내문)가 1쪽 맨 위에 한 번만 나오고, PDF가 1쪽인지 본다.
async function expectOnePagePrint(page: Page, mustShow: string[]) {
  await page.waitForTimeout(400); // 등장 애니메이션
  await page.emulateMedia({ media: "print" });
  const info = await page.evaluate(() => {
    const a = document.querySelector("[data-print-area]") as HTMLElement;
    const r = a.getBoundingClientRect();
    const all = Array.from(a.querySelectorAll<HTMLElement>("*"));
    // 카드 안 요소가 조상의 스크롤 상자에 잘리지 않았는지(보이는 높이 = 원래 높이).
    const clipped = all.filter((el) => {
      const er = el.getBoundingClientRect();
      return er.bottom > r.bottom + 1 || er.right > r.right + 1;
    }).length;
    const visibleOutside = Array.from(document.body.querySelectorAll<HTMLElement>("body *")).filter(
      (el) => !a.contains(el) && !el.contains(a) && el.getClientRects().length > 0,
    ).length;
    return { top: r.top, bottom: r.bottom, docH: document.documentElement.scrollHeight, clipped, visibleOutside, text: a.innerText };
  });
  expect(info.top, "카드가 쪽 맨 위").toBeLessThan(40);
  expect(info.clipped, "카드 안에서 잘린 요소").toBe(0);
  expect(info.visibleOutside, "카드 밖에 자리를 차지하는 요소").toBe(0);
  for (const t of mustShow) expect(info.text).toContain(t);
  const pdf = (await page.pdf({ format: "A4" })).toString("latin1");
  const pages = pdf.match(/\/Type\s*\/Page(?![s\w])/g) ?? [];
  expect(pages.length, "인쇄 쪽 수").toBe(1);
  await page.emulateMedia({ media: "screen" });
}

test("인쇄용 카드: 근로자 카드는 이름·QR·번호가 1쪽에 온전히 인쇄된다", async ({ page }) => {
  await mockEmployer(page);
  await mockWorkers(page);
  await loginEmployer(page, "/m/workers");
  await page.getByRole("button", { name: "근로자 추가하기" }).click();
  await page.getByRole("dialog").getByLabel(/이름/).fill("한별");
  await page.getByRole("dialog").getByRole("button", { name: "추가하기" }).click();
  await page.getByRole("button", { name: "인쇄용 카드 만들기" }).click();
  await expect(page.getByTestId("qr-code")).toBeVisible();
  await expectOnePagePrint(page, ["햇살카페", "0712"]);
  await expect(page.getByTestId("print-code")).toBeVisible();
});

test("인쇄용 카드: 기기 연결 카드는 사업장 코드까지 1쪽에 한 번만 인쇄된다", async ({ page }) => {
  await mockEmployer(page);
  await mockWorkers(page);
  await loginEmployer(page, "/m/settings");
  await expect(page.getByTestId("qr-code")).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 400));
  await page.getByRole("button", { name: "인쇄용 카드 만들기" }).click();
  await expect(page.getByRole("dialog", { name: "기기 연결 카드" })).toBeVisible();
  await expectOnePagePrint(page, ["AB12CD"]);
});

// (2d 검증 1회차) 터치 화면(pointer: coarse)에서 따로 놓인 이동 링크와 스위치도 44px 이상(명세 6.3).
test.describe("390 터치 화면 누를 곳", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  async function sizes(page: Page, selector: string) {
    return page.locator(selector).evaluateAll((els) =>
      els.filter((e) => e.getClientRects().length > 0).map((e) => {
        const r = e.getBoundingClientRect();
        return { name: (e.textContent ?? "").trim() || e.getAttribute("aria-labelledby") || "", w: Math.round(r.width), h: Math.round(r.height) };
      }),
    );
  }
  const small = (xs: { w: number; h: number }[]) => xs.filter((x) => x.w < 44 || x.h < 44);

  test("근로자 상세: 뒤로 링크·위 경로 링크·스위치가 44px 이상", async ({ page }) => {
    await mockEmployer(page);
    await mockWorkers(page);
    await loginEmployer(page, "/m/workers/w1?tab=prefs");
    expect(await page.evaluate(() => matchMedia("(pointer: coarse)").matches)).toBe(true);
    await expect(page.getByRole("group", { name: "말 속도" })).toBeVisible();
    const back = await sizes(page, "main a[href='/m/workers']");
    expect(back.length).toBeGreaterThan(0);
    expect(back.filter((x) => x.h < 44)).toEqual([]);
    const crumbs = await sizes(page, "header nav a");
    expect(crumbs.filter((x) => x.h < 44)).toEqual([]);
    const sw = await sizes(page, "[role=switch]");
    expect(sw.length).toBeGreaterThan(0);
    expect(small(sw)).toEqual([]);
  });

  test("설정: 스위치가 44px 이상", async ({ page }) => {
    await mockEmployer(page);
    await mockWorkers(page);
    await loginEmployer(page, "/m/settings");
    await expect(page.getByRole("heading", { level: 1, name: "설정" })).toBeVisible();
    const sw = await sizes(page, "[role=switch]");
    expect(sw.length).toBeGreaterThan(0);
    expect(small(sw)).toEqual([]);
  });
});
