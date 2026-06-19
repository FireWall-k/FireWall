import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import WorkerPage from "../src/pages/WorkerPage";

const logStep = vi.fn().mockResolvedValue({ ok: true });
const today = vi.fn();

vi.mock("../src/api", () => ({
  AuthError: class extends Error {},
  api: {
    today: () => today(),
    logStep: (b: unknown) => logStep(b),
  },
}));

const card = {
  assignment_id: "asg-1",
  task_id: "task-1",
  task_title: "테스트 직무",
  steps: [
    { id: "s1", order: 1, sentence: "상자를 옮기세요", action_type: "move",
      symbol_url: null, symbol_source: "fallback", needs_fallback: true, tts_audio_url: null },
    { id: "s2", order: 2, sentence: "수량을 확인하세요", action_type: "observe",
      symbol_url: null, symbol_source: "fallback", needs_fallback: true, tts_audio_url: null },
  ],
};

beforeEach(() => {
  logStep.mockClear();
  today.mockReset();
  today.mockResolvedValue([card]);
});

async function renderAndWait() {
  render(<WorkerPage />);
  await screen.findByText("상자를 옮기세요");
}

describe("WorkerPage stuck 수집", () => {
  it("정상 완료 시 stuck=false 로 보고한다", async () => {
    await renderAndWait();
    fireEvent.click(screen.getByText("✓ 완료"));
    await waitFor(() => expect(logStep).toHaveBeenCalled());
    expect(logStep.mock.calls[0][0]).toMatchObject({ step_id: "s1", stuck: false });
  });

  it("'도움이 필요해요'를 누르면 stuck=true 로 보고한다", async () => {
    await renderAndWait();
    fireEvent.click(screen.getByText("🙋 도움이 필요해요"));
    fireEvent.click(screen.getByText("✓ 완료"));
    await waitFor(() => expect(logStep).toHaveBeenCalled());
    expect(logStep.mock.calls[0][0]).toMatchObject({ step_id: "s1", stuck: true });
  });

  it("다시듣기 3회 이상이면 자동으로 stuck=true 로 보고한다", async () => {
    await renderAndWait();
    const replay = screen.getByText("🔊 다시 듣기");
    fireEvent.click(replay);
    fireEvent.click(replay);
    fireEvent.click(replay);
    fireEvent.click(screen.getByText("✓ 완료"));
    await waitFor(() => expect(logStep).toHaveBeenCalled());
    expect(logStep.mock.calls[0][0]).toMatchObject({ step_id: "s1", stuck: true, replay_count: 3 });
  });

  it("두 단계를 모두 마치면 완료 화면을 보여준다", async () => {
    await renderAndWait();
    fireEvent.click(screen.getByText("✓ 완료")); // step1
    await screen.findByText("수량을 확인하세요");
    fireEvent.click(screen.getByText("✓ 완료")); // step2
    await screen.findByText("오늘 일을 모두 마쳤어요!");
    expect(logStep).toHaveBeenCalledTimes(2);
  });

  it("배정이 없으면 안내 문구를 보여준다", async () => {
    today.mockResolvedValue([]);
    render(<WorkerPage />);
    await screen.findByText(/오늘 받은 일이 아직 없어요/);
  });

  it("현재 단계의 동작을 칩으로 보여준다(기능 4)", async () => {
    await renderAndWait();              // step1 action_type = "move"
    expect(screen.getByText("옮기기")).toBeInTheDocument();
  });

});
