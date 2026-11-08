import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { COPY } from "../../src/worker/copy";
import { Outbox, resetOutboxRegistry } from "../../src/worker/outbox";
import { useWorkerSession } from "../../src/worker/session";
import { WorkerSession } from "../../src/worker/WorkerSession";
import type { LogBody } from "../../src/worker/workerApi";

// 4차 검증 반영(근로자 화면): 첫 401이 [다 했어요] 기록일 때도 '다시 들어와 주세요', 대기열이 보낸 시각을 싣는다.
const setLogin = (t: string) => {
  localStorage.setItem("jobcard_token", t);
  localStorage.setItem("jobcard_role", "worker");
  localStorage.setItem("jobcard_name", "민수");
};
const json = (b: unknown, status = 200) =>
  new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
const me = { id: "w1", display_name: "민수", workplace_name: "카페", teacher_title: "선생님", a11y_prefs: {} };
const st = (id: string, order: number) => ({
  id, order, sentence: `${order}단계`, action_type: null, symbol_url: null, symbol_source: "LOCAL_AAC",
  needs_fallback: false, tts_audio_url: null, picture_state: "auto",
});
const job = { assignment_id: "a1", task_id: "t1", task_title: "컵 씻기", steps: [st("s1", 1), st("s2", 2)], done_step_ids: [], status: "new" };

let tokenValid = true;
beforeEach(() => {
  localStorage.clear();
  resetOutboxRegistry();
  tokenValid = true;
  globalThis.fetch = vi.fn(async (u: RequestInfo | URL) => {
    const url = String(u);
    if (!tokenValid) return json({ detail: "접속 코드가 바뀌었습니다." }, 401);
    if (url.includes("/api/worker/me/today")) return json([job]);
    if (url.includes("/api/worker/me")) return json(me);
    if (url.includes("/api/performance-logs")) return json({ ok: true, assignment_status: "in_progress", duplicate: false, applied: true }, 201);
    return json({}, 404);
  }) as typeof fetch;
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function Probe() {
  const s = useWorkerSession();
  return (
    <button onClick={() => s.completeStep(s.jobs[0], s.jobs[0].steps[0] as never, { durationSec: 3, replayCount: 0, stuck: false })}>
      done1
    </button>
  );
}

describe("세션 4차: 첫 401이 [다 했어요] 기록이어도 다시 들어오라고 알린다", () => {
  it("코드를 다시 만든 뒤 [다 했어요] → 저장된 로그인은 지워지고 '다시 들어와 주세요'가 뜬다", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    setLogin("TOKEN_A");
    render(<MemoryRouter><WorkerSession token="TOKEN_A" onLogout={() => {}}><Probe /></WorkerSession></MemoryRouter>);
    await screen.findByText("done1");
    tokenValid = false;
    await act(async () => {
      screen.getByText("done1").click();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(localStorage.getItem("jobcard_token")).toBeNull();
    expect(screen.getByText(COPY.status.expired.title)).toBeTruthy();
    expect(screen.queryByText("done1")).toBeNull();
  });

  it("다른 근로자가 이 기기로 들어온 뒤 앞사람 기록이 401이면 앞사람 화면에 만료를 띄우지 않는다(뒷사람 로그인 유지)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    setLogin("TOKEN_A");
    render(<MemoryRouter><WorkerSession token="TOKEN_A" onLogout={() => {}}><Probe /></WorkerSession></MemoryRouter>);
    await screen.findByText("done1");
    setLogin("TOKEN_B");
    tokenValid = false;
    await act(async () => {
      screen.getByText("done1").click();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(localStorage.getItem("jobcard_token")).toBe("TOKEN_B");
    expect(screen.queryByText(COPY.status.expired.title)).toBeNull();
  });
});

describe("대기열 4차: 보낼 때마다 기기의 지금 시각(client_sent_at)을 싣는다", () => {
  it("끝낸 시각은 그대로, 보낸 시각은 보내는 순간의 값이고 저장본에는 남지 않는다", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-09T01:00:00.000Z"));
    const box = new Outbox("w-sent");
    box.put({ assignment_id: "a1", step_id: "s1", duration_sec: 1, replay_count: 0, stuck: false, completed: true });
    vi.setSystemTime(new Date("2026-11-09T01:01:30.000Z"));
    const sent: LogBody[] = [];
    await box.flush(async (b) => {
      sent.push(b);
    });
    expect(sent).toHaveLength(1);
    expect(sent[0].client_completed_at).toBe("2026-11-09T01:00:00.000Z");
    expect(sent[0].client_sent_at).toBe("2026-11-09T01:01:30.000Z");
    expect(box.size).toBe(0);
  });
});
