import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { ApiError } from "../../src/apiErrors";

// (2c) LiveProvider: GET /api/employer/live 5초 폴링 하나(contract §5.2, tasks §6 FOUNDATION).
const getLive = vi.fn();
vi.mock("../../src/manager/api/live", () => ({ getLive: () => getLive() }));

import LiveProvider from "../../src/manager/shell/LiveProvider";
import { LIVE_POLL_MS, useLive } from "../../src/manager/shell/useLive";

function live(tag: string, help: unknown[] = []) {
  return {
    server_now: "2026-11-10T05:02:31",
    summary: { working: 1, total_workers: 2, open_help: help.length, stuck_steps: 0, needs_check_tasks: 0 },
    workers: [{ worker_id: tag, display_name: tag, initials: tag, badge: "in_progress", last_activity_at: null, last_signal_at: null, current: null, today: [] }],
    help,
  };
}

function Probe() {
  const f = useLive();
  return (
    <div>
      <p data-testid="who">{f.data?.workers[0]?.display_name ?? "없음"}</p>
      <p data-testid="dis">{f.disconnected ? "끊김" : "연결"}</p>
      <p data-testid="upd">{f.updatedAt == null ? "없음" : "있음"}</p>
      <p data-testid="help">{f.help.map((h) => `${h.id}:${h.state}`).join(",")}</p>
      <button type="button" onClick={() => f.markHelp("h1", "resolved")}>닫기</button>
      <button type="button" onClick={() => f.markHelp("h1", "acknowledged")}>확인</button>
    </div>
  );
}

function setHidden(hidden: boolean) {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => (hidden ? "hidden" : "visible") });
  document.dispatchEvent(new Event("visibilitychange"));
}

async function flush() {
  await act(async () => {});
}

beforeEach(() => {
  vi.useFakeTimers();
  getLive.mockReset().mockResolvedValue(live("가"));
});
afterEach(() => {
  setHidden(false);
  vi.useRealTimers();
});

describe("LiveProvider", () => {
  it("처음 한 번, 그 뒤 5초마다 한 번만 부른다(구독하는 곳이 여럿이어도)", async () => {
    render(
      <LiveProvider>
        <Probe />
        <Probe />
      </LiveProvider>,
    );
    await flush();
    expect(getLive).toHaveBeenCalledTimes(1);
    expect(screen.getAllByTestId("who")[0]).toHaveTextContent("가");
    await act(async () => {
      vi.advanceTimersByTime(LIVE_POLL_MS);
    });
    expect(getLive).toHaveBeenCalledTimes(2);
    await act(async () => {
      vi.advanceTimersByTime(LIVE_POLL_MS * 2);
    });
    expect(getLive).toHaveBeenCalledTimes(4);
  });

  it("숨은 탭에서는 멈추고, 다시 보이면 바로 한 번 부른다", async () => {
    render(
      <LiveProvider>
        <Probe />
      </LiveProvider>,
    );
    await flush();
    expect(getLive).toHaveBeenCalledTimes(1);
    act(() => setHidden(true));
    await act(async () => {
      vi.advanceTimersByTime(LIVE_POLL_MS * 4);
    });
    expect(getLive).toHaveBeenCalledTimes(1);
    act(() => setHidden(false));
    await flush();
    expect(getLive).toHaveBeenCalledTimes(2);
  });

  it("늦게 온 응답(앞 요청)은 버린다", async () => {
    let resolveOld: (v: unknown) => void = () => {};
    getLive.mockReset();
    getLive.mockImplementationOnce(() => new Promise((r) => (resolveOld = r)));
    getLive.mockResolvedValueOnce(live("새것"));
    render(
      <LiveProvider>
        <Probe />
      </LiveProvider>,
    );
    await act(async () => {
      vi.advanceTimersByTime(LIVE_POLL_MS);
    });
    expect(screen.getByTestId("who")).toHaveTextContent("새것");
    await act(async () => resolveOld(live("옛것")));
    expect(screen.getByTestId("who")).toHaveTextContent("새것");
  });

  it("실패하면 화면은 그대로 두고 끊김만 표시(토스트 없음), 다음 성공에 풀린다", async () => {
    render(
      <LiveProvider>
        <Probe />
      </LiveProvider>,
    );
    await flush();
    getLive.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await act(async () => {
      vi.advanceTimersByTime(LIVE_POLL_MS);
    });
    expect(screen.getByTestId("dis")).toHaveTextContent("끊김");
    expect(screen.getByTestId("who")).toHaveTextContent("가");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(LIVE_POLL_MS);
    });
    expect(screen.getByTestId("dis")).toHaveTextContent("연결");
  });

  it("429는 끊김이 아니다: 다음 주기에 다시 부른다", async () => {
    render(
      <LiveProvider>
        <Probe />
      </LiveProvider>,
    );
    await flush();
    getLive.mockRejectedValueOnce(new ApiError(429, "잠깐 뒤에 다시 불러 주세요."));
    await act(async () => {
      vi.advanceTimersByTime(LIVE_POLL_MS);
    });
    expect(screen.getByTestId("dis")).toHaveTextContent("연결");
    expect(getLive).toHaveBeenCalledTimes(2);
    await act(async () => {
      vi.advanceTimersByTime(LIVE_POLL_MS);
    });
    expect(getLive).toHaveBeenCalledTimes(3);
  });

  it("[도와줬어요]·[확인했어요]를 누른 결과는 서버의 4초 저장분보다 앞선다", async () => {
    const h = { id: "h1", state: "open" };
    getLive.mockResolvedValue(live("가", [h]));
    render(
      <LiveProvider>
        <Probe />
      </LiveProvider>,
    );
    await flush();
    expect(screen.getByTestId("help")).toHaveTextContent("h1:open");
    act(() => screen.getByRole("button", { name: "확인" }).click());
    expect(screen.getByTestId("help")).toHaveTextContent("h1:acknowledged");
    act(() => screen.getByRole("button", { name: "닫기" }).click());
    expect(screen.getByTestId("help")).toHaveTextContent("");
    // 서버가 아직 열린 요청을 돌려줘도(4초 저장분) 다시 나타나지 않는다.
    await act(async () => {
      vi.advanceTimersByTime(LIVE_POLL_MS);
    });
    expect(screen.getByTestId("help").textContent).toBe("");
  });
});
