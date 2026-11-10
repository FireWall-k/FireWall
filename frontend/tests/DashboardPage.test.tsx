import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DashboardPage from "../src/pages/DashboardPage";

// 대시보드는 "근로자를 먼저 고르고 → 그 근로자의 날짜별 직무 → 집계"를 차례로 부른다
// (근로자 여러 명 배정 기능 도입 이후의 실제 흐름 — listTasks/coaching(id) 단일 인자로
// 부르던 옛 버전은 더 이상 없다).
const listWorkers = vi.fn();
const workerActiveDates = vi.fn();
const workerTasks = vi.fn();
const dashboard = vi.fn();
const coaching = vi.fn();
const archiveTask = vi.fn();

vi.mock("../src/manager/api/tasks", () => ({ archiveTask: (id: string) => archiveTask(id) }));

vi.mock("../src/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      listWorkers: () => listWorkers(),
      workerActiveDates: (id: string) => workerActiveDates(id),
      workerTasks: (id: string, date: string) => workerTasks(id, date),
      dashboard: (taskId: string, workerId: string, date?: string) => dashboard(taskId, workerId, date),
      coaching: (taskId: string, workerId: string, date?: string) => coaching(taskId, workerId, date),
    },
  };
});

function ymd(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
const todayYmd = ymd(new Date());

const worker = { id: "w1", display_name: "김근로", access_code_hint: "11", access_code_length: 4 };
const task = { id: "task-1", title: "분류 작업", status: "published", created_at: "2026-09-20T00:00:00Z" };

const dashboardData = {
  task_id: "task-1", task_title: "분류 작업",
  total_steps: 2, completed_steps: 1, completion_rate: 50,
  stuck_steps: [2],
  steps: [
    { order: 1, sentence: "상자를 옮기세요", completed: true, duration_sec: 12, replay_count: 1, stuck: false },
    { order: 2, sentence: "수량을 확인하세요", completed: false, duration_sec: 0, replay_count: 4, stuck: true },
  ],
};

beforeEach(() => {
  listWorkers.mockReset();
  workerActiveDates.mockReset();
  workerTasks.mockReset();
  dashboard.mockReset();
  coaching.mockReset();
  workerActiveDates.mockResolvedValue([]);
});

describe("DashboardPage", () => {
  it("근로자·직무를 불러와 집계를 표시하고 막힌 단계를 노출한다", async () => {
    listWorkers.mockResolvedValue([worker]);
    workerTasks.mockResolvedValue([task]);
    dashboard.mockResolvedValue(dashboardData);
    coaching.mockResolvedValue({ summary: "", suggestions: [] });

    render(<DashboardPage />);

    await screen.findByText("50%");
    expect(screen.getByText(/2단계 확인 필요/)).toBeInTheDocument();
    expect(dashboard).toHaveBeenCalledWith("task-1", "w1", todayYmd);
    expect(screen.getByText("상자를 옮기세요")).toBeInTheDocument();
    expect(screen.getByText("막힘 기록")).toBeInTheDocument();
  });

  it("등록된 근로자가 없으면 안내 문구를 보여준다", async () => {
    listWorkers.mockResolvedValue([]);
    render(<DashboardPage />);
    await screen.findByText(/아직 등록된 근로자가 없어요. ‘근로자’ 메뉴에서/);
    expect(workerTasks).not.toHaveBeenCalled();
  });

  it("근로자는 있지만 그 날짜에 배정된 직무가 없으면 안내 문구를 보여준다", async () => {
    listWorkers.mockResolvedValue([worker]);
    workerTasks.mockResolvedValue([]);
    render(<DashboardPage />);
    await screen.findByText(/이 근로자에게 오늘 배정된 직무가 없습니다/);
    expect(dashboard).not.toHaveBeenCalled();
  });

  it("대시보드를 불러오면 AI 코칭 제안도 함께 표시된다", async () => {
    listWorkers.mockResolvedValue([worker]);
    workerTasks.mockResolvedValue([task]);
    dashboard.mockResolvedValue(dashboardData);
    coaching.mockResolvedValue({
      summary: "1개 단계에서 개선이 필요해 보입니다.",
      suggestions: [{ order: 2, issue: "다시듣기 과다", suggestion: "사진으로 교체하세요.", action: "photo" }],
    });

    render(<DashboardPage />);

    await screen.findByText(/사진으로 교체하세요/);
    expect(coaching).toHaveBeenCalledWith("task-1", "w1", todayYmd);
    expect(screen.getByText(/2단계 · photo/)).toBeInTheDocument();
    expect(screen.queryByText(/AI 처리 동의가 기록되지 않은/)).not.toBeInTheDocument();
  });

  it("동의 없는 근로자 기록이라 AI를 쓰지 않았으면 그 이유를 알려 준다", async () => {
    listWorkers.mockResolvedValue([worker]);
    workerTasks.mockResolvedValue([task]);
    dashboard.mockResolvedValue(dashboardData);
    coaching.mockResolvedValue({ summary: "1개 단계에서 개선이 필요해 보입니다.", suggestions: [], ai_excluded: true });

    render(<DashboardPage />);

    expect(await screen.findByText(/AI 처리 동의가 기록되지 않은 근로자가 있어/)).toBeInTheDocument();
  });

  it("2a-1: [삭제] 대신 [보관하기] — 확인하면 archive를 부르고(DELETE 아님) '보관함'으로 표시한다", async () => {
    listWorkers.mockResolvedValue([worker]);
    workerTasks.mockResolvedValue([task]);
    dashboard.mockResolvedValue(dashboardData);
    coaching.mockResolvedValue({ summary: "", suggestions: [] });
    archiveTask.mockReset().mockResolvedValue({});
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<DashboardPage />);
    await screen.findByText("50%");
    expect(screen.queryByRole("button", { name: /삭제/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "선택한 직무 보관하기" }));
    expect(confirm.mock.calls[0][0]).toContain("'분류 작업'을 보관함으로 옮길까요?");
    expect(archiveTask).toHaveBeenCalledWith("task-1");
    await waitFor(() => expect(screen.queryByRole("button", { name: "선택한 직무 보관하기" })).not.toBeInTheDocument());
    expect(screen.getByText("보관함에 있는 직무예요")).toBeInTheDocument();
    await waitFor(() => expect(document.activeElement?.id).toBe("dashboard-archived-note"));
    expect(screen.getByRole("option", { name: /분류 작업 \(보관함\)/ })).toBeInTheDocument();
    confirm.mockRestore();
  });

  it("2회차 검증: 보관 응답이 늦고 다음 프레임이 React 반영보다 먼저 와도 초점은 '보관함에 있는 직무예요'로 간다", async () => {
    listWorkers.mockResolvedValue([worker]);
    workerTasks.mockResolvedValue([task]);
    dashboard.mockResolvedValue(dashboardData);
    coaching.mockResolvedValue({ summary: "", suggestions: [] });
    let finish: (v: unknown) => void = () => {};
    archiveTask.mockReset().mockImplementation(() => new Promise((r) => { finish = r; }));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    // 실서버에서 본 경쟁: rAF 콜백이 setState 반영(커밋)보다 먼저 돈다. 콜백을 바로 돌려 그 순서를 만든다.
    const raf = vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => { cb(0); return 0; });
    render(<DashboardPage />);
    await screen.findByText("50%");
    const button = screen.getByRole("button", { name: "선택한 직무 보관하기" });
    button.focus();
    await userEvent.keyboard("{Enter}");
    expect(archiveTask).toHaveBeenCalledWith("task-1");
    finish({});
    await waitFor(() => expect(document.activeElement?.id).toBe("dashboard-archived-note"));
    expect(document.activeElement).not.toBe(document.body);
    raf.mockRestore();
    confirm.mockRestore();
  });

  it("2회차 검증: 보관이 끝나기 전에 다른 직무로 바꾸면 초점을 빼앗지 않는다", async () => {
    const other = { ...task, id: "task-2", title: "포장 작업" };
    listWorkers.mockResolvedValue([worker]);
    workerTasks.mockResolvedValue([task, other]);
    dashboard.mockResolvedValue(dashboardData);
    coaching.mockResolvedValue({ summary: "", suggestions: [] });
    let finish: (v: unknown) => void = () => {};
    archiveTask.mockReset().mockImplementation(() => new Promise((r) => { finish = r; }));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<DashboardPage />);
    await screen.findByText("50%");
    await userEvent.click(screen.getByRole("button", { name: "선택한 직무 보관하기" }));
    const select = screen.getByRole("combobox", { name: "대시보드 직무 선택" });
    await userEvent.selectOptions(select, "task-2");
    finish({});
    await waitFor(() => expect(screen.getByRole("option", { name: /분류 작업 \(보관함\)/ })).toBeInTheDocument());
    expect(document.activeElement?.id).not.toBe("dashboard-archived-note");
    confirm.mockRestore();
  });

  it("1회차 검증: 서버가 보관한 직무라고 주면 [보관하기]를 띄우지 않는다(다시 열어도 또 보관하지 않음)", async () => {
    listWorkers.mockResolvedValue([worker]);
    workerTasks.mockResolvedValue([{ ...task, archived: true }]);
    dashboard.mockResolvedValue(dashboardData);
    coaching.mockResolvedValue({ summary: "", suggestions: [] });
    archiveTask.mockReset();
    render(<DashboardPage />);
    await screen.findByText("50%");
    expect(screen.queryByRole("button", { name: "선택한 직무 보관하기" })).not.toBeInTheDocument();
    expect(screen.getByText("보관함에 있는 직무예요")).toBeInTheDocument();
    expect(archiveTask).not.toHaveBeenCalled();
  });

  it("보관 확인을 취소하면 아무것도 부르지 않는다", async () => {
    listWorkers.mockResolvedValue([worker]);
    workerTasks.mockResolvedValue([task]);
    dashboard.mockResolvedValue(dashboardData);
    coaching.mockResolvedValue({ summary: "", suggestions: [] });
    archiveTask.mockReset();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<DashboardPage />);
    await screen.findByText("50%");
    await userEvent.click(screen.getByRole("button", { name: "선택한 직무 보관하기" }));
    expect(archiveTask).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  // 2회차 검증: 달력에서 지난 날을 고르면 같은 직무라도 그날 배정의 숫자를 묻는다(오늘 배정의 숫자가 아님).
  it("달력에서 다른 날을 고르면 대시보드·코칭을 그 날짜로 다시 부른다", async () => {
    listWorkers.mockResolvedValue([worker]);
    workerTasks.mockResolvedValue([task]);
    dashboard.mockResolvedValue(dashboardData);
    coaching.mockResolvedValue({ summary: "", suggestions: [] });
    const user = userEvent.setup();

    render(<DashboardPage />);
    await screen.findByText("50%");
    expect(dashboard).toHaveBeenLastCalledWith("task-1", "w1", todayYmd);

    const now = new Date();
    const pickDay = now.getDate() === 1 ? 2 : 1;
    const picked = ymd(new Date(now.getFullYear(), now.getMonth(), pickDay));
    await user.click(screen.getByRole("button", { name: "날짜 선택 달력 열기" }));
    await user.click(screen.getByRole("button", { name: String(pickDay) }));

    await vi.waitFor(() => expect(dashboard).toHaveBeenCalledWith("task-1", "w1", picked));
    expect(workerTasks).toHaveBeenCalledWith("w1", picked);
    expect(coaching).toHaveBeenCalledWith("task-1", "w1", picked);
    // 새 날짜의 직무 목록이 오기 전에 옛 목록의 직무를 새 날짜로 묻지 않는다(목록이 온 뒤에만).
    const pickedCall = dashboard.mock.calls.findIndex((c) => c[2] === picked);
    expect(workerTasks.mock.invocationCallOrder[1]).toBeLessThan(dashboard.mock.invocationCallOrder[pickedCall]);
  });
});
