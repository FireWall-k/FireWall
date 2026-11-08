import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
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
  // 문장 텍스트는 커밋 시점에 바로 DOM에 반영되지만, 소요시간 측정을 시작하는
  // useEffect(stepStartRef.current = Date.now())는 그 다음 tick의 passive effect라
  // 둘 사이에 간극이 있다. 시스템이 느리면(전체 스위트를 함께 돌릴 때) findByText가
  // 먼저 끝나버려 시작 시각이 아직 0인 채로 클릭이 들어가 "경과 120초 이상"으로
  // 오판했다(실측, 간헐적 실패). act(async () => {})로 남은 effect를 마저 흘려보낸다.
  await act(async () => {});
}

describe("WorkerPage stuck 수집", () => {
  it("정상 완료 시 stuck=false 로 보고한다", async () => {
    // 소요시간(실제 경과 시간)이 120초를 넘으면 stuck=true가 된다. 전체 테스트 스위트를
    // 같이 돌릴 때 시스템이 느려지면 렌더~클릭 사이 실제 시간이 드물게 그 문턱을 넘어
    // 간헐적으로 실패했다(실측). Date.now()를 고정해 경과 시간을 0으로 만든다.
    const nowSpy = vi.spyOn(Date, "now").mockReturnValue(1_700_000_000_000);
    await renderAndWait();
    fireEvent.click(screen.getByText("✓ 완료"));
    await waitFor(() => expect(logStep).toHaveBeenCalled());
    expect(logStep.mock.calls[0][0]).toMatchObject({ step_id: "s1", stuck: false });
    nowSpy.mockRestore();
  });

  it("'도움이 필요해요'를 누르면 즉시 stuck=true 로 보고된다(대시보드에 바로 반영)", async () => {
    await renderAndWait();
    fireEvent.click(screen.getByText("🙋 도움이 필요해요"));
    await waitFor(() => expect(logStep).toHaveBeenCalledTimes(1));
    expect(logStep.mock.calls[0][0]).toMatchObject({ step_id: "s1", stuck: true });
  });

  it("'도움이 필요해요'만 눌러서는 다음 단계로 넘어가지 않는다(완료를 따로 눌러야 한다)", async () => {
    await renderAndWait();
    fireEvent.click(screen.getByText("🙋 도움이 필요해요"));
    await waitFor(() => expect(logStep).toHaveBeenCalledTimes(1));
    expect(screen.getByText("상자를 옮기세요")).toBeInTheDocument();
    expect(screen.getByText("🙋 요청했어요")).toBeInTheDocument();
  });

  it("도움 요청 후 완료를 누르면 같은 단계가 한 번 더(최종 상태로) 보고되고 다음 단계로 넘어간다", async () => {
    await renderAndWait();
    fireEvent.click(screen.getByText("🙋 도움이 필요해요"));
    await waitFor(() => expect(logStep).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText("✓ 완료"));
    await waitFor(() => expect(logStep).toHaveBeenCalledTimes(2));
    expect(logStep.mock.calls[1][0]).toMatchObject({ step_id: "s1", stuck: true });
    await screen.findByText("수량을 확인하세요");
  });

  it("도움 요청 후 다시 눌러도 중복 보고하지 않는다", async () => {
    await renderAndWait();
    const help = screen.getByText("🙋 도움이 필요해요");
    fireEvent.click(help);
    await waitFor(() => expect(logStep).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText("🙋 요청했어요"));
    await new Promise((r) => setTimeout(r, 0));
    expect(logStep).toHaveBeenCalledTimes(1);
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

  it("사진 서명 URL이 만료되면 오늘 카드를 다시 받아 새 URL로 바꾼다(한 URL당 한 번)", async () => {
    const signed = (n: number) => `http://localhost:8000/api/media/m1?exp=${n}&sig=s${n}`;
    const withPhoto = (url: string) => ({
      ...card, steps: [{ ...card.steps[0], symbol_url: url, symbol_source: "photo" }, card.steps[1]],
    });
    today.mockResolvedValueOnce([withPhoto(signed(1))]).mockResolvedValue([withPhoto(signed(2))]);
    await renderAndWait();
    const img = screen.getByAltText("상자를 옮기세요");
    expect(img).toHaveAttribute("src", signed(1));

    fireEvent.error(img);  // 만료(403)로 그림을 못 불러온 상황
    await waitFor(() => expect(screen.getByAltText("상자를 옮기세요")).toHaveAttribute("src", signed(2)));
    expect(today).toHaveBeenCalledTimes(2);
    // 보던 단계는 그대로다(처음 단계로 되돌아가지 않는다).
    expect(screen.getByText("상자를 옮기세요")).toBeInTheDocument();

    // 같은 URL로 또 실패해도 다시 조회하지 않는다(무한 재조회 방지).
    fireEvent.error(screen.getByAltText("상자를 옮기세요"));
    fireEvent.error(screen.getByAltText("상자를 옮기세요"));
    await act(async () => {});
    expect(today).toHaveBeenCalledTimes(3);
    fireEvent.error(screen.getByAltText("상자를 옮기세요"));
    await act(async () => {});
    expect(today).toHaveBeenCalledTimes(3);
  });

  it("배정이 없으면 안내 문구를 보여준다", async () => {
    today.mockResolvedValue([]);
    render(<WorkerPage />);
    await screen.findByText(/오늘 받은 일이 아직 없어요/);
  });

  it("현재 단계의 동작 칩은 근로자 화면에 없다(0차 3번, 예전 기능 4)", async () => {
    await renderAndWait();              // step1 action_type = "move"
    expect(screen.queryByText("옮기기")).not.toBeInTheDocument();
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

  it("'지난 일 보기'를 누르면 완료한 일을 목록으로 보여주고, 눌러 열면 그림을 다시 볼 수 있다", async () => {
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

// ---------- 단계 화면 정리(진행 표시 하나·꼬리표 확신·직무 사이 목록) ----------

describe("WorkerPage 단계 화면", () => {
  const secondCard = {
    assignment_id: "asg-2", task_id: "task-2", task_title: "두 번째 직무",
    steps: [
      { id: "t1", order: 1, sentence: "손님께 인사하세요", action_type: "observe",
        symbol_url: null, symbol_source: "fallback", needs_fallback: true, tts_audio_url: null },
    ],
  };

  it("진행 표시는 하나뿐이다(오늘 몇 번째 일인지는 단계 화면에 띄우지 않는다)", async () => {
    today.mockResolvedValue([card, secondCard]);
    await renderAndWait();
    expect(screen.getAllByTestId("step-progress")).toHaveLength(1);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "1");
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuemax", "2");
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    expect(screen.queryByText(/번째/)).not.toBeInTheDocument();
  });

  it("직무를 마치면 오늘 할 일 목록에서 몇 번째까지 했는지 보여 준다", async () => {
    today.mockResolvedValue([card, secondCard]);
    await renderAndWait();
    fireEvent.click(screen.getByText("✓ 완료"));
    await screen.findByText("수량을 확인하세요");
    fireEvent.click(screen.getByText("✓ 완료"));
    await screen.findByText(/다음 일 시작하기/);
    expect(screen.getByText("오늘 할 일 2개 중 1개를 마쳤어요.")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "오늘 할 일" });
    expect(list).toHaveTextContent("테스트 직무");
    expect(list).toHaveTextContent("두 번째 직무");
  });

  // 0차 3번: 동작 꼬리표(ActionChip)를 근로자 화면에서 뺐다(문장·그림이 동작을 말한다).
  it("동작 꼬리표를 보이지 않는다(저장된 action_type이 있어도)", async () => {
    today.mockResolvedValue([{ ...secondCard, steps: [{ ...secondCard.steps[0], sentence: "박스 바닥 덮개를 접으세요", action_type: "pack" }] }]);
    render(<WorkerPage />);
    await screen.findByText("박스 바닥 덮개를 접으세요");
    expect(screen.queryByTestId("action-chip")).not.toBeInTheDocument();
    expect(screen.queryByText("접기")).not.toBeInTheDocument();
  });

  it("도움 요청이 서버에 닿지 않으면 '아직 못 불렀어요'를 보이고 다시 누를 수 있다", async () => {
    logStep.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await renderAndWait();
    fireEvent.click(screen.getByText("🙋 도움이 필요해요"));
    expect(await screen.findByText("아직 못 불렀어요. 손을 들어 선생님을 불러요.")).toBeInTheDocument();
    expect(screen.getByText("🙋 도움이 필요해요")).toBeInTheDocument();
  });

  it("불러오지 못하면 영어 원문 대신 쉬운 문장을 24px로 보인다", async () => {
    today.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<WorkerPage />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("인터넷이 안 돼요");
    expect(alert).not.toHaveTextContent(/[A-Za-z]/);
    expect(alert).toHaveClass("text-worker");
  });

  it("그림은 한 단계에 한 장이다", async () => {
    today.mockResolvedValue([{ ...card, steps: [{ ...card.steps[0], symbol_url: "https://x/img.png" }] }]);
    await renderAndWait();
    expect(screen.getByTestId("step-picture").querySelectorAll("img")).toHaveLength(1);
  });
});

describe("WorkerPage 지난 일 → 오늘 할 일", () => {
  it("지난 일 화면에서 '← 오늘 할 일로'를 누르면 단계 화면으로 돌아온다", async () => {
    await renderAndWait();
    fireEvent.click(screen.getByText("지난 일 보기"));
    await screen.findByText("아직 받은 일이 없어요.");
    fireEvent.click(screen.getByText("← 오늘 할 일로"));
    await screen.findByText("상자를 옮기세요");
  });
});
