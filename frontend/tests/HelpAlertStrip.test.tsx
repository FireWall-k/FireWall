import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HelpAlertStrip, { HELP_POLL_MS } from "../src/components/HelpAlertStrip";
import { relativeTime } from "../src/components/helpTime";
import type { EmployerHelp } from "../src/api";

const employerHelp = vi.fn();
const ackHelp = vi.fn();
const resolveHelp = vi.fn();

vi.mock("../src/api", () => ({
  api: {
    employerHelp: (s?: string) => employerHelp(s),
    ackHelp: (id: string) => ackHelp(id),
    resolveHelp: (id: string) => resolveHelp(id),
  },
}));

function help(over: Partial<EmployerHelp> = {}): EmployerHelp {
  return {
    id: "h1", state: "open", created_at: new Date().toISOString().replace("Z", ""), acknowledged_at: null,
    worker_id: "w1", worker_name: "김민지", assignment_id: "a1", task_id: "t1", task_title: "컵 씻기",
    step_id: "s3", step_order: 3, step_sentence: "컵을 물에 넣어요", step_symbol_url: null,
    ...over,
  };
}

beforeEach(() => {
  employerHelp.mockReset().mockResolvedValue([]);
  ackHelp.mockReset().mockResolvedValue({});
  resolveHelp.mockReset().mockResolvedValue({});
});
afterEach(() => {
  vi.useRealTimers();
});

describe("HelpAlertStrip(사업주 도움 요청 띠)", () => {
  it("요청이 없으면 아무것도 그리지 않는다", async () => {
    const { container } = render(<HelpAlertStrip />);
    await waitFor(() => expect(employerHelp).toHaveBeenCalledWith("active"));
    expect(container).toBeEmptyDOMElement();
  });

  it("요청이 있으면 '김민지 님이 도움을 요청했어요 · 컵 씻기 3단계 · 방금'", async () => {
    employerHelp.mockResolvedValue([help()]);
    render(<HelpAlertStrip />);
    const strip = await screen.findByRole("status");
    expect(strip).toHaveTextContent("김민지 님이 도움을 요청했어요 · 컵 씻기 3단계 · 방금");
    expect(screen.getByRole("button", { name: "확인했어요" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "도와줬어요" })).toBeInTheDocument();
  });

  it("3건까지 보이고 나머지는 '그 외 N건'", async () => {
    employerHelp.mockResolvedValue([1, 2, 3, 4, 5].map((i) => help({ id: `h${i}`, worker_name: `근로자${i}` })));
    render(<HelpAlertStrip />);
    await screen.findByText("근로자1");
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("그 외 2건")).toBeInTheDocument();
  });

  it("[확인했어요]는 ack, [도와줬어요]는 resolve를 부르고 띠에서 뺀다", async () => {
    employerHelp.mockResolvedValueOnce([help()]).mockResolvedValue([help({ state: "acknowledged" })]);
    const user = userEvent.setup();
    render(<HelpAlertStrip />);
    await user.click(await screen.findByRole("button", { name: "확인했어요" }));
    expect(ackHelp).toHaveBeenCalledWith("h1");
    expect(await screen.findByText("확인함")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "확인했어요" })).not.toBeInTheDocument();

    employerHelp.mockResolvedValue([]);
    await user.click(screen.getByRole("button", { name: "도와줬어요" }));
    expect(resolveHelp).toHaveBeenCalledWith("h1");
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  });

  it("처리하지 못하면(근로자가 이미 취소함) 서버 문장을 보인다", async () => {
    employerHelp.mockResolvedValue([help()]);
    resolveHelp.mockRejectedValue(new Error("근로자가 이미 취소한 요청이에요."));
    const user = userEvent.setup();
    render(<HelpAlertStrip />);
    await user.click(await screen.findByRole("button", { name: "도와줬어요" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("근로자가 이미 취소한 요청이에요.");
  });

  it("5초마다 다시 부르고, 불러오기에 실패해도 띠는 그대로 둔다", async () => {
    vi.useFakeTimers();
    employerHelp.mockResolvedValueOnce([help()]).mockRejectedValue(new Error("404"));
    render(<HelpAlertStrip />);
    await act(async () => {});
    expect(screen.getByRole("status")).toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(HELP_POLL_MS);
    });
    expect(employerHelp).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("숨은 탭에서는 부르지 않는다", async () => {
    vi.useFakeTimers();
    render(<HelpAlertStrip />);
    await act(async () => {});
    expect(employerHelp).toHaveBeenCalledTimes(1);
    const vis = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    document.dispatchEvent(new Event("visibilitychange"));
    await act(async () => {
      vi.advanceTimersByTime(HELP_POLL_MS * 3);
    });
    expect(employerHelp).toHaveBeenCalledTimes(1);
    vis.mockReturnValue("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    await act(async () => {});
    expect(employerHelp).toHaveBeenCalledTimes(2);
    vis.mockRestore();
  });

  it("늦게 온 응답(앞서 보낸 요청)은 버린다", async () => {
    vi.useFakeTimers();
    let resolveFirst: (v: EmployerHelp[]) => void = () => {};
    employerHelp
      .mockImplementationOnce(() => new Promise((r) => { resolveFirst = r; }))
      .mockResolvedValue([]);
    render(<HelpAlertStrip />);
    await act(async () => {
      vi.advanceTimersByTime(HELP_POLL_MS); // 두 번째 요청: 빈 목록
    });
    await act(async () => {
      resolveFirst([help()]); // 첫 요청 응답이 이제야 도착
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("relativeTime", () => {
  const now = Date.parse("2026-11-09T01:10:00Z");
  it.each([
    ["2026-11-09T01:09:40", "방금"],
    ["2026-11-09T01:05:00", "5분 전"],
    ["2026-11-08T23:00:00", "2시간 전"],
    ["2026-11-09T01:09:40Z", "방금"],
  ])("%s → %s", (iso, out) => {
    expect(relativeTime(iso, now)).toBe(out);
  });
});
