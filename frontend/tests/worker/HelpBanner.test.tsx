import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import type { HelpOut } from "../../src/api";
import { NetworkError } from "../../src/apiErrors";
import { HelpBanner, HelpButton } from "../../src/worker/Help";
import { HELP_ACK_CLOSE_MS, HELP_POLL_MS, useHelp, type HelpPhase } from "../../src/worker/hooks/useHelp";

// 도움 띠 4상태(명세 4.5 + 창업자 결정 8)와 도움 요청 흐름(contract §7).
afterEach(() => {
  vi.useRealTimers();
});

const help = (state: HelpOut["state"], resolution: HelpOut["resolution"] = null): HelpOut => ({
  id: "h1", assignment_id: "a1", step_id: "s1", step_order: 1, state, resolution,
  created_at: "2026-11-09T01:00:00", acknowledged_at: null, cancelled_at: null, resolved_at: null,
});

describe("HelpBanner", () => {
  it.each([
    ["sending", "선생님을 부르는 중이에요", null],
    ["sent", "선생님을 불렀어요. 여기서 기다려요.", "취소"],
    ["failed", "아직 못 불렀어요. 손을 들어 선생님을 불러요.", "다시 부르기"],
    ["acked", "선생님이 확인했어요", null],
  ] as const)("%s: 문구와 버튼, role=status", (phase, text, button) => {
    render(<HelpBanner phase={phase} onCancel={() => {}} onRetry={() => {}} />);
    expect(screen.getByRole("status")).toHaveTextContent(text);
    if (button) expect(screen.getByRole("button", { name: button })).toBeInTheDocument();
    else expect(screen.queryByRole("button")).toBeNull();
  });

  it("idle이면 띠가 없다", () => {
    const { container } = render(<HelpBanner phase="idle" onCancel={() => {}} onRetry={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("'불렀어요': 문장과 [취소]가 한 줄 가로 배치(문장 flex-1, [취소] 줄지 않고 줄바꿈 없음)", () => {
    const onCancel = vi.fn();
    render(<HelpBanner phase="sent" onCancel={onCancel} onRetry={() => {}} />);
    const text = screen.getByTestId("help-band-text");
    const cancel = screen.getByRole("button", { name: "취소" });
    const row = text.parentElement!;
    expect(row).toBe(cancel.parentElement);
    expect(row.className).toMatch(/\bflex\b/);
    expect(row.className).not.toMatch(/flex-col|flex-wrap/);
    expect(text.className).toMatch(/flex-1/);
    expect(cancel.className).toMatch(/shrink-0/);
    expect(cancel.className).toMatch(/whitespace-nowrap/);
    expect(text.compareDocumentPosition(cancel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(cancel);
    expect(onCancel).toHaveBeenCalled();
  });
});

describe("HelpButton", () => {
  it.each([
    ["idle", "도와주세요", "false"],
    ["sending", "부르는 중", "true"],
    ["sent", "불렀어요", "true"],
    ["failed", "도와주세요", "false"],
    ["acked", "도와주세요", "false"],
  ] as [HelpPhase, string, string][])("%s → '%s'", (phase, label, pressed) => {
    render(<HelpButton phase={phase} onPress={() => {}} />);
    const b = screen.getByRole("button", { name: label });
    expect(b).toHaveAttribute("aria-pressed", pressed);
  });
});

function fakeApi(overrides: Partial<Record<"createHelp" | "getHelp" | "cancelHelp", ReturnType<typeof vi.fn>>> = {}) {
  return {
    createHelp: vi.fn().mockResolvedValue(help("open")),
    getHelp: vi.fn().mockResolvedValue(help("open")),
    cancelHelp: vi.fn().mockResolvedValue(help("cancelled")),
    ...overrides,
  };
}

describe("useHelp", () => {
  it("부르기 → 보내는 중 → 불렀어요(새 요청 id 포함)", async () => {
    const api = fakeApi();
    const { result } = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api }));
    expect(result.current.phase).toBe("idle");
    act(() => result.current.request());
    expect(result.current.phase).toBe("sending");
    await act(async () => {});
    expect(result.current.phase).toBe("sent");
    expect(api.createHelp).toHaveBeenCalledWith(expect.objectContaining({ assignment_id: "a1", step_id: "s1" }));
    expect(typeof api.createHelp.mock.calls[0][0].client_request_id).toBe("string");
  });

  it("닿지 않으면 '아직 못 불렀어요'(대기열에 넣지 않음), [다시 부르기]로 다시", async () => {
    const api = fakeApi({ createHelp: vi.fn().mockRejectedValueOnce(new NetworkError()).mockResolvedValue(help("open")) });
    const { result } = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api }));
    act(() => result.current.request());
    await act(async () => {});
    expect(result.current.phase).toBe("failed");
    act(() => result.current.request());
    await act(async () => {});
    expect(result.current.phase).toBe("sent");
    expect(api.createHelp).toHaveBeenCalledTimes(2);
  });

  it("불렀어요 동안 5초마다 확인 → 선생님 확인 → 3초 뒤 닫힘", async () => {
    vi.useFakeTimers();
    const api = fakeApi();
    const { result } = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api }));
    act(() => result.current.request());
    await act(async () => {});
    expect(result.current.phase).toBe("sent");
    await act(async () => {
      vi.advanceTimersByTime(HELP_POLL_MS);
    });
    expect(api.getHelp).toHaveBeenCalledWith("h1");
    expect(result.current.phase).toBe("sent");
    api.getHelp.mockResolvedValue(help("acknowledged"));
    await act(async () => {
      vi.advanceTimersByTime(HELP_POLL_MS);
    });
    expect(result.current.phase).toBe("acked");
    await act(async () => {
      vi.advanceTimersByTime(HELP_ACK_CLOSE_MS);
    });
    expect(result.current.phase).toBe("idle");
  });

  it("사업주가 [도와줬어요]로 닫아도 '선생님이 확인했어요'", async () => {
    vi.useFakeTimers();
    const api = fakeApi({ getHelp: vi.fn().mockResolvedValue(help("resolved", "employer")) });
    const { result } = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api }));
    act(() => result.current.request());
    await act(async () => {});
    await act(async () => {
      vi.advanceTimersByTime(HELP_POLL_MS);
    });
    expect(result.current.phase).toBe("acked");
  });

  it("[취소]: 바로 닫고 서버에 취소를 보낸다", async () => {
    const api = fakeApi();
    const { result } = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api }));
    act(() => result.current.request());
    await act(async () => {});
    act(() => result.current.cancel());
    expect(result.current.phase).toBe("idle");
    expect(api.cancelHelp).toHaveBeenCalledWith("h1");
  });

  it("[다 했어요]를 누르면 띠를 닫는다(서버가 '해결됨'으로 닫음)", async () => {
    const api = fakeApi();
    const { result } = renderHook(() => useHelp({ assignmentId: "a1", stepId: "s1", api }));
    act(() => result.current.request());
    await act(async () => {});
    act(() => result.current.markStepDone());
    expect(result.current.phase).toBe("idle");
    expect(api.cancelHelp).not.toHaveBeenCalled();
  });

  it("새로고침 뒤 active_help로 띠를 되살린다", () => {
    const api = fakeApi();
    const { result } = renderHook(() =>
      useHelp({ assignmentId: "a1", stepId: "s1", api, initial: { id: "h1", state: "open", step_id: "s1", created_at: "x" } }),
    );
    expect(result.current.phase).toBe("sent");
    act(() => result.current.cancel());
    expect(api.cancelHelp).toHaveBeenCalledWith("h1");
  });
});
