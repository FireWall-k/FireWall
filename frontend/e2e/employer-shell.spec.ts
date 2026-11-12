import { test, expect, devices } from "@playwright/test";
import { emojiInText, horizontalOverflow, loginEmployer, mockEmployer } from "./employer-mock";

// 사업주 새 틀(2a-1, tasks §3.4): 폭별 배치(사이드바 240·72, 아래 탭바), 가로 스크롤 0, 모든 /m 화면의 도움 띠,
// 옛 주소 넘김, 오류 토스트 유지, 움직임 줄이기, 손가락 기기 44, 이모지 0, 로그인(Enter·390 위 띠 120·blue-700 0),
// 직무 목록 시연 대본(직무 → 확인 필요 → 보관하기 → 보관에서 꺼내기).
// 사업주는 주로 PC로 쓰므로 이 파일은 데스크톱 브라우저로 본다(손가락 기기 시험만 따로 휴대폰으로).
const { defaultBrowserType: _ignored, ...DESKTOP } = devices["Desktop Chrome"];
void _ignored;
test.use({ ...DESKTOP, locale: "ko-KR" });

const WIDTHS = [1440, 1279, 767, 390] as const;
const ROUTES = ["/m", "/m/tasks", "/m/tasks/new", "/m/workers", "/m/settings"] as const;

for (const width of WIDTHS) {
  test.describe(`${width}폭`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 } });

    test("모든 /m 화면: 가로 스크롤 0, 도움 띠 보임, 이모지 0", async ({ page }) => {
      await mockEmployer(page);
      await loginEmployer(page, "/m");
      for (const path of ROUTES) {
        await page.goto(path);
        await expect(page.getByTestId("help-band"), `${path} 도움 띠`).toBeVisible();
        await expect(page.getByTestId("help-band")).toContainText("김민지");
        await page.waitForLoadState("networkidle");
        expect(await horizontalOverflow(page), `${path} 가로 넘침`).toBeLessThanOrEqual(0);
        expect(await emojiInText(page), `${path} 이모지`).toEqual([]);
      }
    });

    test("사이드바·아이콘 모드·아래 탭바", async ({ page }) => {
      await mockEmployer(page);
      await loginEmployer(page, "/m/tasks");
      await expect(page.getByRole("heading", { name: "직무", level: 1 })).toBeVisible();
      const sidebar = page.getByTestId("sidebar");
      const tabbar = page.getByTestId("mobile-tabbar");
      if (width >= 1280) {
        await expect(sidebar).toBeVisible();
        expect((await sidebar.boundingBox())!.width).toBe(240);
        await expect(sidebar.getByText("직무")).toBeVisible();
        await expect(tabbar).toBeHidden();
      } else if (width >= 768) {
        await expect(sidebar).toBeVisible();
        expect((await sidebar.boundingBox())!.width).toBe(72);
        await expect(tabbar).toBeHidden();
      } else {
        await expect(sidebar).toBeHidden();
        await expect(tabbar).toBeVisible();
        await expect(tabbar.getByRole("link", { name: "직무" })).toHaveAttribute("aria-current", "page");
      }
      // '그림'은 파일럿 전까지 메뉴에 없다
      await expect(page.getByRole("link", { name: "그림" })).toHaveCount(0);
    });
  });
}

test("옛 주소는 새 주소로 넘어간다(뒤로 가기에 남지 않음)", async ({ page }) => {
  await mockEmployer(page);
  await loginEmployer(page, "/m");
  for (const [from, to] of [
    ["/manager", "/m/tasks/new"],
    ["/dashboard", "/m"],
    ["/workers", "/m/workers"],
    ["/admin/tasks", "/m/tasks/new"],
    ["/admin/dashboard", "/m"],
  ] as const) {
    await page.goto(from);
    await expect(page, from).toHaveURL(new RegExp(`${to.replace(/\//g, "\\/")}$`));
    await expect(page.getByTestId("sidebar")).toBeVisible();
  }
});

test("로그인 화면: Enter로 로그인해 사업주 홈으로, [로그인]은 44px moss, blue-700 0건", async ({ page }) => {
  await mockEmployer(page);
  await page.goto("/m/login");
  const submit = page.getByRole("button", { name: "로그인", exact: true });
  const box = await submit.boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(44);
  expect(await submit.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgb(72, 97, 63)"); // moss #48613F
  const blue = await page.evaluate(() =>
    Array.from(document.querySelectorAll("*")).filter((el) => {
      const s = getComputedStyle(el);
      return [s.color, s.backgroundColor, s.borderTopColor].includes("rgb(29, 78, 216)");
    }).length,
  );
  expect(blue).toBe(0);
  await page.getByLabel("아이디").fill("boss");
  await page.getByLabel("비밀번호").fill("pw");
  await page.getByLabel("비밀번호").press("Enter");
  await expect(page).toHaveURL(/\/m$/);
  await expect(page.getByTestId("sidebar")).toBeVisible();
});

test.describe("로그인 390", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("왼쪽 소개 패널이 위쪽 120 띠로 접힌다", async ({ page }) => {
    await mockEmployer(page);
    await page.goto("/m/login");
    const band = page.getByTestId("login-intro");
    await expect(band).toBeVisible();
    const b = (await band.boundingBox())!;
    expect(b.height).toBe(120);
    expect(b.y).toBe(0);
    expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0);
  });
});

test("오류 토스트는 10초 뒤에도 남고, 성공 토스트는 저절로 닫힌다", async ({ page }) => {
  await page.clock.install();
  const m = await mockEmployer(page);
  await loginEmployer(page, "/m/tasks");
  await page.getByRole("button", { name: "앞치마 입기 메뉴" }).click();
  await page.getByRole("menuitem", { name: "보관하기" }).click();
  const ok = page.getByText("'앞치마 입기'를 보관함으로 옮겼어요");
  await expect(ok).toBeVisible();
  await page.clock.fastForward(6_000);
  await expect(ok).toBeHidden();

  m.failPaths.add("/api/tasks/t1/archive");
  await page.getByRole("button", { name: "컵 씻기 메뉴" }).click();
  await page.getByRole("menuitem", { name: "보관하기" }).click();
  const err = page.getByText("처리하지 못했어요. 잠시 뒤 다시 시도해 주세요.");
  await expect(err).toBeVisible();
  await page.clock.fastForward(11_000);
  await expect(err).toBeVisible();
});

test("움직임 줄이기: 틀의 전환 시간이 0", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockEmployer(page);
  await loginEmployer(page, "/m/tasks");
  await expect(page.getByRole("tab", { name: /전체/ })).toBeVisible();
  const durations = await page.evaluate(() =>
    Array.from(document.querySelectorAll("a, button, [role=tab]")).map((el) => {
      const s = getComputedStyle(el);
      return [s.transitionDuration, s.animationDuration];
    }),
  );
  expect(durations.length).toBeGreaterThan(5);
  for (const [t, a] of durations) {
    expect(t.split(",").every((x) => parseFloat(x) === 0)).toBe(true);
    expect(a.split(",").every((x) => parseFloat(x) === 0)).toBe(true);
  }
});

test.describe("손가락 기기(휴대폰)", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  test("틀·직무 목록의 버튼·링크가 44 이상", async ({ page }) => {
    await mockEmployer(page);
    await loginEmployer(page, "/m/tasks");
    await expect(page.getByText("컵 씻기")).toBeVisible();
    expect(await page.evaluate(() => matchMedia("(pointer: coarse)").matches)).toBe(true);
    const small = await page.evaluate(() =>
      Array.from(
        document.querySelectorAll<HTMLElement>(
          "header button, header a, nav a, nav button, main button, [role=tab], [data-testid=help-band] button",
        ),
      )
        .filter((el) => el.offsetParent !== null)
        .map((el) => ({ name: el.getAttribute("aria-label") ?? el.textContent?.trim(), h: el.getBoundingClientRect().height }))
        .filter((b) => b.h < 44),
    );
    expect(small).toEqual([]);
    // 도움 띠 단추도 검사에 들어갔는지(띠는 header·main 밖에 있다)
    await expect(page.getByTestId("help-band").getByRole("button", { name: "도와줬어요" })).toBeVisible();
  });

  test("로그인 화면의 단추·링크('근로자 화면으로 ›' 포함)도 44 이상", async ({ page }) => {
    await mockEmployer(page);
    await page.goto("/m/login");
    await expect(page.getByRole("link", { name: /근로자 화면으로/ })).toBeVisible();
    expect(await page.evaluate(() => matchMedia("(pointer: coarse)").matches)).toBe(true);
    const small = await page.evaluate(() =>
      Array.from(document.querySelectorAll<HTMLElement>("a[href], button"))
        .filter((el) => el.offsetParent !== null)
        .map((el) => ({ name: el.getAttribute("aria-label") ?? el.textContent?.trim(), h: el.getBoundingClientRect().height }))
        .filter((b) => b.h < 44),
    );
    expect(small).toEqual([]);
  });

  test("390: 걸러보기 탭 5개가 한 줄에 다 보이고, 도움 띠 글이 좁은 칸에 꺾이지 않는다", async ({ page }) => {
    await mockEmployer(page);
    await loginEmployer(page, "/m/tasks");
    const tablist = page.getByRole("tablist", { name: "직무 걸러보기" });
    await expect(page.getByRole("tab", { name: /보관/ })).toBeVisible();
    const fit = await tablist.evaluate((el) => {
      const box = el.getBoundingClientRect();
      return {
        overflow: el.scrollWidth - el.clientWidth,
        lastRight: el.querySelector<HTMLElement>("[role=tab]:last-child")!.getBoundingClientRect().right,
        boxRight: box.right,
      };
    });
    expect(fit.overflow).toBeLessThanOrEqual(0);
    expect(fit.lastRight).toBeLessThanOrEqual(fit.boxRight);

    // 버튼 줄은 글 아래로 내려가고, '1분 전'은 한 줄로 묶인다
    const strip = page.getByTestId("help-band");
    const text = strip.locator("li p").first();
    const button = strip.getByRole("button", { name: "도와줬어요" });
    const tb = (await text.boundingBox())!;
    const bb = (await button.boundingBox())!;
    expect(bb.y).toBeGreaterThanOrEqual(tb.y + tb.height - 1);
    const timeLines = await strip.locator("li p .tabular-nums").first().evaluate((el) => el.getClientRects().length);
    expect(timeLines).toBe(1);
  });
});

test.describe("직무 목록 시연 대본", () => {
  test.use({ viewport: { width: 1440, height: 900 } });
  test("사이드바 '직무' → '확인 필요' → 보관하기 → 보관에서 꺼내기", async ({ page }) => {
    const m = await mockEmployer(page);
    await loginEmployer(page, "/m");
    await page.getByTestId("sidebar").getByRole("link", { name: "직무" }).click();
    await expect(page).toHaveURL(/\/m\/tasks$/);
    const table = page.getByRole("table", { name: "직무 목록" });
    await expect(table.getByText("컵 씻기")).toBeVisible();

    // 확인 필요: 초안(컵 씻기)과 보낸 직무(택배…)가 함께
    await page.getByRole("tab", { name: /확인 필요/ }).click();
    await expect(page).toHaveURL(/filter=needs_check/);
    await expect(table.getByText("앞치마 입기")).toBeHidden();
    await expect(table.getByText("컵 씻기")).toBeVisible();
    await expect(table.getByText("택배 상자 포장하고 운송장 붙이기")).toBeVisible();
    await expect(table.getByText("고친 내용 안 보냄").filter({ visible: true })).toBeVisible();

    // 한 직무 보관하기(키보드로 메뉴 열기)
    await page.getByRole("button", { name: "컵 씻기 메뉴" }).focus();
    await page.keyboard.press("ArrowDown");
    await page.getByRole("menuitem", { name: "보관하기" }).click();
    await expect(page.getByText("'컵 씻기'를 보관함으로 옮겼어요")).toBeVisible();
    await expect(table.getByText("컵 씻기")).toBeHidden();
    await expect(page.getByRole("tab", { name: /보관/ })).toContainText("2");

    // 보관 필터에서 되살리기
    await page.getByRole("tab", { name: /보관/ }).click();
    await expect(table.getByText("컵 씻기")).toBeVisible();
    await page.getByRole("button", { name: "컵 씻기 메뉴" }).click();
    await page.getByRole("menuitem", { name: "보관함에서 꺼내기" }).click();
    await expect(table.getByText("컵 씻기")).toBeHidden();
    await expect(page.getByRole("tab", { name: /보관/ })).toContainText("1");
    expect(m.calls).toContain("POST /api/tasks/t1/archive");
    expect(m.calls).toContain("POST /api/tasks/t1/unarchive");
  });

  test("완전히 지우기: 보관 걸러보기에서만, 지워지는 것 목록을 확인한 뒤", async ({ page }) => {
    const m = await mockEmployer(page);
    await loginEmployer(page, "/m/tasks?filter=archived");
    await page.getByRole("button", { name: "옛 창고 정리 메뉴" }).click();
    await page.getByRole("menuitem", { name: "완전히 지우기" }).click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("수행 기록과 도움 요청 기록");
    await expect(dialog.getByRole("button", { name: "취소" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("button", { name: "옛 창고 정리 메뉴" })).toBeFocused();
    expect(m.calls.some((c) => c.startsWith("DELETE"))).toBe(false);

    await page.getByRole("button", { name: "옛 창고 정리 메뉴" }).click();
    await page.getByRole("menuitem", { name: "완전히 지우기" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "완전히 지우기" }).click();
    await expect(page.getByText("'옛 창고 정리'를 완전히 지웠어요")).toBeVisible();
    expect(m.calls).toContain("DELETE /api/tasks/t9");
  });
});

test.describe("행동 뒤 키보드 초점(WCAG 2.4.3)", () => {
  test.use({ viewport: { width: 1440, height: 900 } });
  const activeTag = (page: import("@playwright/test").Page) => page.evaluate(() => document.activeElement?.tagName ?? "NONE");

  test("키보드로 보관하기 → 초점이 다음 행 … 단추로, [실행 취소] → 그 직무로 돌아옴", async ({ page }) => {
    await mockEmployer(page);
    await loginEmployer(page, "/m/tasks");
    const table = page.getByRole("table", { name: "직무 목록" });
    await expect(table.getByText("컵 씻기")).toBeVisible();
    await page.getByRole("button", { name: "컵 씻기 메뉴" }).focus();
    await page.keyboard.press("Enter");
    // 꺼 둔 '고치기'도 초점을 받는다(이유를 들을 수 있게)
    await expect(page.getByRole("menuitem", { name: /^고치기/ })).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await expect(page.getByRole("menuitem", { name: "보관하기" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(table.getByText("컵 씻기")).toBeHidden();
    await expect.poll(() => activeTag(page)).not.toBe("BODY");
    await expect(page.locator(":focus")).toHaveAttribute("data-task-menu", /.+/);

    await page.getByRole("button", { name: "실행 취소" }).click();
    await expect(table.getByText("컵 씻기")).toBeVisible();
    await expect(page.getByRole("button", { name: "컵 씻기 메뉴" })).toBeFocused();
  });

  test("완전히 지우기 → 마지막 행이 사라지면 목록 칸으로, 검색 [X] → 검색칸으로", async ({ page }) => {
    await mockEmployer(page);
    await loginEmployer(page, "/m/tasks?filter=archived");
    await page.getByRole("button", { name: "옛 창고 정리 메뉴" }).focus();
    await page.keyboard.press("Enter");
    await page.keyboard.press("End");
    await expect(page.getByRole("menuitem", { name: "완전히 지우기" })).toBeFocused();
    await page.keyboard.press("Enter");
    await page.getByRole("alertdialog").getByRole("button", { name: "완전히 지우기" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "옛 창고 정리 메뉴" })).toHaveCount(0);
    await expect.poll(() => activeTag(page)).not.toBe("BODY");
    await expect(page.getByRole("tabpanel")).toBeFocused();

    const search = page.getByLabel("제목으로 찾기");
    await search.fill("컵");
    await page.getByRole("button", { name: "검색 지우기" }).first().focus();
    await page.keyboard.press("Enter");
    await expect(search).toBeFocused();
    await expect(search).toHaveValue("");
  });
});
