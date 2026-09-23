import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import DashboardPage from "../src/pages/DashboardPage";

// 대시보드는 "근로자를 먼저 고르고 → 그 근로자의 날짜별 직무 → 집계"를 차례로 부른다
// (근로자 여러 명 배정 기능 도입 이후의 실제 흐름 — listTasks/coaching(id) 단일 인자로
// 부르던 옛 버전은 더 이상 없다).
const listWorkers = vi.fn();
const workerActiveDates = vi.fn();
const workerTasks = vi.fn();
const dashboard = vi.fn();
const coaching = vi.fn();

vi.mock("../src/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      listWorkers: () => listWorkers(),
      workerActiveDates: (id: string) => workerActiveDates(id),
      workerTasks: (id: string, date: string) => workerTasks(id, date),
      dashboard: (taskId: string, workerId: string) => dashboard(taskId, workerId),
      coaching: (taskId: string, workerId: string) => coaching(taskId, workerId),
    },
  };
});

const worker = { id: "w1", display_name: "김근로", access_code: "1111" };
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
    expect(dashboard).toHaveBeenCalledWith("task-1", "w1");
    expect(screen.getByText("상자를 옮기세요")).toBeInTheDocument();
    expect(screen.getByText("막힘 기록")).toBeInTheDocument();
  });

  it("등록된 근로자가 없으면 안내 문구를 보여준다", async () => {
    listWorkers.mockResolvedValue([]);
    render(<DashboardPage />);
    await screen.findByText(/아직 등록된 근로자가 없습니다/);
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
    expect(coaching).toHaveBeenCalledWith("task-1", "w1");
    expect(screen.getByText(/2단계 · photo/)).toBeInTheDocument();
  });
});
