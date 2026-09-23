import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import WorkerPage from "../src/pages/WorkerPage";

const logStep = vi.fn().mockResolvedValue({ ok: true });
const today = vi.fn();
const history = vi.fn();

vi.mock("../src/api", () => ({
  AuthError: class extends Error {},
  api: {
    today: () => today(),
    history: () => history(),
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
  history.mockReset();
  history.mockResolvedValue([]);
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

// ---------- 지난 일 보기(이번 세션에 추가된 기능) ----------
// 완료한 일은 today()에서 빠지므로, history()로 다시 볼 수 있는지 검증한다.

describe("WorkerPage 지난 일 보기", () => {
  const historyCard = {
    assignment_id: "asg-0", task_id: "task-0", task_title: "바닥 청소",
    assigned_date: "2026-09-20", status: "done",
    steps: [
      { id: "s0", order: 1, sentence: "바닥을 쓸어주세요", action_type: "clean",
        symbol_url: null, symbol_source: "fallback", needs_fallback: false,
        tts_audio_url: null, completed: true },
    ],
  };

  it("탭을 누르면 완료한 일을 목록으로 보여주고, 눌러 열면 그림을 다시 볼 수 있다", async () => {
    history.mockResolvedValue([historyCard]);
    await renderAndWait();

    fireEvent.click(screen.getByText("지난 일 보기"));
    await screen.findByText("바닥 청소");
    expect(history).toHaveBeenCalled();

    fireEvent.click(screen.getByText("바닥 청소"));
    await screen.findByText("바닥을 쓸어주세요");
    expect(screen.getByText("✓ 완료했어요")).toBeInTheDocument();
    // 복습 화면은 읽기 전용이다 — 완료 처리를 다시 하면 안 된다.
    expect(screen.queryByText("✓ 완료")).not.toBeInTheDocument();
  });

  it("받은 일이 없으면 안내 문구를 보여준다", async () => {
    history.mockResolvedValue([]);
    await renderAndWait();
    fireEvent.click(screen.getByText("지난 일 보기"));
    await screen.findByText("아직 받은 일이 없어요.");
  });
});
