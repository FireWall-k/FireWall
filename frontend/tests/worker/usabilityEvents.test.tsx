import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { DEFAULT_A11Y_PREFS, type HelpOut, type Step } from "../../src/api";
import {
  HELD_MAX,
  discardWorkerEvents,
  flushWorkerEvents,
  resetWorkerEventsForTest,
  trackWorkerEvent,
} from "../../src/worker/hooks/usePresence";
import { useHelp } from "../../src/worker/hooks/useHelp";
import { PRAISE_MS, StepPlayer, type StepPlayerProps } from "../../src/worker/StepPlayer";
import { PrimaryAction } from "../../src/worker/ui/WorkerButton";
import type { WorkerEvent } from "../../src/worker/workerApi";

// 3b-1 사용 측정 이벤트(명세 8.4): tap_debounced·exit_confirm·exit_cancel·help_cancel, 배정 id·숫자 값,
// 끊긴 동안 메모리에 두기(기기 저장 없음).

beforeEach(() => {
  resetWorkerEventsForTest();
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => {
  vi.useRealTimers();
});

const steps: Step[] = [
  { id: "s1", order: 1, sentence: "컵을 물에 넣어요", action_type: "other", symbol_url: null, symbol_source: "fallback", needs_fallback: true, tts_audio_url: null },
  { id: "s2", order: 2, sentence: "컵을 닦아요", action_type: "other", symbol_url: null, symbol_source: "fallback", needs_fallback: true, tts_audio_url: null },
];

function props(over: Partial<StepPlayerProps> = {}): StepPlayerProps {
  return {
    mode: "live", title: "컵 씻기", steps, index: 1, doneIds: new Set(), prefs: { ...DEFAULT_A11Y_PREFS, autoplay_sound: false },
    onDone: vi.fn(), onRecord: vi.fn(), onPrev: vi.fn(), onExit: vi.fn(), onSignal: vi.fn(), onEvent: vi.fn(), ...over,
  };
}

const names = (fn: ReturnType<typeof vi.fn>) => fn.mock.calls.map((c) => c[0]);

describe("tap_debounced: 600ms 중복 방지에 걸린 누름", () => {
  it("버튼은 걸린 누름마다 onDebounced를 부르고 onPress는 한 번", () => {
    vi.useFakeTimers();
    const onPress = vi.fn();
    const onDebounced = vi.fn();
    render(<PrimaryAction onPress={onPress} onDebounced={onDebounced}>다 했어요</PrimaryAction>);
    const b = screen.getByRole("button", { name: "다 했어요" });
    fireEvent.click(b);
    act(() => vi.advanceTimersByTime(200));
    fireEvent.click(b);
    act(() => vi.advanceTimersByTime(500));
    fireEvent.click(b);
    act(() => vi.advanceTimersByTime(200));
    fireEvent.click(b);
    expect(onPress).toHaveBeenCalledTimes(2);
    expect(onDebounced).toHaveBeenCalledTimes(2);
  });

  it("단계 화면 [다 했어요] 두 번 → step 하나 기록 + tap_debounced 한 번", () => {
    vi.useFakeTimers();
    const p = props();
    render(<StepPlayer {...p} />);
    const b = screen.getByRole("button", { name: "다 했어요" });
    fireEvent.click(b);
    act(() => vi.advanceTimersByTime(100));
    fireEvent.click(b);
    expect(p.onRecord).toHaveBeenCalledTimes(1);
    expect(p.onEvent).toHaveBeenCalledWith("tap_debounced", steps[1]);
    act(() => vi.advanceTimersByTime(PRAISE_MS));
  });

  it("다시 보기(review)에서는 남기지 않는다", () => {
    vi.useFakeTimers();
    const p = props({ mode: "review", onNext: vi.fn(), index: 0 });
    render(<StepPlayer {...p} />);
    const b = screen.getByRole("button", { name: "다음" });
    fireEvent.click(b);
    act(() => vi.advanceTimersByTime(100));
    fireEvent.click(b);
    expect(p.onEvent).not.toHaveBeenCalled();
  });
});

describe("exit_confirm·exit_cancel: [나가기] 확인 창", () => {
  it("'계속할래요'는 exit_cancel, '멈출래요'는 exit_confirm + 나가기", () => {
    vi.useFakeTimers();
    const p = props();
    render(<StepPlayer {...p} />);
    fireEvent.click(screen.getByRole("button", { name: "나가기" }));
    fireEvent.click(screen.getByRole("button", { name: "계속할래요" }));
    expect(p.onExit).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(700));
    fireEvent.click(screen.getByRole("button", { name: "나가기" }));
    fireEvent.click(screen.getByRole("button", { name: "멈출래요" }));
    expect(p.onExit).toHaveBeenCalledTimes(1);
    const ev = names(p.onEvent as ReturnType<typeof vi.fn>).filter((n) => n.startsWith("exit_"));
    expect(ev).toEqual(["exit_cancel", "exit_confirm"]);
  });
});

describe("help_cancel: 띠 [취소]", () => {
  const help = (state: HelpOut["state"]): HelpOut => ({
    id: "h1", assignment_id: "a1", step_id: "s1", step_order: 1, state, resolution: null,
    created_at: "2026-11-09T01:00:00", acknowledged_at: null, cancelled_at: null, resolved_at: null,
  });
  it("[취소]를 누르면 onCancel 한 번", async () => {
    const api = {
      createHelp: vi.fn().mockResolvedValue(help("open")),
      getHelp: vi.fn().mockResolvedValue(help("open")),
      cancelHelp: vi.fn().mockResolvedValue(help("cancelled")),
      cancelHelpByClient: vi.fn().mockResolvedValue(help("cancelled")),
    };
    const onCancel = vi.fn();
    const { result } = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api, onCancel }));
    act(() => result.current.request());
    await act(async () => {});
    expect(onCancel).not.toHaveBeenCalled();
    act(() => result.current.cancel());
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(api.cancelHelp).toHaveBeenCalledWith("h1");
  });
});

describe("이벤트 칸과 끊긴 동안", () => {
  it("배정 id·숫자 값을 싣고, 이름·문장 칸은 없다", () => {
    const send = vi.fn().mockResolvedValue(undefined);
    trackWorkerEvent("step_done", { task_id: "t1", step_id: "s1", assignment_id: "a1", value_num: 12.3 }, true);
    flushWorkerEvents(send);
    const [e] = send.mock.calls[0][0] as WorkerEvent[];
    expect(Object.keys(e).sort()).toEqual(["assignment_id", "at", "name", "step_id", "task_id", "value_num"]);
    expect(e).toMatchObject({ name: "step_done", assignment_id: "a1", value_num: 12.3 });
  });

  it("끊긴 동안은 보내지 않고(타이머 없음) 다음 연결된 기록 때 함께, 기기 저장소에는 쓰지 않는다", () => {
    vi.useFakeTimers();
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    trackWorkerEvent("offline_queued", { assignment_id: "a1" }, false);
    trackWorkerEvent("step_done", { assignment_id: "a1", value_num: 3 }, false);
    expect(vi.getTimerCount()).toBe(0);
    trackWorkerEvent("offline_flushed", { value_num: 1 }, true);
    expect(vi.getTimerCount()).toBe(1);
    const send = vi.fn().mockResolvedValue(undefined);
    flushWorkerEvents(send);
    expect((send.mock.calls[0][0] as WorkerEvent[]).map((e) => e.name)).toEqual(["offline_queued", "step_done", "offline_flushed"]);
    expect(setItem).not.toHaveBeenCalled();
    setItem.mockRestore();
  });

  it(`끊긴 동안은 최대 ${HELD_MAX}건(오래된 것부터 버림), 나가면 버린다`, () => {
    for (let i = 0; i < HELD_MAX + 5; i++) trackWorkerEvent("step_view", { step_id: `s${i}` }, false);
    const send = vi.fn().mockResolvedValue(undefined);
    flushWorkerEvents(send);
    const all = send.mock.calls.flatMap((c) => c[0] as WorkerEvent[]);
    expect(all).toHaveLength(HELD_MAX);
    expect(all[0].step_id).toBe("s5");
    trackWorkerEvent("step_view", { step_id: "x" }, false);
    discardWorkerEvents();
    const send2 = vi.fn();
    flushWorkerEvents(send2);
    expect(send2).not.toHaveBeenCalled();
  });
});
