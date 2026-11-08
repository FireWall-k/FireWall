import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, renderHook, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { DEFAULT_A11Y_PREFS, type HelpOut, type HistoryCard } from "../../src/api";
import { NetworkError } from "../../src/apiErrors";
import { COPY } from "../../src/worker/copy";
import { HistoryDetailScreen, HistoryScreen } from "../../src/worker/HistoryScreen";
import { HELP_POLL_MS, useHelp } from "../../src/worker/hooks/useHelp";
import { ProgressDots } from "../../src/worker/ProgressDots";
import { jobProgress } from "../../src/worker/resume";
import { SessionContext, type WorkerSessionValue } from "../../src/worker/session";
import { normalizeJob, workerApi, type TodayJob } from "../../src/worker/workerApi";

// 3차 검증 반영(근로자 화면): 다른 단계에서 부른 도움, 했던 일 화면의 못 보낸 기록.
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const help = (state: HelpOut["state"], over: Partial<HelpOut> = {}): HelpOut => ({
  id: "h1", assignment_id: "a1", step_id: "s3", step_order: 3, state, resolution: null,
  created_at: "2026-11-09T01:00:00", acknowledged_at: null, cancelled_at: null, resolved_at: null, ...over,
});

function fakeApi(over: Record<string, ReturnType<typeof vi.fn>> = {}) {
  return {
    createHelp: vi.fn().mockResolvedValue(help("open")),
    getHelp: vi.fn().mockResolvedValue(help("open")),
    cancelHelp: vi.fn().mockResolvedValue(help("cancelled")),
    cancelHelpByClient: vi.fn().mockResolvedValue(help("cancelled")),
    ...over,
  };
}

describe("useHelp 3차: [이전] 뒤 다른 단계를 끝내도 도움 띠는 남는다(서버와 같은 규칙)", () => {
  it("3단계에서 부르고 2단계를 끝내면 띠·상태 확인이 그대로, 확인되면 '선생님이 확인했어요'", async () => {
    vi.useFakeTimers();
    const api = fakeApi();
    const { result, rerender } = renderHook(({ step }) => useHelp({ assignmentId: "a1", stepId: step, api }), {
      initialProps: { step: "s3" },
    });
    act(() => result.current.request());
    await act(async () => {});
    expect(result.current.phase).toBe("sent");
    rerender({ step: "s2" }); // [이전]
    act(() => result.current.markStepDone("s2"));
    expect(result.current.phase).toBe("sent");
    api.getHelp.mockResolvedValue(help("acknowledged", { acknowledged_at: "2026-11-09T01:01:00" }));
    await act(async () => {
      vi.advanceTimersByTime(HELP_POLL_MS);
    });
    expect(result.current.phase).toBe("acked");
  });

  it("부른 단계를 끝내거나 단계 없이 부른 요청이면 띠를 닫는다", async () => {
    const api = fakeApi();
    const { result } = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s3", api }));
    act(() => result.current.request());
    await act(async () => {});
    act(() => result.current.markStepDone("s3"));
    expect(result.current.phase).toBe("idle");

    const api2 = fakeApi({ createHelp: vi.fn().mockResolvedValue(help("open", { step_id: null })) });
    const r2 = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s3", api: api2 }));
    act(() => r2.result.current.request());
    await act(async () => {});
    act(() => r2.result.current.markStepDone("s2"));
    expect(r2.result.current.phase).toBe("idle");
  });
});

// --- 했던 일: 못 보낸 기록도 '다 했어요' ---
const step = (id: string, order: number) => ({
  id, order, sentence: `${order}단계 문장`, action_type: null, symbol_url: "/x.webp", symbol_source: "LOCAL_AAC",
  symbol_label: null, tts_audio_url: null, picture_state: "auto",
});
const steps = [step("s1", 1), step("s2", 2)];
const card: HistoryCard = {
  assignment_id: "a1", task_id: "t1", task_title: "컵 씻기", assigned_date: "2026-11-09", status: "in_progress",
  steps: [{ ...steps[0], completed: true }, { ...steps[1], completed: false }],
} as HistoryCard;

function value(local: string[], jobs: TodayJob[] = []): WorkerSessionValue {
  const p = { ...DEFAULT_A11Y_PREFS, autoplay_sound: false };
  return {
    me: { id: "w1", display_name: "민수", workplace_name: "행복카페", teacher_title: "선생님", a11y_prefs: p },
    prefs: p, jobs, online: true, synced: false, pendingCount: local.length, unsentNote: null,
    refresh: async () => {}, progressOf: (j) => jobProgress(j.steps, new Set()), localDoneIds: () => local,
    completeStep: () => {}, onMediaError: () => {}, logout: () => {}, reportError: () => {},
  };
}

function renderAt(path: string, v: WorkerSessionValue) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SessionContext.Provider value={v}>
        <Routes>
          <Route path="/w/history" element={<HistoryScreen />} />
          <Route path="/w/history/:aid" element={<HistoryDetailScreen />} />
        </Routes>
      </SessionContext.Provider>
    </MemoryRouter>,
  );
}

describe("했던 일 3차: 대기열·이 화면에서 끝낸 단계를 서버 기록과 합친다", () => {
  it("마지막 [다 했어요] 기록이 아직 대기열에 있어도 카드는 '다 했어요'", async () => {
    vi.spyOn(workerApi, "history").mockResolvedValue([card]);
    renderAt("/w/history", value(["s2"]));
    expect(await screen.findByText("컵 씻기")).toBeTruthy();
    expect(screen.getByText(COPY.card.done)).toBeTruthy();
    expect(screen.queryByText(COPY.card.stopped)).toBeNull();
  });

  it("대기열이 비어 있으면 서버 기록대로 '하다가 멈췄어요'", async () => {
    vi.spyOn(workerApi, "history").mockResolvedValue([card]);
    renderAt("/w/history", value([]));
    expect(await screen.findByText(COPY.card.stopped)).toBeTruthy();
  });

  it("인터넷이 끊겨도 받아 둔 오늘 할 일로 방금 끝낸 일을 다시 볼 수 있다", async () => {
    vi.spyOn(workerApi, "history").mockRejectedValue(new NetworkError());
    const job = normalizeJob({ assignment_id: "a1", task_id: "t1", task_title: "컵 씻기", steps, done_step_ids: ["s1"] });
    renderAt("/w/history/a1", value(["s2"], [job]));
    expect(await screen.findByText("1단계 문장")).toBeTruthy();
  });
});

describe("진행 칸 막대(13단계 이상) 3차", () => {
  it("지금 칸은 주황(도움 색)이 아니라 초록 테두리 + 더 큰 높이로 보인다", () => {
    render(<ProgressDots total={14} current={4} done={(i) => i < 4} />);
    const cells = screen.getByTestId("progress-dots").querySelectorAll("span");
    expect(cells).toHaveLength(14);
    const cur = cells[4];
    expect(cur.getAttribute("data-state")).toBe("current");
    expect(cur.className).toContain("border-worker-primary");
    expect(cur.className).toContain("h-5");
    for (const c of cells) expect(c.className).not.toContain("help");
    expect(cells[0].className).toContain("bg-worker-primary");
    expect(cells[0].className).toContain("h-3");
  });
});
