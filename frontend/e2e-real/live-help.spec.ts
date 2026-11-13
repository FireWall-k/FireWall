import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

// 2c 오늘 현황과 도움을 실제 백엔드에 붙여 본다(목킹 없음, playwright.real.config.ts 머리말 참고).
// tasks §6 시연 대본: ① 휴대폰에서 [도와주세요] ② 컴퓨터 홈 맨 위 띠 ③ [이 단계 고치기]로 편집기
// ④ 돌아와 [도와줬어요] ⑤ 휴대폰 '선생님이 확인했어요'. 서버 결과(배지·presence·도움 상태)는 API로 직접 확인한다.
// 근로자 화면은 프로젝트 기기(phone 390 / tablet 768), 사업주 화면은 1440폭 창 하나로 돈다.

const API = process.env.REAL_API_BASE ?? "http://127.0.0.1:8100";
const LOGIN = process.env.REAL_EMPLOYER_LOGIN ?? "realboss";
const PASSWORD = process.env.REAL_EMPLOYER_PASSWORD ?? "realtest1234";
const SHOTS = process.env.REAL_C_SHOTS_DIR;
const RAW = "컵을 개수대에 모아요. 컵을 물로 헹궈요. 컵을 건조대에 엎어 놓아요.";

type Step = { id: string; sentence: string; symbol_url: string | null; picture_state?: string };

async function ok<T>(res: Awaited<ReturnType<APIRequestContext["get"]>>): Promise<T> {
  if (!res.ok()) throw new Error(`${res.url()} → ${res.status()} ${await res.text()}`);
  return (await res.json()) as T;
}
const auth = (token: string) => ({ Authorization: `Bearer ${token}` });

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  const dir = `${SHOTS}/${test.info().project.name}`;
  mkdirSync(dir, { recursive: true });
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${dir}/${name}.png` });
}

interface LiveWorker {
  worker_id: string;
  badge: string;
  current: { assignment_id: string; task_id: string; step: { id: string; source_step_id: string | null; order: number } | null } | null;
}
interface Live {
  summary: { working: number; total_workers: number; open_help: number; stuck_steps: number; needs_check_tasks: number };
  workers: LiveWorker[];
  help: { id: string; worker_id: string; state: string; task_id: string | null; source_step_id: string | null }[];
}

test("2c 시연 대본: [도와주세요] → 홈 띠 → [이 단계 고치기] → [도와줬어요] → '선생님이 확인했어요'", async ({ page, request, browser }) => {
  test.setTimeout(180_000);
  const tag = `${test.info().project.name}${Date.now() % 100000}`;
  const employer = (await ok<{ token: string }>(
    await request.post(`${API}/api/auth/login`, { data: { login_id: LOGIN, password: PASSWORD } }),
  )).token;
  const wp = await ok<{ workplace_code: string }>(await request.get(`${API}/api/workplace`, { headers: auth(employer) }));
  const workerName = `현황${tag}`;
  const w = await ok<{ id: string; access_code: string }>(
    await request.post(`${API}/api/workers`, { headers: auth(employer), data: { display_name: workerName } }),
  );
  const task = await ok<{ id: string; title: string; steps: Step[] }>(
    await request.post(`${API}/api/tasks`, { headers: auth(employer), data: { raw_input: RAW, business_type: "카페" } }),
  );
  const fallback = task.steps.find((s) => s.symbol_url)?.symbol_url ?? null;
  for (const s of task.steps) {
    if (s.symbol_url && s.picture_state && s.picture_state !== "none" && s.picture_state !== "confirmed") {
      await ok(await request.post(`${API}/api/tasks/${task.id}/steps/${s.id}/picture/confirm`, { headers: auth(employer) }));
    } else if (!s.symbol_url) {
      const found = await ok<{ matches: { image_url: string }[] }>(
        await request.post(`${API}/api/aac/search`, { headers: auth(employer), data: { query: s.sentence, limit: 3 } }),
      );
      const url = found.matches[0]?.image_url ?? fallback;
      if (!url) throw new Error("붙일 그림을 찾지 못했다");
      await ok(await request.patch(`${API}/api/tasks/${task.id}/steps/${s.id}`, {
        headers: auth(employer), data: { symbol_url: url, symbol_source: "LOCAL_AAC" },
      }));
    }
  }
  await ok(await request.post(`${API}/api/tasks/${task.id}/send`, { headers: auth(employer), data: { worker_ids: [w.id], day: "today" } }));

  // 근로자: 가게 코드 → 번호 → 오늘 → 시작 → 2단계
  await page.goto("/worker/setup");
  await page.getByLabel("가게 코드").fill(wp.workplace_code);
  await page.getByRole("button", { name: "연결하기" }).click();
  await page.getByTestId("keypad").waitFor();
  for (const d of w.access_code) await page.getByRole("button", { name: d, exact: true }).click();
  await expect(page).toHaveURL(/\/worker\/today$/, { timeout: 15_000 });
  await page.getByTestId("job-card").filter({ hasText: task.title }).click();
  await page.getByRole("button", { name: "시작하기" }).click();
  await expect(page).toHaveURL(/\/step\/1$/);
  await page.getByRole("button", { name: "다 했어요" }).click();
  await expect(page).toHaveURL(/\/step\/2$/, { timeout: 10_000 });
  // /w에는 서비스 워커가 없다.
  expect(await page.evaluate(() => navigator.serviceWorker?.controller ?? null)).toBeNull();

  // ① 휴대폰에서 [도와주세요]
  await page.waitForTimeout(700);
  await page.getByTestId("help-button").click();
  await expect(page.getByTestId("help-band-text")).toHaveText("선생님을 불렀어요. 여기서 기다려요.");
  await shot(page, "c1-worker-help");

  // 서버: 배지 help, 지금 단계(presence) = 2단계, 도움 요청에 task_id·source_step_id
  let mine: LiveWorker | undefined;
  await expect.poll(async () => {
    const live = await ok<Live>(await request.get(`${API}/api/employer/live`, { headers: auth(employer) }));
    mine = live.workers.find((x) => x.worker_id === w.id);
    return `${mine?.badge}:${mine?.current?.step?.order}`;
  }, { timeout: 15_000 }).toBe("help:2");
  const live = await ok<Live>(await request.get(`${API}/api/employer/live`, { headers: auth(employer) }));
  const h = live.help.find((x) => x.worker_id === w.id)!;
  expect(h).toMatchObject({ state: "open", task_id: task.id, source_step_id: task.steps[1].id });
  expect(JSON.stringify(live)).not.toMatch(/percent|%/);

  // ② 컴퓨터 홈 맨 위 띠
  const boss = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "ko-KR" });
  const bp = await boss.newPage();
  await bp.goto("/manager/login");
  await bp.getByLabel("아이디").fill(LOGIN);
  await bp.getByLabel("비밀번호").fill(PASSWORD);
  await bp.getByLabel("비밀번호").press("Enter");
  await expect(bp).toHaveURL(/\/manager(\?|$)/, { timeout: 15_000 });
  const item = bp.getByTestId("help-band-item").filter({ hasText: workerName });
  await expect(item).toContainText(`${workerName} 님이 도움을 요청했어요`, { timeout: 15_000 });
  await expect(item).toContainText("2단계");
  await expect(bp.getByTestId("live-status-line")).toContainText("마지막 갱신");
  const row = bp.getByRole("row").filter({ hasText: workerName });
  await expect(row).toContainText("도움 요청");
  if (SHOTS) {
    mkdirSync(`${SHOTS}/${test.info().project.name}`, { recursive: true });
    await bp.screenshot({ path: `${SHOTS}/${test.info().project.name}/c2-employer-home-band.png` });
  }

  // ③ [이 단계 고치기] → 편집기 그 단계(1번)
  await item.getByRole("button", { name: "이 단계 고치기" }).click();
  await expect(bp).toHaveURL((u) => u.pathname === `/manager/tasks/${task.id}` && u.searchParams.get("step") === task.steps[1].id);

  // ④ 돌아와 [도와줬어요]
  await bp.goBack();
  await expect(bp).toHaveURL(/\/manager(\?|$)/);
  await bp.getByTestId("help-band-item").filter({ hasText: workerName }).getByRole("button", { name: "도와줬어요" }).click();
  await expect(bp.getByTestId("help-band-item").filter({ hasText: workerName })).toHaveCount(0);
  // 서버에서 닫혔다(도움 목록은 캐시 없음). 현황(live)은 사업장마다 4초 저장분이라 다음 주기에 빠진다.
  await expect.poll(async () => {
    const act = await ok<{ id: string }[]>(await request.get(`${API}/api/employer/help?state=active`, { headers: auth(employer) }));
    return act.some((x) => x.id === h.id);
  }, { timeout: 10_000 }).toBe(false);
  await expect.poll(async () => {
    const lv = await ok<Live>(await request.get(`${API}/api/employer/live`, { headers: auth(employer) }));
    return lv.help.some((x) => x.id === h.id);
  }, { timeout: 10_000 }).toBe(false);

  // ⑤ 휴대폰 '선생님이 확인했어요'
  await page.bringToFront();
  await expect(page.getByText("선생님이 확인했어요")).toBeVisible({ timeout: 15_000 });
  await shot(page, "c5-worker-acked");
  await boss.close();
});
