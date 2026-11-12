import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import type { HelpOut } from "../../src/api";
import { NetworkError } from "../../src/apiErrors";
import { useHelp } from "../../src/worker/hooks/useHelp";

// 2c 1회차 검증: [도와주세요]를 여러 번 누르면 서버 요청은 1건인데 help_open 측정 이벤트는 누른 만큼 쌓였다.
// onSend는 실제로 부르기를 시작할 때만 불린다.
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => {
  vi.restoreAllMocks();
});

const help = (state: HelpOut["state"]): HelpOut => ({
  id: "h1", assignment_id: "a1", step_id: "s1", step_order: 1, state, resolution: null,
  created_at: "2026-11-09T01:00:00", acknowledged_at: null, cancelled_at: null, resolved_at: null,
});

function fakeApi(createHelp = vi.fn().mockResolvedValue(help("open"))) {
  return {
    createHelp,
    getHelp: vi.fn().mockResolvedValue(help("open")),
    cancelHelp: vi.fn().mockResolvedValue(help("cancelled")),
    cancelHelpByClient: vi.fn().mockResolvedValue(help("cancelled")),
  };
}

describe("help_open은 실제 부르기마다 한 번", () => {
  it("부르는 중·불렀어요에서 4번 더 눌러도 onSend 1번, 서버 요청 1번", async () => {
    const api = fakeApi();
    const onSend = vi.fn();
    const { result } = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api, onSend }));
    act(() => result.current.request());
    act(() => result.current.request()); // 부르는 중
    await act(async () => {});
    expect(result.current.phase).toBe("sent");
    act(() => result.current.request()); // 불렀어요
    act(() => result.current.request());
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(api.createHelp).toHaveBeenCalledTimes(1);
  });

  it("못 불렀어요 뒤 [다시 부르기]는 새 시도로 센다", async () => {
    const api = fakeApi(vi.fn().mockRejectedValueOnce(new NetworkError()).mockResolvedValue(help("open")));
    const onSend = vi.fn();
    const { result } = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api, onSend }));
    act(() => result.current.request());
    await act(async () => {});
    expect(result.current.phase).toBe("failed");
    act(() => result.current.request());
    await act(async () => {});
    expect(result.current.phase).toBe("sent");
    expect(onSend).toHaveBeenCalledTimes(2);
  });
});
