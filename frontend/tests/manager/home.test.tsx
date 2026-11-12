import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import type { EmployerHelp } from "../../src/api";
import type { CoachingCard, LiveOut, LiveWorker, TimelineOut } from "../../src/manager/api/types";

// (2c) 홈 · 오늘 현황 부품(명세 5.2): HelpBand, SummaryCards, LiveTable, TimelineDrawer, CoachingCards, 빈 상태.
const ackHelp = vi.fn().mockResolvedValue({});
const resolveHelp = vi.fn().mockResolvedValue({});
vi.mock("../../src/api", async (orig) => {
  const real = await orig<typeof import("../../src/api")>();
  return { ...real, api: { ackHelp: (id: string) => ackHelp(id), resolveHelp: (id: string) => resolveHelp(id) } };
});
const getTimeline = vi.fn();
const getCoaching = vi.fn();
vi.mock("../../src/manager/api/live", () => ({
  getTimeline: (id: string) => getTimeline(id),
  getCoaching: () => getCoaching(),
}));

import HelpBand from "../../src/manager/home/HelpBand";
import HomePage from "../../src/manager/home/HomePage";
import LiveTable from "../../src/manager/home/LiveTable";
import SummaryCards from "../../src/manager/home/SummaryCards";
import TimelineDrawer from "../../src/manager/home/TimelineDrawer";
import { LiveContext, type LiveFeed } from "../../src/manager/shell/useLive";

const NOW = Date.parse("2026-11-10T05:00:00Z");
const iso = (minAgo: number) => new Date(NOW - minAgo * 60_000).toISOString().replace("Z", "");

function help(over: Partial<EmployerHelp> = {}): EmployerHelp {
  return {
    id: "h1", state: "open", created_at: iso(0), acknowledged_at: null, worker_id: "w1", worker_name: "김민지",
    assignment_id: "a1", task_id: "t1", task_title: "컵 씻기", step_id: "s3", step_order: 3, step_sentence: "컵을 헹궈요",
    step_symbol_url: null, source_step_id: "src3", step_thumb_url: null, ...over,
  };
}

function worker(over: Partial<LiveWorker> = {}): LiveWorker {
  return {
    worker_id: "w1", display_name: "김민지", initials: "김", badge: "in_progress", last_activity_at: iso(1), last_signal_at: iso(1),
    current: {
      assignment_id: "a1", task_id: "t1", task_title: "컵 씻기", version_no: 1, done: 3, total: 6,
      step: { id: "s4", source_step_id: "src4", order: 4, sentence: "컵을 말려요", thumb_url: null },
    },
    today: [{ assignment_id: "a1", task_title: "컵 씻기", status: "in_progress", is_next: true }],
    ...over,
  };
}

function liveOut(over: Partial<LiveOut> = {}): LiveOut {
  return {
    server_now: iso(0),
    summary: { working: 2, total_workers: 3, open_help: 1, stuck_steps: 1, needs_check_tasks: 2 },
    workers: [
      worker(),
      worker({ worker_id: "w2", display_name: "이수진", initials: "이", badge: "stuck_suspect" }),
      worker({ worker_id: "w3", display_name: "박하늘", initials: "박", badge: "offline", last_signal_at: iso(5) }),
      worker({ worker_id: "w4", display_name: "최다온", initials: "최", badge: "idle", current: null, today: [] }),
    ],
    help: [],
    ...over,
  };
}

function feed(over: Partial<LiveFeed> = {}): LiveFeed {
  const data = over.data === undefined ? liveOut() : over.data;
  return {
    data, help: data?.help ?? [], updatedAt: NOW, disconnected: false, now: NOW,
    reload: vi.fn().mockResolvedValue(undefined), markHelp: vi.fn(), ...over,
  };
}

function Where() {
  const l = useLocation();
  return <p data-testid="where">{l.pathname + l.search}</p>;
}

function renderWith(ui: React.ReactNode, f: LiveFeed = feed(), path = "/m") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <LiveContext.Provider value={f}>
        <Routes>
          <Route path="*" element={<>{ui}<Where /></>} />
        </Routes>
      </LiveContext.Provider>
    </MemoryRouter>,
  );
}

function timeline(): TimelineOut {
  return {
    worker_id: "w1", display_name: "김민지", date: "2026-11-10",
    assignments: [{
      assignment_id: "a1", task_id: "t1", task_title: "컵 씻기", version_no: 1, status: "in_progress", assigned_at: iso(60),
      steps: [
        { step_id: "s1", source_step_id: "src1", order: 1, sentence: "컵을 들어요", thumb_url: null, completed: true, completed_at: iso(30), duration_sec: 150, replay_count: 2, prev_count: 1, help_count: 0 },
        { step_id: "s2", source_step_id: "src2", order: 2, sentence: "물을 틀어요", thumb_url: null, completed: false, completed_at: null, duration_sec: null, replay_count: 0, prev_count: 0, help_count: 1 },
      ],
    }],
    events: [
      { at: iso(30), kind: "step_done", assignment_id: "a1", step_order: 1 },
      { at: iso(20), kind: "help_open", assignment_id: "a1", step_order: 2 },
    ],
  };
}

beforeEach(() => {
  ackHelp.mockClear();
  resolveHelp.mockClear();
  getTimeline.mockReset().mockResolvedValue(timeline());
  getCoaching.mockReset().mockResolvedValue([]);
});

describe("HelpBand(도움 요청 띠)", () => {
  it("요청이 없으면 아무것도 그리지 않는다", () => {
    renderWith(<HelpBand />, feed({ help: [] }));
    expect(screen.queryByTestId("help-band")).not.toBeInTheDocument();
  });

  it("4건이면 3건만 보이고 '그 외 1건'", () => {
    const list = ["김민지", "이수진", "박하늘", "최다온"].map((n, i) => help({ id: `h${i}`, worker_name: n }));
    renderWith(<HelpBand />, feed({ help: list }));
    expect(screen.getAllByTestId("help-band-item")).toHaveLength(3);
    expect(screen.getByText("그 외 1건")).toBeInTheDocument();
    expect(screen.queryByText("최다온")).not.toBeInTheDocument();
  });

  it("문구: '김민지 님이 도움을 요청했어요 · 컵 씻기 3단계 · 방금'과 버튼 4개", () => {
    renderWith(<HelpBand />, feed({ help: [help()] }));
    const item = screen.getByTestId("help-band-item");
    expect(item).toHaveTextContent("김민지 님이 도움을 요청했어요 · 컵 씻기 3단계 · 방금");
    for (const name of ["보러 가기", "이 단계 고치기", "확인했어요", "도와줬어요"]) {
      expect(within(item).getByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("[이 단계 고치기] → 편집기 그 단계(?step=source_step_id)로 1번", async () => {
    const user = userEvent.setup();
    renderWith(<HelpBand />, feed({ help: [help()] }));
    await user.click(screen.getByRole("button", { name: "이 단계 고치기" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/m/tasks/t1?step=src3");
  });

  it("[도와줬어요] → 서버에 닫기 + 화면에 먼저 반영(markHelp) + 다시 불러오기", async () => {
    const user = userEvent.setup();
    const f = feed({ help: [help()] });
    renderWith(<HelpBand />, f);
    await user.click(screen.getByRole("button", { name: "도와줬어요" }));
    expect(resolveHelp).toHaveBeenCalledWith("h1");
    expect(f.markHelp).toHaveBeenCalledWith("h1", "resolved");
    expect(f.reload).toHaveBeenCalled();
  });

  it("확인한 요청은 '도움 가는 중'이고 [확인했어요]가 없다", () => {
    renderWith(<HelpBand />, feed({ help: [help({ state: "acknowledged" })] }));
    expect(screen.getByText("도움 가는 중")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "확인했어요" })).not.toBeInTheDocument();
  });

  it("[보러 가기] → 그 근로자의 오늘 기록 서랍", async () => {
    const user = userEvent.setup();
    renderWith(<HelpBand />, feed({ help: [help()] }));
    await user.click(screen.getByRole("button", { name: "보러 가기" }));
    expect(await screen.findByRole("dialog", { name: "김민지 님 오늘 기록" })).toBeInTheDocument();
    expect(getTimeline).toHaveBeenCalledWith("w1");
  });

  it("휴대폰용 … 메뉴에 [이 단계 고치기]·[확인했어요]가 있다(넓은 화면 버튼은 md 이상에서만)", async () => {
    const user = userEvent.setup();
    renderWith(<HelpBand />, feed({ help: [help()] }));
    expect(screen.getByRole("button", { name: "이 단계 고치기" })).toHaveClass("hidden", "md:inline-flex");
    await user.click(screen.getByRole("button", { name: "김민지 님 도움 요청 메뉴 더 보기" }));
    expect(screen.getByRole("menuitem", { name: "이 단계 고치기" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "확인했어요" })).toBeInTheDocument();
  });
});

describe("SummaryCards(요약 4칸)", () => {
  it("숫자와 단위, 완료율 %는 없다, 넷째 칸은 직무 목록 '확인 필요'", () => {
    const onFilter = vi.fn();
    renderWith(<SummaryCards summary={liveOut().summary} openHelp={1} filter={null} onFilter={onFilter} />);
    expect(screen.getByTestId("summary-working")).toHaveTextContent("지금 일하는 사람2/3명");
    expect(screen.getByTestId("summary-help")).toHaveTextContent("도움 요청1건");
    expect(screen.getByTestId("summary-stuck")).toHaveTextContent("막힘 의심1단계");
    expect(screen.getByTestId("summary-needs-check")).toHaveAttribute("href", "/m/tasks?filter=needs_check");
    expect(document.body.textContent).not.toMatch(/%/);
  });

  it("누르면 걸러보기, 다시 누르면 풀림(aria-pressed)", async () => {
    const user = userEvent.setup();
    const onFilter = vi.fn();
    const { rerender } = renderWith(<SummaryCards summary={liveOut().summary} openHelp={1} filter={null} onFilter={onFilter} />);
    await user.click(screen.getByTestId("summary-stuck"));
    expect(onFilter).toHaveBeenLastCalledWith("stuck");
    rerender(
      <MemoryRouter>
        <SummaryCards summary={liveOut().summary} openHelp={1} filter="stuck" onFilter={onFilter} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("summary-stuck")).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByTestId("summary-stuck"));
    expect(onFilter).toHaveBeenLastCalledWith(null);
  });

  it("홈에서 '막힘 의심'을 누르면 표가 막힘 의심인 사람만 보인다", async () => {
    const user = userEvent.setup();
    renderWith(<HomePage />);
    expect(within(screen.getByTestId("live-table")).getAllByTestId("live-worker-name")).toHaveLength(4);
    await user.click(screen.getByTestId("summary-stuck"));
    const names = within(screen.getByTestId("live-table")).getAllByTestId("live-worker-name").map((b) => b.textContent);
    expect(names).toEqual(["이수진"]);
    expect(screen.getByText("'막힘 의심'으로 걸러 보는 중이에요")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "걸러보기 지우기" }));
    expect(within(screen.getByTestId("live-table")).getAllByTestId("live-worker-name")).toHaveLength(4);
  });
});

describe("LiveTable(근로자 실시간 표)", () => {
  it("배지: 색(톤)·아이콘·글이 함께, 연결 끊김은 '마지막 신호 n분 전'", () => {
    renderWith(<LiveTable workers={liveOut().workers} now={NOW} onOpen={vi.fn()} />);
    const kinds = Array.from(document.querySelectorAll("[data-badge-kind]"));
    const byKind = Object.fromEntries(kinds.map((k) => [k.getAttribute("data-badge-kind"), k]));
    expect(byKind.in_progress).toHaveTextContent("하는 중");
    expect(byKind.stuck_suspect).toHaveTextContent("막힘 의심");
    expect(byKind.offline).toHaveTextContent("연결 끊김");
    expect(byKind.idle).toHaveTextContent("오늘 일 없음");
    // 색: 막힘 의심은 주의(warn), 연결 끊김은 위험(danger), 하는 중은 안내(info)
    expect(byKind.stuck_suspect.querySelector(".badge")).toHaveClass("text-warn-700");
    expect(byKind.offline.querySelector(".badge")).toHaveClass("text-danger-700");
    expect(byKind.in_progress.querySelector(".badge")).toHaveClass("text-info-700");
    // 아이콘(꾸밈)도 함께
    for (const k of kinds) expect(k.querySelector("svg[aria-hidden='true']")).not.toBeNull();
    expect(screen.getByText("마지막 신호 5분 전")).toBeInTheDocument();
  });

  it("진행은 점 + '3/6', 지금 단계는 '4단계 · 문장', 마지막 활동 '1분 전'", () => {
    renderWith(<LiveTable workers={[worker()]} now={NOW} onOpen={vi.fn()} />);
    expect(screen.getByRole("img", { name: "6단계 중 3단계 함" })).toBeInTheDocument();
    expect(screen.getByText("4단계 · 컵을 말려요")).toBeInTheDocument();
    expect(screen.getByText("1분 전")).toBeInTheDocument();
  });

  it("행이나 이름을 누르면 onOpen, … 메뉴는 행 클릭으로 번지지 않는다", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    renderWith(<LiveTable workers={[worker()]} now={NOW} onOpen={onOpen} />);
    await user.click(screen.getByTestId("live-worker-name"));
    expect(onOpen).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "김민지 님 메뉴" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("menuitem", { name: "오늘 기록 보기" }));
    expect(onOpen).toHaveBeenCalledTimes(2);
  });
});

describe("TimelineDrawer(오늘 기록 서랍)", () => {
  it("막대 대신 '표로 보기': 단계별 걸린 시간·다시 듣기·이전 누름·도움", async () => {
    const user = userEvent.setup();
    renderWith(<TimelineDrawer workerId="w1" name="김민지" onClose={vi.fn()} />);
    const dialog = await screen.findByRole("dialog", { name: "김민지 님 오늘 기록" });
    await within(dialog).findByTestId("timeline-bars");
    expect(within(dialog).getByText("2분 30초")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("tab", { name: "표로 보기" }));
    const table = within(dialog).getByRole("table", { name: "컵 씻기 단계별 기록" });
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("1. 컵을 들어요2분 30초2번1번0번");
    expect(rows[2]).toHaveTextContent("2. 물을 틀어요아직 안 함0번0번1번");
    expect(within(dialog).getByText("1단계를 했어요")).toBeInTheDocument();
    expect(within(dialog).getByText("도움을 요청했어요")).toBeInTheDocument();
  });

  it("Esc로 닫는다(onClose)", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderWith(<TimelineDrawer workerId="w1" name="김민지" onClose={onClose} />);
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("불러오지 못하면 [다시 시도]로 다시 부른다", async () => {
    const user = userEvent.setup();
    getTimeline.mockRejectedValueOnce(new Error("x"));
    renderWith(<TimelineDrawer workerId="w1" name="김민지" onClose={vi.fn()} />);
    expect(await screen.findByText("기록을 불러오지 못했어요")).toBeInTheDocument();
    const retry = screen.getAllByRole("button").find((b) => /다시/.test(b.textContent ?? ""));
    await user.click(retry!);
    await screen.findByTestId("timeline-bars");
    expect(getTimeline).toHaveBeenCalledTimes(2);
  });
});

describe("HomePage(오늘 현황)", () => {
  it("제목 줄: 날짜 · 마지막 갱신 HH:MM:SS, 끊기면 '연결이 잠시 끊겼어요 · 마지막 갱신 …'(토스트 없음)", () => {
    const { unmount } = renderWith(<HomePage />);
    expect(screen.getByRole("heading", { level: 1, name: "오늘 현황" })).toBeInTheDocument();
    expect(screen.getByTestId("live-status-line").textContent).toMatch(/^\d+월 \d+일 .요일 · 마지막 갱신 \d\d:\d\d:\d\d$/);
    unmount();
    renderWith(<HomePage />, feed({ disconnected: true }));
    expect(screen.getByTestId("live-status-line").textContent).toMatch(/^연결이 잠시 끊겼어요 · 마지막 갱신 \d\d:\d\d:\d\d$/);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("코칭 카드: 신호 칩·제안·[이 단계 고치기] → 편집기 ?step=&fix= 1번", async () => {
    const user = userEvent.setup();
    const card: CoachingCard = {
      task_id: "t1", task_title: "컵 씻기", source_step_id: "src2", step_id: "s2", sentence: "물을 틀어요", thumb_url: null,
      signals: { replay_avg: 3.5, duration_avg_sec: 150, help_count: 2, runs: 4 }, suggestion: "photo", after: null,
    };
    getCoaching.mockResolvedValue([card]);
    renderWith(<HomePage />);
    const c = await screen.findByTestId("coaching-card");
    expect(c).toHaveTextContent("다시 듣기 평균 3.5번");
    expect(c).toHaveTextContent("평균 2분 30초");
    expect(c).toHaveTextContent("도움 2번");
    expect(c).toHaveTextContent("사진으로 바꾸기");
    await user.click(within(c).getByRole("link", { name: /^이 단계 고치기/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/m/tasks/t1?step=src2&fix=photo");
  });

  it("새 사업장: 시작 점검표 3단계와 [바로 하기]", async () => {
    renderWith(<HomePage />, feed({ data: liveOut({ workers: [], summary: { working: 0, total_workers: 0, open_help: 0, stuck_steps: 0, needs_check_tasks: 0 } }) }));
    const empty = screen.getByTestId("home-empty");
    expect(within(empty).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      expect.stringContaining("근로자 추가"),
      expect.stringContaining("기기 연결"),
      expect.stringContaining("첫 직무 보내기"),
    ]);
    expect(within(empty).getByRole("link", { name: "근로자 추가 바로 하기" })).toHaveAttribute("href", "/m/workers");
    expect(within(empty).getByRole("link", { name: "첫 직무 보내기 바로 하기" })).toHaveAttribute("href", "/m/tasks/new");
    expect(screen.queryByTestId("live-table")).not.toBeInTheDocument();
    await waitFor(() => expect(getCoaching).toHaveBeenCalled());
  });

  it("현황을 아직 못 받았고 끊겼으면 오류 안내(다시 불러옴)", async () => {
    renderWith(<HomePage />, feed({ data: null, help: [], updatedAt: null, disconnected: true }));
    expect(screen.getByText("현황을 불러오지 못했어요")).toBeInTheDocument();
    await act(async () => {});
  });
});
