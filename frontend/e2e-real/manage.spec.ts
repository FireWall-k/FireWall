import { expect, test, type APIRequestContext } from "@playwright/test";

// 2d 시연 대본(tasks §7)을 실제 서버로 돈다(목킹 없음).
// ① [근로자 추가] → 4자리 번호·인쇄 카드 ② 설정에서 QR ③ 휴대폰으로 /worker?site= 열기 → 번호만 넣으면 들어감
// ④ 화면 설정에서 말 속도 0.8 ⑤ 근로자 화면 목소리가 0.8로 느려짐(오디오 playbackRate 또는 브라우저 음성 rate).

const API = process.env.REAL_API_BASE ?? "http://127.0.0.1:8100";
const LOGIN = process.env.REAL_EMPLOYER_LOGIN ?? "realboss";
const PASSWORD = process.env.REAL_EMPLOYER_PASSWORD ?? "realtest1234";

async function ok<T>(res: Awaited<ReturnType<APIRequestContext["get"]>>): Promise<T> {
  if (!res.ok()) throw new Error(`${res.url()} → ${res.status()} ${await res.text()}`);
  return (await res.json()) as T;
}
const auth = (t: string) => ({ Authorization: `Bearer ${t}` });

test.describe("2d 관리 화면(실제 서버)", () => {
  test("시연 대본: 근로자 추가 → QR 주소 → /worker?site=로 번호만 넣고 들어감 → 말 속도 0.8 → 느려진 목소리", async ({
    page,
    request,
    browser,
  }) => {
    const tag = `${Date.now() % 100000}`;
    const name = `관리${tag}`;
    const tok = await ok<{ token: string; role: string; display_name: string }>(
      await request.post(`${API}/api/auth/login`, { data: { login_id: LOGIN, password: PASSWORD } }),
    );
    const employer = tok.token;

    // ① 사업주 로그인(화면) → 근로자 → [근로자 추가하기]
    await page.goto("/manager/login");
    await page.getByLabel("아이디").fill(LOGIN);
    await page.getByLabel("비밀번호").fill(PASSWORD);
    await page.getByLabel("비밀번호").press("Enter");
    await expect(page).toHaveURL(/\/manager(\?|$)/, { timeout: 15_000 });
    // 메뉴 '근로자'(390은 아래 탭바)
    const nav = (page.viewportSize()?.width ?? 0) < 768 ? page.getByTestId("mobile-tabbar") : page.getByTestId("sidebar");
    await nav.getByRole("link", { name: "근로자" }).click();
    await expect(page).toHaveURL(/\/manager\/workers$/);
    await page.getByRole("button", { name: "근로자 추가하기" }).click();
    await page.getByRole("dialog").getByLabel(/이름/).fill(name);
    await page.getByRole("dialog").getByRole("button", { name: "추가하기" }).click();
    const codeEl = page.getByTestId("new-worker-code");
    await expect(codeEl).toHaveText(/^\d{4}$/);
    const code = (await codeEl.textContent())!.trim();
    await page.getByRole("button", { name: "인쇄용 카드 만들기" }).click();
    await expect(page.getByTestId("qr-code").first()).toBeVisible();
    await page.keyboard.press("Escape");

    // 목록 응답에는 전체 번호가 없다.
    const listText = await (await request.get(`${API}/api/workers`, { headers: auth(employer) })).text();
    expect(listText).not.toContain(`"access_code"`);
    const workers = JSON.parse(listText) as { id: string; display_name: string }[];
    const workerId = workers.find((w) => w.display_name === name)!.id;

    // ② 설정 → 기기 연결 주소·QR
    await page.goto("/manager/settings");
    await expect(page.getByTestId("qr-code").first()).toBeVisible();
    const link = (await page.getByTestId("device-link").textContent())!.trim();
    const wp = await ok<{ workplace_code: string; device_link: string }>(
      await request.get(`${API}/api/workplace`, { headers: auth(employer) }),
    );
    expect(link).toBe(wp.device_link);
    expect(link.endsWith(`/worker?site=${wp.workplace_code}`)).toBe(true);

    // 그림 붙인 2단계 직무를 만들어 보낸다(API).
    const task = await ok<{ id: string; steps: { id: string; sentence: string; symbol_url: string | null; picture_state?: string }[] }>(
      await request.post(`${API}/api/tasks`, {
        headers: auth(employer),
        data: { raw_input: "테이블을 행주로 닦아요. 쓰레기통을 비워요.", business_type: "카페" },
      }),
    );
    const fallback = task.steps.find((s) => s.symbol_url)?.symbol_url ?? null;
    for (const s of task.steps) {
      if (s.symbol_url && s.picture_state && s.picture_state !== "none" && s.picture_state !== "confirmed") {
        await ok(await request.post(`${API}/api/tasks/${task.id}/steps/${s.id}/picture/confirm`, { headers: auth(employer) }));
      } else if (!s.symbol_url) {
        const found = await ok<{ matches: { image_url: string }[] }>(
          await request.post(`${API}/api/aac/search`, { headers: auth(employer), data: { query: s.sentence, limit: 3 } }),
        );
        await ok(
          await request.patch(`${API}/api/tasks/${task.id}/steps/${s.id}`, {
            headers: auth(employer),
            data: { symbol_url: found.matches[0]?.image_url ?? fallback, symbol_source: "LOCAL_AAC" },
          }),
        );
      }
    }
    await ok(await request.post(`${API}/api/tasks/${task.id}/publish`, { headers: auth(employer) }));
    const asg = await ok<{ id: string }[]>(
      await request.post(`${API}/api/tasks/${task.id}/assignments`, { headers: auth(employer), data: { worker_id: workerId } }),
    );

    // ④ 근로자 상세 → 화면 설정 → 말 속도 '느리게 0.8'
    await page.goto(`/manager/workers/${workerId}`);
    await page.getByRole("tab", { name: "화면 설정" }).click();
    await page.getByText("느리게 0.8").click();
    await expect(page.getByText("저장했어요").first()).toBeVisible();
    await expect
      .poll(async () => {
        const all = await ok<{ id: string; a11y_prefs: { tts_rate?: number } }[]>(
          await request.get(`${API}/api/workers`, { headers: auth(employer) }),
        );
        return all.find((x) => x.id === workerId)?.a11y_prefs.tts_rate;
      })
      .toBe(0.8);

    // ③ 새 기기(휴대폰)에서 /worker?site=CODE → 가게 코드 입력 없이 번호만
    const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: "ko-KR", isMobile: true, hasTouch: true });
    const w = await phone.newPage();
    await w.addInitScript(() => {
      const rates: number[] = [];
      (window as unknown as { __rates: number[] }).__rates = rates;
      const origPlay = HTMLMediaElement.prototype.play;
      HTMLMediaElement.prototype.play = function (this: HTMLMediaElement) {
        // 소리 잠금 풀기용 무음(data:)은 빼고, 단계 문장 음성만 센다. 서버 음성은 0.9배로 만들어져 있어
        // 화면은 playbackRate = 말 속도 / 0.9로 맞춘다(useStepAudio) — 그래서 0.9를 곱해 말 속도로 되돌린다.
        if (!this.currentSrc.startsWith("data:") && !this.src.startsWith("data:")) rates.push(this.playbackRate * 0.9);
        return origPlay.call(this);
      };
      if ("speechSynthesis" in window) {
        const s = window.speechSynthesis;
        const orig = s.speak.bind(s);
        s.speak = (u: SpeechSynthesisUtterance) => {
          rates.push(u.rate);
          return orig(u);
        };
      }
    });
    const base = new URL(page.url()).origin;
    await w.goto(`${base}/worker?site=${wp.workplace_code}`);
    await w.getByTestId("keypad").waitFor();
    expect(new URL(w.url()).search).toBe("");
    for (const d of code) await w.getByRole("button", { name: d, exact: true }).click();
    await expect(w).toHaveURL(/\/worker\/today$/, { timeout: 15_000 });
    // 로그인 전 화면(번호 넣기 등)은 아직 근로자 설정을 모르므로 기본 0.9로 읽는다. 로그인해 오늘 할 일에 온 뒤부터 센다.
    await w.evaluate(() => {
      (window as unknown as { __rates: number[] }).__rates.length = 0;
    });
    await w.getByTestId("job-card").first().click();
    await expect(w).toHaveURL(new RegExp(`/worker/job/${asg[0].id}$`), { timeout: 15_000 });
    await w.getByRole("button", { name: "시작하기" }).click();
    await expect(w).toHaveURL(new RegExp(`/worker/job/${asg[0].id}/step/1$`), { timeout: 15_000 });
    // ⑤ 목소리 속도: 자동 읽기가 막히면 [듣기]를 누른다.
    await w.waitForTimeout(800);
    let rates = await w.evaluate(() => (window as unknown as { __rates: number[] }).__rates);
    if (rates.length === 0) {
      await w.getByRole("button", { name: /듣기/ }).first().click();
      await w.waitForTimeout(500);
      rates = await w.evaluate(() => (window as unknown as { __rates: number[] }).__rates);
    }
    expect(rates.length).toBeGreaterThan(0);
    for (const r of rates) expect(r).toBeCloseTo(0.8, 5);
    await phone.close();
  });
});
