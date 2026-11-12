import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { DEFAULT_A11Y_PREFS, type Step } from "../../src/api";
import { Outbox } from "../../src/worker/outbox";
import {
  PRESENCE_HEARTBEAT_MS,
  WORKER_EVENT_FLUSH_MS,
  flushWorkerEvents,
  resetWorkerEventsForTest,
  trackWorkerEvent,
  usePresence,
} from "../../src/worker/hooks/usePresence";
import { PRAISE_MS, StepPlayer, type StepPlayerProps } from "../../src/worker/StepPlayer";
import type { LogBody } from "../../src/worker/workerApi";

// (2c) 근로자 기기 신호(presence)·측정 이벤트·[이전] 수(prev_count). 화면은 그대로이고 보이는 것이 없다.

function setHidden(hidden: boolean) {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => (hidden ? "hidden" : "visible") });
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeEach(() => {
  vi.useFakeTimers();
  resetWorkerEventsForTest();
});
afterEach(() => {
  setHidden(false);
  vi.useRealTimers();
});

describe("usePresence", () => {
  it("단계를 열 때 보내고, 같은 단계에 머무는 동안 30초마다, 다시 듣기가 늘면 바로 보낸다", () => {
    const send = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => usePresence({ assignmentId: "a1", online: true, send }));
    act(() => result.current({ stepId: "s1", replayCount: 0, prevCount: 0 }));
    expect(send).toHaveBeenCalledTimes(1);
    const first = send.mock.calls[0][0];
    expect(first).toMatchObject({ assignment_id: "a1", step_id: "s1", replay_count: 0, prev_count: 0 });
    expect(typeof first.step_started_at).toBe("string");
    expect(typeof first.client_sent_at).toBe("string");

    act(() => vi.advanceTimersByTime(PRESENCE_HEARTBEAT_MS));
    expect(send).toHaveBeenCalledTimes(2);
    // 같은 단계면 단계를 연 시각은 그대로다(서버가 머문 시간을 잰다).
    expect(send.mock.calls[1][0].step_started_at).toBe(first.step_started_at);

    act(() => result.current({ stepId: "s1", replayCount: 1, prevCount: 0 }));
    expect(send).toHaveBeenCalledTimes(3);
    expect(send.mock.calls[2][0].replay_count).toBe(1);

    vi.setSystemTime(Date.now() + 1000);
    act(() => result.current({ stepId: "s2", replayCount: 0, prevCount: 0 }));
    expect(send.mock.calls[3][0].step_id).toBe("s2");
    expect(send.mock.calls[3][0].step_started_at).not.toBe(first.step_started_at);
  });

  it("오프라인이면 보내지 않고, 연결되면 바로 한 번 보낸다", () => {
    const send = vi.fn().mockResolvedValue(undefined);
    const { result, rerender } = renderHook(({ online }) => usePresence({ assignmentId: "a1", online, send }), {
      initialProps: { online: false },
    });
    act(() => result.current({ stepId: "s1", replayCount: 0, prevCount: 0 }));
    act(() => vi.advanceTimersByTime(PRESENCE_HEARTBEAT_MS * 2));
    expect(send).not.toHaveBeenCalled();
    rerender({ online: true });
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("숨은 탭에서는 보내지 않고, 다시 보이면 바로 보낸다", () => {
    const send = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => usePresence({ assignmentId: "a1", online: true, send }));
    act(() => result.current({ stepId: "s1", replayCount: 0, prevCount: 0 }));
    act(() => setHidden(true));
    act(() => vi.advanceTimersByTime(PRESENCE_HEARTBEAT_MS * 2));
    expect(send).toHaveBeenCalledTimes(1);
    act(() => setHidden(false));
    expect(send).toHaveBeenCalledTimes(2);
  });

  it("실패해도 던지지 않는다(화면에 아무것도 띄우지 않음)", async () => {
    const send = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    const { result } = renderHook(() => usePresence({ assignmentId: "a1", online: true, send }));
    expect(() => act(() => result.current({ stepId: "s1", replayCount: 0, prevCount: 0 }))).not.toThrow();
    await act(async () => {});
    const sync = vi.fn(() => {
      throw new Error("x");
    });
    const h2 = renderHook(() => usePresence({ assignmentId: "a1", online: true, send: sync }));
    expect(() => act(() => h2.result.current({ stepId: "s1", replayCount: 0, prevCount: 0 }))).not.toThrow();
  });
});

describe("근로자 측정 이벤트", () => {
  it("2초 모아 한 번에 보낸다, 오프라인이면 버린다(대기열 없음)", () => {
    const send = vi.fn().mockResolvedValue(undefined);
    trackWorkerEvent("step_view", { task_id: "t1", step_id: "s1" }, true);
    trackWorkerEvent("step_replay", { task_id: "t1", step_id: "s1" }, true);
    trackWorkerEvent("step_prev", { task_id: "t1", step_id: "s1" }, false);
    flushWorkerEvents(send);
    expect(send).toHaveBeenCalledTimes(1);
    expect(send.mock.calls[0][0].map((e: { name: string }) => e.name)).toEqual(["step_view", "step_replay"]);
    // 이름·문장 같은 개인정보 칸이 없다.
    for (const e of send.mock.calls[0][0]) expect(Object.keys(e).sort()).toEqual(["at", "name", "step_id", "task_id"]);
    expect(WORKER_EVENT_FLUSH_MS).toBe(2000);
  });
});

const steps: Step[] = [
  { id: "s1", order: 1, sentence: "컵을 물에 넣어요", action_type: "other", symbol_url: null, symbol_source: "fallback", needs_fallback: true, tts_audio_url: null },
  { id: "s2", order: 2, sentence: "컵을 닦아요", action_type: "other", symbol_url: null, symbol_source: "fallback", needs_fallback: true, tts_audio_url: null },
];

describe("StepPlayer 신호·이벤트·prevCount", () => {
  function props(over: Partial<StepPlayerProps> = {}): StepPlayerProps {
    return {
      mode: "live", title: "컵 씻기", steps, index: 1, doneIds: new Set(), prefs: { ...DEFAULT_A11Y_PREFS, autoplay_sound: false },
      onDone: vi.fn(), onRecord: vi.fn(), onPrev: vi.fn(), onExit: vi.fn(), onSignal: vi.fn(), onEvent: vi.fn(), ...over,
    };
  }

  it("단계를 열면 onSignal·step_view, [이전]은 step_prev + 그 단계 prevCount를 센다", () => {
    const p = props();
    const { rerender } = render(<StepPlayer {...p} />);
    expect(p.onSignal).toHaveBeenLastCalledWith({ step: steps[1], replayCount: 0, prevCount: 0 });
    expect(p.onEvent).toHaveBeenCalledWith("step_view", steps[1]);
    fireEvent.click(screen.getByRole("button", { name: "이전" }));
    expect(p.onPrev).toHaveBeenCalled();
    expect(p.onEvent).toHaveBeenCalledWith("step_prev", steps[1]);
    rerender(<StepPlayer {...p} index={0} />);
    act(() => vi.advanceTimersByTime(700));
    rerender(<StepPlayer {...p} index={1} />);
    expect(p.onSignal).toHaveBeenLastCalledWith({ step: steps[1], replayCount: 0, prevCount: 1 });
    act(() => vi.advanceTimersByTime(700));
    fireEvent.click(screen.getByRole("button", { name: "다 했어요" }));
    expect(p.onRecord).toHaveBeenCalledWith(expect.objectContaining({ prevCount: 1 }));
    act(() => vi.advanceTimersByTime(PRAISE_MS));
  });

  it("다시 보기(review)에서는 신호·이벤트를 보내지 않는다", () => {
    const p = props({ mode: "review", onNext: vi.fn() });
    render(<StepPlayer {...p} />);
    expect(p.onSignal).not.toHaveBeenCalled();
    expect(p.onEvent).not.toHaveBeenCalled();
  });
});

describe("오프라인 대기열은 prev_count를 그대로 실어 보낸다", () => {
  it("put → flush 본문에 prev_count", async () => {
    vi.useRealTimers();
    localStorage.clear();
    const box = new Outbox("w-prev");
    box.put({ assignment_id: "a1", step_id: "s1", duration_sec: 3, replay_count: 0, stuck: false, completed: true, prev_count: 2 });
    const sent: LogBody[] = [];
    await box.flush(async (b) => {
      sent.push(b);
    });
    expect(sent[0].prev_count).toBe(2);
  });
});
