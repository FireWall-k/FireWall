import { expect, test, type APIRequestContext, type Locator } from "@playwright/test";

// 클릭 수 완료 기준(tasks §4.4·4.5, 명세 3.4-A 목표 8번 이하)을 실제 서버로 증명한다(목킹 없음,
// playwright.real.config.ts 머리말대로 규칙 모드 AI 하네스·키 없음 — 유료 호출 없음).
// 고정 문장(p2/b1_fixed_sentence.txt)은 규칙 엔진만으로 6단계 모두 auto_high가 된다.
// [새 직무] → [단계로 나누기] → [이대로 그림 고르기] → [그림 한눈에] → [보이는 자동 그림 모두 맞아요] → [보내기] →
// [1명에게 보내기] = 7번. 글자 넣기는 클릭으로 세지 않는다.
// 받는 사람은 '사업장에서 마지막으로 보낸 사람'으로 미리 체크된다(contract §3.6) — 시험 앞에서 새 근로자 한 명에게
// 다른 직무를 API로 보내 두어, 실제 DB에 다른 근로자가 있어도 1명이 미리 체크되게 한다.

const API = process.env.REAL_API_BASE ?? "http://127.0.0.1:8100";
const LOGIN = process.env.REAL_EMPLOYER_LOGIN ?? "realboss";
const PASSWORD = process.env.REAL_EMPLOYER_PASSWORD ?? "realtest1234";
const FIXED_SENTENCE =
  "커터칼로 상자를 열어요. 상품을 선반에 놓아요. 같은 상품끼리 모아요. 테이블을 행주로 닦아요. 바닥을 빗자루로 쓸어요. 손을 씻어요.";

const auth = (token: string) => ({ Authorization: `Bearer ${token}` });

async function ok<T>(res: Awaited<ReturnType<APIRequestContext["get"]>>): Promise<T> {
  if (!res.ok()) throw new Error(`${res.url()} → ${res.status()} ${await res.text()}`);
  return (await res.json()) as T;
}

type Step = { id: string; picture_state: string };

test("실제 서버: 고정 문장은 6단계 모두 auto_high이고, [새 직무]부터 보내기까지 클릭 7번", async ({ page, request }) => {
  test.skip(test.info().project.name !== "tablet", "넓은 화면에서 한 번만 본다");
  await page.setViewportSize({ width: 1440, height: 900 });
  const token = (await ok<{ token: string }>(
    await request.post(`${API}/api/auth/login`, { data: { login_id: LOGIN, password: PASSWORD } }),
  )).token;

  // 받는 사람 한 명을 '사업장에서 마지막으로 보낸 사람'으로 만들어 둔다.
  const w = await ok<{ id: string; display_name: string }>(
    await request.post(`${API}/api/workers`, { headers: auth(token), data: { display_name: `클릭${Date.now() % 100000}` } }),
  );
  const prep = await ok<{ id: string; steps: Step[] }>(
    await request.post(`${API}/api/tasks`, { headers: auth(token), data: { raw_input: FIXED_SENTENCE } }),
  );
  await ok(await request.post(`${API}/api/tasks/${prep.id}/pictures/confirm`, {
    headers: auth(token), data: { step_ids: prep.steps.filter((s) => s.picture_state === "auto_high").map((s) => s.id) },
  }));
  await ok(await request.post(`${API}/api/tasks/${prep.id}/send`, {
    headers: auth(token), data: { worker_ids: [w.id], day: "today" },
  }));

  await page.addInitScript((t) => {
    localStorage.setItem("jobcard_token", t);
    localStorage.setItem("jobcard_role", "employer");
    localStorage.setItem("jobcard_name", "통합 카페");
  }, token);
  await page.goto("/m/tasks");

  const seen: string[] = [];
  const click = async (l: Locator, label: string) => {
    await expect(l).toBeVisible({ timeout: 60_000 });
    await l.click();
    seen.push(label);
  };

  await click(page.getByRole("link", { name: "새 직무" }).first(), "새 직무");
  await page.getByLabel("어떤 일을 시킬까요?").fill(FIXED_SENTENCE);
  await click(page.getByRole("button", { name: "단계로 나누기" }), "단계로 나누기");
  await click(page.getByRole("button", { name: "이대로 그림 고르기" }), "이대로 그림 고르기");
  await expect(page.getByTestId("task-editor")).toBeVisible({ timeout: 60_000 });

  // 서버 상태로 확인: 6단계 모두 auto_high.
  const taskId = decodeURIComponent(page.url().split("/").pop() ?? "");
  const created = await ok<{ steps: Step[] }>(await request.get(`${API}/api/tasks/${taskId}`, { headers: auth(token) }));
  expect(created.steps.map((s) => s.picture_state)).toEqual(Array(6).fill("auto_high"));

  await click(page.getByRole("button", { name: "그림 한눈에" }), "그림 한눈에");
  await expect(page.getByTestId("confirm-all")).not.toHaveAttribute("aria-disabled", "true", { timeout: 30_000 });
  await click(page.getByTestId("confirm-all"), "보이는 자동 그림 모두 맞아요");
  await click(page.getByTestId("picture-overview").getByRole("button", { name: "보내기" }), "보내기");
  const sheet = page.getByRole("dialog", { name: "보내기 전에 확인해요" });
  await expect(sheet.getByRole("checkbox", { name: new RegExp(`${w.display_name} 님`) })).toBeChecked({ timeout: 30_000 });
  await click(sheet.getByRole("button", { name: "1명에게 보내기" }), "1명에게 보내기");
  await expect(page.getByText("1명에게 보냈어요")).toBeVisible({ timeout: 30_000 });

  expect(seen).toHaveLength(7);
  // 서버에도 그 근로자에게 보낸 버전 1이 있다.
  const recipients = await ok<{ last_batch_worker_ids: string[] }>(
    await request.get(`${API}/api/tasks/${taskId}/recipients`, { headers: auth(token) }),
  );
  expect(recipients.last_batch_worker_ids).toEqual([w.id]);
});
