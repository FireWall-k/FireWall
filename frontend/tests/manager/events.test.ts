import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// (2c) 사업주 측정 이벤트 도우미: 모아서 보냄, 50건씩, 실패는 조용히 버림.
const postEvents = vi.fn();
vi.mock("../../src/manager/api/live", () => ({ postEvents: (e: unknown) => postEvents(e) }));

import { EVENT_BATCH_MAX, EVENT_FLUSH_MS, flushEvents, resetEventsForTest, track } from "../../src/manager/shell/events";

beforeEach(() => {
  vi.useFakeTimers();
  resetEventsForTest();
  postEvents.mockReset().mockResolvedValue(undefined);
});
afterEach(() => vi.useRealTimers());

describe("manager/shell/events", () => {
  it("2초 모았다가 한 번에 보낸다", () => {
    track("task_create_start");
    track("send_click_count", { task_id: "t1", value_num: 3 });
    expect(postEvents).not.toHaveBeenCalled();
    vi.advanceTimersByTime(EVENT_FLUSH_MS);
    expect(postEvents).toHaveBeenCalledTimes(1);
    const batch = postEvents.mock.calls[0][0];
    expect(batch.map((e: { name: string }) => e.name)).toEqual(["task_create_start", "send_click_count"]);
    expect(batch[1]).toMatchObject({ task_id: "t1", value_num: 3 });
    expect(typeof batch[0].at).toBe("string");
  });

  it("50건이 차면 바로 보내고, 실패해도 던지지 않는다", async () => {
    postEvents.mockRejectedValue(new Error("x"));
    for (let i = 0; i < EVENT_BATCH_MAX; i++) track("send_click_disabled");
    expect(postEvents).toHaveBeenCalledTimes(1);
    expect(postEvents.mock.calls[0][0]).toHaveLength(50);
    await Promise.resolve();
    expect(() => flushEvents()).not.toThrow();
  });

  it("탭이 숨으면 남은 것을 바로 보낸다", () => {
    track("task_send_done", { value_num: 42 });
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(postEvents).toHaveBeenCalledTimes(1);
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
  });
});
