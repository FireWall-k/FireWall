import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getAuth } from "../../src/api";
import { AuthError } from "../../src/apiErrors";
import { Outbox, resetOutboxRegistry } from "../../src/worker/outbox";
import { workerApi } from "../../src/worker/workerApi";

// 3차 검증: 대기열 기록은 대기열 주인(세션을 연 근로자)의 토큰으로 보낸다. 같은 기기에서 다음 근로자가 들어와도
// 앞사람 기록이 뒷사람 토큰으로 가 404로 버려지지 않고, 앞사람 토큰의 401이 뒷사람 로그인을 지우지 않는다.
const setLogin = (token: string) => {
  localStorage.setItem("jobcard_token", token);
  localStorage.setItem("jobcard_role", "worker");
  localStorage.setItem("jobcard_name", token);
};
const base = { duration_sec: 3, replay_count: 0, stuck: false, completed: true };
const ok = () =>
  new Response(JSON.stringify({ ok: true, assignment_status: "in_progress", duplicate: false, applied: true }), {
    status: 201,
  });
const realFetch = globalThis.fetch;

beforeEach(() => {
  localStorage.clear();
  resetOutboxRegistry();
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

const authOf = (init?: RequestInit) => ((init?.headers ?? {}) as Record<string, string>).Authorization;

describe("대기열 토큰 묶기", () => {
  it("다른 탭에서 B가 들어와도 A의 기록은 A 토큰으로 간다", async () => {
    setLogin("TOKEN_A");
    const box = new Outbox("A");
    box.put({ ...base, assignment_id: "asgA", step_id: "s1" });
    setLogin("TOKEN_B");
    const seen: string[] = [];
    globalThis.fetch = vi.fn(async (_u: RequestInfo | URL, init?: RequestInit) => {
      seen.push(authOf(init));
      return ok();
    }) as typeof fetch;
    const r = await box.flush((b) => workerApi.logStep(b, undefined, "TOKEN_A"));
    expect(seen).toEqual(["Bearer TOKEN_A"]);
    expect(r).toMatchObject({ sent: 1, dropped: 0, remaining: 0 });
  });

  it("공용 태블릿: A가 나간 뒤 B가 들어와도 A의 남은 기록은 A 토큰으로 다 간다", async () => {
    setLogin("TOKEN_A");
    const box = new Outbox("A");
    box.put({ ...base, assignment_id: "asgA", step_id: "s1", client_completed_at: "2026-11-09T01:00:00.000Z" });
    box.put({ ...base, assignment_id: "asgA", step_id: "s2", client_completed_at: "2026-11-09T01:01:00.000Z" });
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const calls: string[] = [];
    globalThis.fetch = vi.fn(async (_u: RequestInfo | URL, init?: RequestInit) => {
      calls.push(authOf(init));
      if (calls.length === 1) await gate;
      return authOf(init) === "Bearer TOKEN_A" ? ok() : new Response("{}", { status: 404 });
    }) as typeof fetch;
    const p = box.flush((b) => workerApi.logStep(b, undefined, "TOKEN_A"));
    localStorage.removeItem("jobcard_token");
    setLogin("TOKEN_B");
    release();
    const r = await p;
    expect(calls).toEqual(["Bearer TOKEN_A", "Bearer TOKEN_A"]);
    expect(r).toMatchObject({ sent: 2, dropped: 0, remaining: 0 });
    expect(getAuth()?.token).toBe("TOKEN_B");
  });

  it("앞사람 토큰의 401은 기록을 남기고 멈추며, 뒷사람 로그인을 지우지 않는다", async () => {
    setLogin("TOKEN_A");
    const box = new Outbox("A");
    box.put({ ...base, assignment_id: "asgA", step_id: "s1" });
    setLogin("TOKEN_B");
    globalThis.fetch = vi.fn(async () => new Response("{}", { status: 401 })) as typeof fetch;
    const r = await box.flush((b) => workerApi.logStep(b, undefined, "TOKEN_A"));
    expect(r).toMatchObject({ expired: true, remaining: 1 });
    expect(getAuth()?.token).toBe("TOKEN_B");
    // 저장된 로그인으로 보낸 요청의 401은 예전처럼 로그인을 지운다.
    const err = await workerApi.today().catch((e) => e);
    expect(err).toBeInstanceOf(AuthError);
    expect(getAuth()).toBeNull();
  });
});
