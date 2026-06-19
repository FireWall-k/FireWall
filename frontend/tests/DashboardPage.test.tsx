import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import DashboardPage from "../src/pages/DashboardPage";

const listTasks = vi.fn();
const dashboard = vi.fn();
const coaching = vi.fn();

vi.mock("../src/api", () => ({
  api: {
    listTasks: () => listTasks(),
    dashboard: (id: string) => dashboard(id),
    coaching: (id: string) => coaching(id),
  },
}));

beforeEach(() => {
  listTasks.mockReset();
  dashboard.mockReset();
  coaching.mockReset();
});

describe("DashboardPage", () => {
  it("직무 목록을 불러와 첫 직무의 집계를 표시하고 막힌 단계를 노출한다", async () => {
    listTasks.mockResolvedValue([{ id: "task-1", title: "분류 작업", status: "published" }]);
    dashboard.mockResolvedValue({
      task_id: "task-1", task_title: "분류 작업",
      total_steps: 2, completed_steps: 1, completion_rate: 50.0,
      stuck_steps: [2],
      steps: [
        { order: 1, sentence: "상자를 옮기세요", completed: true, duration_sec: 12, replay_count: 1, stuck: false },
        { order: 2, sentence: "수량을 확인하세요", completed: false, duration_sec: 0, replay_count: 4, stuck: true },
      ],
    });

    render(<DashboardPage />);
    await screen.findByText("50%");
    await screen.findByText(/막힌 단계: 2/);
    expect(dashboard).toHaveBeenCalledWith("task-1");
    expect(screen.getByText("상자를 옮기세요")).toBeInTheDocument();
  });

  it("직무가 없으면 빈 옵션을 표시한다", async () => {
    listTasks.mockResolvedValue([]);
    render(<DashboardPage />);
    await screen.findByText("직무 없음");
    expect(dashboard).not.toHaveBeenCalled();
  });

  it("'제안 받기'를 누르면 AI 코칭 제안을 표시한다", async () => {
    listTasks.mockResolvedValue([{ id: "task-1", title: "분류 작업", status: "published" }]);
    dashboard.mockResolvedValue({
      task_id: "task-1", task_title: "분류 작업",
      total_steps: 2, completed_steps: 2, completion_rate: 100.0, stuck_steps: [2],
      steps: [],
    });
    coaching.mockResolvedValue({
      summary: "1개 단계에서 개선이 필요해 보입니다.",
      suggestions: [{ order: 2, issue: "다시듣기 과다", suggestion: "사진으로 교체하세요.", action: "photo" }],
    });

    const { findByText, getByText } = render(<DashboardPage />);
    await findByText("50%".replace("50","100"));
    fireEvent.click(getByText("제안 받기"));
    await findByText(/사진으로 교체하세요/);
    expect(coaching).toHaveBeenCalledWith("task-1");
    expect(getByText("사진으로 교체")).toBeInTheDocument();
  });

});
