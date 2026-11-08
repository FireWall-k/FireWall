import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { DEFAULT_A11Y_PREFS, type HelpOut, type Step } from "../../src/api";
import { NetworkError } from "../../src/apiErrors";
import { FORBIDDEN_PATTERNS, COPY } from "../../src/worker/copy";
import { HELP_POLL_MS, HELP_SEND_TIMEOUT_MS, useHelp } from "../../src/worker/hooks/useHelp";
import { Outbox, resetOutboxRegistry } from "../../src/worker/outbox";
import { PRAISE_MS, StepPlayer } from "../../src/worker/StepPlayer";
import { cachedJobs, localDay, noteSentInTodayCache, TODAY_CACHE_PREFIX, writeTodayCache } from "../../src/worker/todayCache";
import { ConfirmScreen } from "../../src/worker/ui/ConfirmScreen";
import { LOG_SEND_TIMEOUT_MS, normalizeJob, workerApi, type TodayJob } from "../../src/worker/workerApi";
import { OfflineMark } from "../../src/worker/WorkerScreen";

// 2차 검증 반영(근로자 화면): 도움 흐름의 경쟁 조건, 멈춘 기록 보내기, 기록 잃음, 오래된 목록.
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  resetOutboxRegistry();
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const help = (state: HelpOut["state"], over: Partial<HelpOut> = {}): HelpOut => ({
  id: "h1", assignment_id: "a1", step_id: "s1", step_order: 1, state, resolution: null,
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

describe("useHelp 2차", () => {
  it("[취소] 직후 다시 부르면, 취소가 서버에 닿은 뒤에 새로 부른다", async () => {
    let finishCancel!: (h: HelpOut) => void;
    const api = fakeApi({ cancelHelp: vi.fn(() => new Promise<HelpOut>((r) => { finishCancel = r; })) });
    const { result } = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api }));
    act(() => result.current.request());
    await act(async () => {});
    act(() => result.current.cancel());
    act(() => result.current.request());
    await act(async () => {});
    expect(api.createHelp).toHaveBeenCalledTimes(1); // 아직 취소를 기다린다
    await act(async () => finishCancel(help("cancelled")));
    expect(api.createHelp).toHaveBeenCalledTimes(2);
    expect(result.current.phase).toBe("sent");
  });

  it("근로자가 누르지 않은 '취소됨'이 보이면 말없이 닫지 않고 '아직 못 불렀어요'", async () => {
    vi.useFakeTimers();
    const api = fakeApi();
    const { result } = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api }));
    act(() => result.current.request());
    await act(async () => {});
    api.getHelp.mockResolvedValue(help("cancelled"));
    await act(async () => {
      vi.advanceTimersByTime(HELP_POLL_MS);
    });
    expect(result.current.phase).toBe("failed");
  });

  it("8초 뒤 끊은 누름은 [다 했어요] 때 키로 닫는다(늦게 닿아 사업주 화면에만 남지 않게)", async () => {
    vi.useFakeTimers();
    const hang = vi.fn((_b: unknown, signal?: AbortSignal) =>
      new Promise<HelpOut>((_r, reject) => signal?.addEventListener("abort", () => reject(new DOMException("x", "AbortError")))));
    const api = fakeApi({ createHelp: hang });
    const { result } = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api }));
    act(() => result.current.request());
    await act(async () => {
      vi.advanceTimersByTime(HELP_SEND_TIMEOUT_MS);
    });
    expect(result.current.phase).toBe("failed");
    const clientId = (hang.mock.calls[0][0] as { client_request_id: string }).client_request_id;
    act(() => result.current.markStepDone());
    expect(result.current.phase).toBe("idle");
    expect(api.cancelHelpByClient).toHaveBeenCalledWith({ assignment_id: "a1", step_id: "s1", client_request_id: clientId });
  });

  it("보내는 중 [다 했어요] 뒤 그 요청이 끊기면(답 없음) 키로 닫는다", async () => {
    vi.useFakeTimers();
    const hang = vi.fn((_b: unknown, signal?: AbortSignal) =>
      new Promise<HelpOut>((_r, reject) => signal?.addEventListener("abort", () => reject(new DOMException("x", "AbortError")))));
    const api = fakeApi({ createHelp: hang });
    const { result } = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api }));
    act(() => result.current.request());
    act(() => result.current.markStepDone());
    await act(async () => {
      vi.advanceTimersByTime(HELP_SEND_TIMEOUT_MS);
    });
    expect(api.cancelHelpByClient).toHaveBeenCalledTimes(1);
    expect(result.current.phase).toBe("idle");
  });

  it("들어올 때 열린 요청은 서버에 물어본 뒤 띠를 보인다: 이미 취소됐으면 띠 없음", async () => {
    const api = fakeApi({ getHelp: vi.fn().mockResolvedValue(help("cancelled")) });
    const { result } = renderHook(() =>
      useHelp({ assignmentId: "a1", stepId: "s1", api, initial: { id: "h1", state: "open", step_id: "s1", created_at: "x" } }),
    );
    expect(result.current.phase).toBe("idle");
    await act(async () => {});
    expect(api.getHelp).toHaveBeenCalledWith("h1");
    expect(result.current.phase).toBe("idle");
  });

  it("목록이 아직 옛것이어도(active_help 없음) 이 탭이 부른 요청을 기억해 다시 들어오면 '불렀어요'", async () => {
    const api = fakeApi();
    const first = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api }));
    act(() => first.result.current.request());
    await act(async () => {});
    first.unmount(); // [나가기]
    const again = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api, initial: null }));
    await act(async () => {});
    expect(again.result.current.phase).toBe("sent");
    // [취소]하고 나가면 다시 들어와도 띠가 없다(서버도 취소).
    act(() => again.result.current.cancel());
    again.unmount();
    api.getHelp.mockResolvedValue(help("cancelled"));
    const third = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api, initial: null }));
    await act(async () => {});
    expect(third.result.current.phase).toBe("idle");
  });

  it("'선생님이 확인했어요'는 이 기기에서 한 번만(다시 들어올 때마다 되살리지 않는다)", async () => {
    const acked = help("acknowledged", { acknowledged_at: "2026-11-09T01:01:00" });
    const api = fakeApi({ getHelp: vi.fn().mockResolvedValue(acked) });
    const initial = { id: "h1", state: "acknowledged" as const, step_id: "s1", created_at: "x" };
    const a = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api, initial }));
    await act(async () => {});
    expect(a.result.current.phase).toBe("acked");
    a.unmount();
    const b = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api, initial }));
    await act(async () => {});
    expect(b.result.current.phase).toBe("idle");
  });

  it("인터넷이 끊겨 확인 못 하면 목록의 열린 요청을 믿는다", async () => {
    const api = fakeApi({ getHelp: vi.fn().mockRejectedValue(new NetworkError()) });
    const { result } = renderHook(() =>
      useHelp({ assignmentId: "a1", stepId: "s1", api, initial: { id: "h1", state: "open", step_id: "s1", created_at: "x" } }),
    );
    await act(async () => {});
    expect(result.current.phase).toBe("sent");
  });
});

describe("완료 기록 보내기: 답 없는 요청이 대기열을 붙잡지 않는다", () => {
  it("logStep은 정해진 시간 뒤 끊고(AbortError), 대기열은 기록을 남긴 채 '다음에 다시'", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockImplementation((_u, init) =>
      new Promise((_r, reject) => (init as RequestInit).signal?.addEventListener("abort", () => reject(new DOMException("x", "AbortError")))));
    const box = new Outbox("w1");
    box.put({ assignment_id: "a1", step_id: "s1", duration_sec: 1, replay_count: 0, stuck: false, completed: true });
    const p = box.flush((b) => workerApi.logStep(b));
    await act(async () => {
      vi.advanceTimersByTime(LOG_SEND_TIMEOUT_MS);
    });
    const r = await p;
    expect(r).toMatchObject({ sent: 0, failed: true, remaining: 1 });
    // 다음 보내기는 새로 시작한다(예전에는 멈춘 요청의 결과를 같이 기다리기만 했다).
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ ok: true, assignment_status: "in_progress", duplicate: false, applied: true }), { status: 201 }));
    const r2 = await box.flush((b) => workerApi.logStep(b));
    expect(r2).toMatchObject({ sent: 1, remaining: 0 });
  });
});

const step = (id: string) => ({ id, order: 0, sentence: id, action_type: "other", symbol_url: null } as unknown as TodayJob["steps"][number]);
const job = (aid: string, ids: string[], done: string[] = []): TodayJob =>
  normalizeJob({ assignment_id: aid, task_id: "t", task_title: "컵 씻기", steps: ids.map(step), done_step_ids: done });

describe("writeTodayCache: 늦게 온 옛 목록이 보낸 단계를 지우지 않는다", () => {
  it("기기에 적힌 끝낸 단계는 합친다(지금도 있는 단계만), 모두 덮으면 done", () => {
    localStorage.setItem(`${TODAY_CACHE_PREFIX}w1`, JSON.stringify({ day: localDay(), jobs: [job("a1", ["s1", "s2"])] }));
    noteSentInTodayCache("w1", "a1", "s1");
    // 기록보다 먼저 답한 GET이 늦게 도착: s1이 없다.
    const merged = writeTodayCache("w1", [job("a1", ["s1", "s2"]), job("a2", ["x"])]);
    expect(merged[0].done_step_ids).toEqual(["s1"]);
    expect(cachedJobs("w1")![0].done_step_ids).toEqual(["s1"]);
    noteSentInTodayCache("w1", "a1", "s2");
    const all = writeTodayCache("w1", [job("a1", ["s1", "s2"], ["s1"])]);
    expect(all[0].status).toBe("done");
    // 지워진 단계는 되살리지 않는다.
    expect(writeTodayCache("w1", [job("a1", ["s2", "s3"])])[0].done_step_ids).toEqual(["s2"]);
  });

  it("다른 날 저장본은 합치지 않는다", () => {
    localStorage.setItem(`${TODAY_CACHE_PREFIX}w1`, JSON.stringify({ day: "2000-1-1", jobs: [job("a1", ["s1"], ["s1"])] }));
    expect(writeTodayCache("w1", [job("a1", ["s1"])])[0].done_step_ids).toEqual([]);
  });
});

const steps: Step[] = [
  { id: "s1", order: 1, sentence: "컵을 물에 넣어요", action_type: "other", symbol_url: "http://x/a.png", symbol_source: "LOCAL_AAC", needs_fallback: false, tts_audio_url: null },
  { id: "s2", order: 2, sentence: "컵을 닦아요", action_type: "other", symbol_url: "http://x/b.png", symbol_source: "LOCAL_AAC", needs_fallback: false, tts_audio_url: null },
];

describe("StepPlayer: [다 했어요] 기록은 누른 순간 남긴다", () => {
  it("onRecord는 바로, onDone(다음 단계)은 칭찬 뒤. 칭찬 중에 화면이 사라져도 기록은 이미 남았다", () => {
    vi.useFakeTimers();
    const onRecord = vi.fn();
    const onDone = vi.fn();
    const { unmount } = render(
      <StepPlayer mode="live" title="컵 씻기" steps={steps} index={0} doneIds={new Set()} prefs={{ ...DEFAULT_A11Y_PREFS, autoplay_sound: false }}
        onRecord={onRecord} onDone={onDone} onPrev={() => {}} onExit={() => {}} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "다 했어요" }));
    expect(onRecord).toHaveBeenCalledTimes(1);
    expect(onDone).not.toHaveBeenCalled();
    unmount(); // 뒤로 가기·화면 잠금
    act(() => {
      vi.advanceTimersByTime(PRAISE_MS);
    });
    expect(onDone).not.toHaveBeenCalled();
    expect(onRecord.mock.calls[0][0]).toMatchObject({ index: 0 });
  });

  it("단계 시간은 단조 시계로 잰다: 기기 시계가 뒤로 가도 음수가 아니다", () => {
    const now = vi.spyOn(performance, "now").mockReturnValue(10_000);
    vi.spyOn(Date, "now").mockReturnValue(5_000_000);
    const onRecord = vi.fn();
    render(
      <StepPlayer mode="live" title="컵 씻기" steps={steps} index={0} doneIds={new Set()} prefs={{ ...DEFAULT_A11Y_PREFS, autoplay_sound: false }}
        onRecord={onRecord} onDone={() => {}} onPrev={() => {}} onExit={() => {}} />,
    );
    now.mockReturnValue(13_500);
    vi.mocked(Date.now).mockReturnValue(1_000); // 시계가 뒤로
    fireEvent.click(screen.getByRole("button", { name: "다 했어요" }));
    expect(onRecord.mock.calls[0][0].durationSec).toBeCloseTo(3.5);
  });
});

describe("작은 화면 문구", () => {
  it("끊김 표시는 좁은 휴대폰에서도 글자가 있다(아이콘만이 아님)", () => {
    render(<OfflineMark />);
    const mark = screen.getByTestId("offline-mark");
    expect(mark).toHaveAccessibleName(COPY.band.offlineShort);
    expect(mark.textContent).toContain(COPY.band.offlineTiny);
  });

  it("끝내기 확인: 못 보낸 기록 알림을 보이고 읽는다", () => {
    const speak = window.speechSynthesis.speak as ReturnType<typeof vi.fn>;
    speak.mockClear();
    render(<ConfirmScreen kind="end" speak note={COPY.confirm.unsent} onStay={() => {}} onLeave={() => {}} />);
    expect(screen.getByTestId("confirm-note")).toHaveTextContent(COPY.confirm.unsent);
    for (const re of FORBIDDEN_PATTERNS) expect(COPY.confirm.unsent).not.toMatch(re);
    expect(speak).toHaveBeenCalled();
  });
});
