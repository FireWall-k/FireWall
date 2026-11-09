import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ManagerPage from "../src/pages/ManagerPage";
import { ApiError } from "../src/apiErrors";

const createTask = vi.fn();
const splitPreview = vi.fn();
const rewriteStep = vi.fn();
const mergeSteps = vi.fn();
const uploadStepPhoto = vi.fn();
const removeStepPhoto = vi.fn();
const listWorkers = vi.fn();
const createWorker = vi.fn();
const publish = vi.fn();
const assign = vi.fn();
// 자동 채택 못 한(needs_fallback=true) 단계는 마운트 시 후보를 조회한다 — 목이 없으면 깨진다.
const stepSymbolCandidates = vi.fn().mockResolvedValue({ step_id: "s1", reason: "no_candidate", candidates: [] });
// (2a-0) 새 호출(src/manager/api/send.ts)은 공용 req를 쓴다 — 경로·메서드를 그대로 확인한다.
const reqMock = vi.fn();

vi.mock("../src/api", () => ({
  api: {
    createTask: (raw: string, ctx: unknown) => createTask(raw, ctx),
    splitPreview: (raw: string, ctx: unknown) => splitPreview(raw, ctx),
    rewriteStep: (t: string, s: string, sentence: string) => rewriteStep(t, s, sentence),
    mergeSteps: (t: string, ids: string[], sentence: string) => mergeSteps(t, ids, sentence),
    uploadStepPhoto: (t: string, s: string, f: File) => uploadStepPhoto(t, s, f),
    removeStepPhoto: (t: string, s: string) => removeStepPhoto(t, s),
    stepSymbolCandidates: (t: string, s: string) => stepSymbolCandidates(t, s),
    listWorkers: () => listWorkers(),
    createWorker: (name: string, code?: string) => createWorker(name, code),
    publish: (id: string) => publish(id),
    assign: (id: string, workerIds: string[]) => assign(id, workerIds),
    updateStep: vi.fn(),
  },
  req: (path: string, init?: RequestInit) => reqMock(path, init),
}));

// 단계로 나누기 버튼은 직무 내용이 비어 있으면 비활성 상태다 — 모든 테스트가 이걸 거친다.
// 나누기는 입력 화면에서 끝낸다: [단계로 나누기] → 나눈 줄 확인 → [이대로 그림 고르기]를 눌러야 초안·편집기가 생긴다.
async function typeAndDecompose(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("직무 내용"), "상자를 옮겨주세요.");
  await user.click(screen.getByRole("button", { name: "단계로 나누기" }));
  await user.click(await screen.findByRole("button", { name: "이대로 그림 고르기 ›" }));
}

const previewStep = {
  order: 1, sentence: "상자를 옮기세요", action_type: "move", symbol_query: ["상자"],
  split_group: null as number | null, split_check: false, source_text: null as string | null,
};

const baseStep = {
  id: "s1", order: 1, sentence: "상자를 옮기세요", action_type: "move",
  symbol_url: null as string | null, symbol_source: "fallback", needs_fallback: true,
  tts_audio_url: null as string | null,
};
// 그림(현장 사진)이 붙은 단계 — 보내기 테스트용(그림 없는 단계는 보내기가 막힌다).
const photoStep = {
  ...baseStep, symbol_url: "http://localhost:8000/api/media/p1?sig=x", symbol_source: "photo", needs_fallback: false,
  picture_state: "confirmed",
};

beforeEach(() => {
  createTask.mockReset();
  splitPreview.mockReset();
  rewriteStep.mockReset();
  mergeSteps.mockReset();
  splitPreview.mockResolvedValue({ task_title: "직무", job: "", steps: [previewStep] });
  uploadStepPhoto.mockReset();
  removeStepPhoto.mockReset();
  listWorkers.mockReset();
  publish.mockReset();
  assign.mockReset();
  createTask.mockResolvedValue({ id: "task-1", title: "직무", status: "draft", steps: [baseStep] });
  listWorkers.mockResolvedValue([]);
  reqMock.mockReset();
  // 그림 확인은 서버가 확인함으로 둔 단계를 돌려준다.
  reqMock.mockImplementation(async (path: string) => {
    const m = /\/steps\/([^/]+)\/picture\/confirm$/.exec(path);
    if (m) {
      return {
        ...baseStep, id: m[1], symbol_url: "http://localhost:8000/api/aac/images/cafe/CAFE_012.webp",
        symbol_source: "LOCAL_AAC", needs_fallback: false, picture_state: "confirmed",
      };
    }
    throw new Error(`목 없음: ${path}`);
  });
});

describe("ManagerPage 사진 업로드 (기능 5)", () => {
  it("단계에 사진을 올리면 uploadStepPhoto를 호출하고 상징이 사진으로 바뀐다", async () => {
    const user = userEvent.setup();
    uploadStepPhoto.mockResolvedValue({
      ...baseStep, symbol_url: "http://localhost:8000/api/photos/x.png",
      symbol_source: "photo", needs_fallback: false,
    });

    render(<ManagerPage />);
    await typeAndDecompose(user);
    // 단계가 렌더되면 '사진 올리기' 라벨이 보인다(문장은 input value라 텍스트로 안 잡힘).
    await screen.findByText("사진 올리기");

    const fileInput = screen.getByLabelText("1단계 사진 업로드") as HTMLInputElement;
    const file = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "p.png", { type: "image/png" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => expect(uploadStepPhoto).toHaveBeenCalledWith("task-1", "s1", file));
    // 업로드 후 '사진 교체' + '되돌리기' 노출
    await screen.findByText("사진 교체");
    expect(screen.getByText("되돌리기")).toBeInTheDocument();
    expect(screen.getByText(/직접 올린 사진/)).toBeInTheDocument();
  });

  it("'되돌리기'를 누르면 removeStepPhoto를 호출한다", async () => {
    const user = userEvent.setup();
    createTask.mockResolvedValue({
      id: "task-1", title: "직무", status: "draft",
      steps: [{ ...baseStep, symbol_url: "http://localhost:8000/api/photos/x.png",
                symbol_source: "photo", needs_fallback: false }],
    });
    removeStepPhoto.mockResolvedValue({ ...baseStep });

    render(<ManagerPage />);
    await typeAndDecompose(user);
    await screen.findByText("되돌리기");
    fireEvent.click(screen.getByText("되돌리기"));
    await waitFor(() => expect(removeStepPhoto).toHaveBeenCalledWith("task-1", "s1"));
  });
});

// ---------- 인라인 근로자 추가: 결과는 입력칸 바로 아래에 ----------

describe("ManagerPage — 인라인 근로자 추가", () => {
  it("추가 실패 오류가 화면 맨 위가 아니라 추가 입력칸 바로 아래에 뜬다", async () => {
    const user = userEvent.setup();
    createWorker.mockReset().mockRejectedValue(new Error("이미 사용 중인 접속 코드입니다. 다른 코드를 입력해 주세요."));
    render(<ManagerPage />);
    await typeAndDecompose(user);
    await user.type(await screen.findByLabelText("새 근로자 이름"), "박알바");
    await user.type(screen.getByLabelText("새 근로자 접속 코드"), "1234");
    await user.click(screen.getByRole("button", { name: "+ 근로자 추가" }));

    const msgs = await screen.findAllByText(/이미 사용 중인 접속 코드/);
    expect(msgs).toHaveLength(1); // 위쪽 배너에는 띄우지 않는다
    const addButton = screen.getByRole("button", { name: "+ 근로자 추가" });
    // 버튼이 든 입력 줄 바로 다음 요소가 오류 문구다.
    expect(addButton.parentElement?.nextElementSibling).toBe(msgs[0]);
  });

  it("보내기 목록에는 이름만, 등록된 근로자 목록은 번호를 가리고 눈 단추를 누르면 보인다(명세 5.6)", async () => {
    const user = userEvent.setup();
    listWorkers.mockResolvedValue([
      { id: "w1", display_name: "김근로", access_code: "1234", access_code_hint: "34", access_code_length: 4 },
    ]);
    render(<ManagerPage />);
    await typeAndDecompose(user);
    const box = await screen.findByRole("checkbox", { name: "김근로" });
    expect(box.closest("label")).not.toHaveTextContent("1234");
    expect(document.body).not.toHaveTextContent("1234");
    expect(screen.getByTestId("code-w1")).toHaveTextContent("●●●●");

    await user.click(screen.getByRole("button", { name: "김근로 번호 보기" }));
    expect(screen.getByTestId("code-w1")).toHaveTextContent("1234");
    await user.click(screen.getByRole("button", { name: "김근로 번호 가리기" }));
    expect(screen.getByTestId("code-w1")).toHaveTextContent("●●●●");
  });

  it("번호를 보이게 해도 5초 뒤에는 다시 가린다", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      listWorkers.mockResolvedValue([
        { id: "w1", display_name: "김근로", access_code: "1234", access_code_hint: "34", access_code_length: 4 },
      ]);
      render(<ManagerPage />);
      await typeAndDecompose(user);
      await user.click(await screen.findByRole("button", { name: "김근로 번호 보기" }));
      expect(screen.getByTestId("code-w1")).toHaveTextContent("1234");
      await act(async () => {
        vi.advanceTimersByTime(5_100);
      });
      expect(screen.getByTestId("code-w1")).toHaveTextContent("●●●●");
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("ManagerPage — 그림 없는 단계는 보낼 수 없다(0차)", () => {
  beforeEach(() => {
    listWorkers.mockResolvedValue([{ id: "w1", display_name: "김근로", access_code_hint: "11", access_code_length: 4 }]);
  });

  it("그림 없는 단계가 있으면 보내기 버튼이 막히고 몇 단계인지 알려 준다", async () => {
    const user = userEvent.setup();
    createTask.mockResolvedValue({
      id: "task-1", title: "직무", status: "draft",
      steps: [
        { ...photoStep, id: "s1", order: 1 },
        { ...baseStep, id: "s2", order: 2 },
        { ...baseStep, id: "s3", order: 3, picture_state: "none" },
      ],
    });
    render(<ManagerPage />);
    await typeAndDecompose(user);
    await screen.findByRole("checkbox", { name: /김근로/ });
    expect(screen.getByRole("button", { name: /게시하고 보내기/ })).toBeDisabled();
    expect(screen.getByText("그림이 없는 단계가 있어요(2, 3단계). 그림을 고른 뒤 보내 주세요.")).toBeInTheDocument();
  });

  it("서버가 그림 없음을 422로 막으면 그 문장을 그대로 보인다", async () => {
    const user = userEvent.setup();
    createTask.mockResolvedValue({ id: "task-1", title: "직무", status: "draft", steps: [photoStep] });
    publish.mockRejectedValue(new Error("그림이 없는 단계가 있어요(1단계). 그림을 고르거나 사진을 올린 뒤 보내 주세요."));
    render(<ManagerPage />);
    await typeAndDecompose(user);
    await screen.findByRole("checkbox", { name: /김근로/ });
    await user.click(screen.getByRole("button", { name: /게시하고 보내기/ }));
    expect((await screen.findAllByText(/그림을 고르거나 사진을 올린 뒤 보내 주세요/)).length).toBeGreaterThanOrEqual(1);
  });
});

// ---------- 근로자 여러 명에게 보내기(이번 세션에 추가된 기능) ----------

const workers = [
  { id: "w1", display_name: "김근로", access_code_hint: "11", access_code_length: 4 },
  { id: "w2", display_name: "박알바", access_code_hint: "22", access_code_length: 4 },
];

describe("ManagerPage — 근로자 여러 명에게 보내기", () => {
  beforeEach(() => {
    listWorkers.mockResolvedValue(workers);
    createTask.mockResolvedValue({ id: "task-1", title: "직무", status: "draft", steps: [photoStep] });
    publish.mockResolvedValue({ id: "task-1", title: "직무", status: "published", steps: [photoStep] });
  });

  it("근로자를 여러 명 체크하면 보내기 버튼에 인원수가 표시된다", async () => {
    const user = userEvent.setup();
    render(<ManagerPage />);
    await typeAndDecompose(user);
    await screen.findByRole("checkbox", { name: /김근로/ }); // 첫 근로자는 기본 선택됨

    await user.click(screen.getByRole("checkbox", { name: /박알바/ }));

    expect(screen.getByRole("button", { name: "게시하고 2명에게 보내기" })).toBeInTheDocument();
  });

  it("보내면 버튼 바로 아래에도 결과가 뜬다(상단 배너뿐 아니라)", async () => {
    const user = userEvent.setup();
    assign.mockResolvedValue([
      { id: "a1", task_id: "task-1", worker_id: "w1", status: "assigned" },
      { id: "a2", task_id: "task-1", worker_id: "w2", status: "assigned" },
    ]);
    render(<ManagerPage />);
    await typeAndDecompose(user);
    await user.click(await screen.findByRole("checkbox", { name: /박알바/ }));

    await user.click(screen.getByRole("button", { name: "게시하고 2명에게 보내기" }));

    const messages = await screen.findAllByText(/김근로, 박알바님에게 보냈습니다/);
    expect(messages.length).toBeGreaterThanOrEqual(2); // 상단 배너 + 버튼 아래 인라인
    expect(assign).toHaveBeenCalledWith("task-1", ["w1", "w2"]);
  });

  it("배정에 실패하면 실패 메시지가 남는다(자동으로 사라지지 않음)", async () => {
    const user = userEvent.setup();
    assign.mockRejectedValue(new Error("네트워크 오류"));
    render(<ManagerPage />);
    await typeAndDecompose(user);
    await screen.findByRole("checkbox", { name: /김근로/ });

    await user.click(screen.getByRole("button", { name: /게시하고 보내기/ }));

    expect((await screen.findAllByText("네트워크 오류")).length).toBeGreaterThanOrEqual(1);
  });
});

describe("ManagerPage — 자동으로 고른 그림은 확인해야 보낼 수 있다", () => {
  const autoStep = {
    ...baseStep, symbol_url: "http://localhost:8000/api/aac/images/cafe/CAFE_012.webp",
    symbol_source: "LOCAL_AAC", needs_fallback: false,
  };

  beforeEach(() => {
    listWorkers.mockResolvedValue(workers);
    createTask.mockResolvedValue({ id: "task-1", title: "직무", status: "draft", steps: [autoStep] });
    publish.mockResolvedValue({ id: "task-1", title: "직무", status: "published", steps: [autoStep] });
    assign.mockResolvedValue([{ id: "a1", task_id: "task-1", worker_id: "w1", status: "assigned" }]);
  });

  it("확인 전에는 보내기 버튼이 막히고 안내가 뜬다", async () => {
    const user = userEvent.setup();
    render(<ManagerPage />);
    await typeAndDecompose(user);
    await screen.findByRole("checkbox", { name: /김근로/ });

    expect(screen.getByRole("button", { name: /게시하고 보내기/ })).toBeDisabled();
    expect(screen.getByText(/자동으로 고른 그림 1장을 확인해야/)).toBeInTheDocument();
    expect(publish).not.toHaveBeenCalled();
  });

  it("그림을 확인하면 보낼 수 있다", async () => {
    const user = userEvent.setup();
    render(<ManagerPage />);
    await typeAndDecompose(user);
    await screen.findByRole("checkbox", { name: /김근로/ });

    await user.click(screen.getByRole("button", { name: "1단계 그림 확인" }));
    expect(screen.getByText("✓ 확인함")).toBeInTheDocument();
    const send = screen.getByRole("button", { name: /게시하고 보내기/ });
    expect(send).toBeEnabled();
    await user.click(send);
    await waitFor(() => expect(assign).toHaveBeenCalledWith("task-1", ["w1"]));
  });

  it("그림 대신 사진을 올린 단계는 따로 확인하지 않아도 된다", async () => {
    const user = userEvent.setup();
    uploadStepPhoto.mockResolvedValue({
      ...autoStep, symbol_url: "http://localhost:8000/api/photos/x.png", symbol_source: "photo",
    });
    render(<ManagerPage />);
    await typeAndDecompose(user);
    await screen.findByRole("checkbox", { name: /김근로/ });

    const file = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "p.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("1단계 사진 업로드"), { target: { files: [file] } });
    await screen.findByText("사진 교체");
    expect(screen.getByRole("button", { name: /게시하고 보내기/ })).toBeEnabled();
  });
});

describe("ManagerPage — 단계로 나누기 전/후 레이아웃", () => {
  it("직무가 없을 땐 입력·검색이 전체 폭을 쓴다(오른쪽을 빈 채로 예약하지 않는다)", async () => {
    const { container } = render(<ManagerPage />);
    await screen.findByText("오늘 직무 입력");
    expect(container.innerHTML).not.toContain("lg:grid-cols-[380px_1fr]");
  });

  it("단계로 나눈 뒤에는 왼쪽 380px + 오른쪽 검토 2단으로 바뀐다", async () => {
    const user = userEvent.setup();
    const { container } = render(<ManagerPage />);
    await typeAndDecompose(user);
    await screen.findByText(/검토 · 수정/);
    expect(container.innerHTML).toContain("lg:grid-cols-[380px_1fr]");
  });
});

describe("ManagerPage — 근로자 특성 메모 대상", () => {
  it("맞춤 대상 근로자를 고르면 worker_id를 함께 보내고, 고르지 않으면 보내지 않는다", async () => {
    const user = userEvent.setup();
    listWorkers.mockResolvedValue([
      { id: "w1", display_name: "김근로", access_code_hint: "34", access_code_length: 6 },
    ]);
    render(<ManagerPage />);
    const select = await screen.findByLabelText("맞춤 대상 근로자");

    await typeAndDecompose(user);
    await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
    expect(splitPreview.mock.calls[0][1]).toMatchObject({ worker_id: undefined });
    expect(createTask.mock.calls[0][1]).toMatchObject({ worker_id: undefined });

    await user.selectOptions(select, "w1");
    await user.type(screen.getByLabelText("근로자 특성"), "그림 선호");
    await user.click(screen.getByRole("button", { name: "단계로 나누기" }));
    await waitFor(() => expect(splitPreview).toHaveBeenCalledTimes(2));
    expect(splitPreview.mock.calls[1][1]).toMatchObject({ worker_id: "w1", worker_note: "그림 선호" });
    await user.click(await screen.findByRole("button", { name: "이대로 그림 고르기 ›" }));
    await waitFor(() => expect(createTask).toHaveBeenCalledTimes(2));
    expect(createTask.mock.calls[1][1]).toMatchObject({ worker_id: "w1", worker_note: "그림 선호" });
  });
});

// ---------- 2a-0: 서버 보내기 검사에 맞춘 최소 연결(tasks.md §2.3) ----------

describe("ManagerPage — 그림 확인을 서버에 적는다(2a-0)", () => {
  const autoHigh = {
    ...baseStep, symbol_url: "http://localhost:8000/api/aac/images/cafe/CAFE_012.webp",
    symbol_source: "LOCAL_AAC", needs_fallback: false, picture_state: "auto_high",
  };

  beforeEach(() => {
    listWorkers.mockResolvedValue(workers);
    publish.mockResolvedValue({ id: "task-1", title: "직무", status: "published", steps: [] });
    assign.mockResolvedValue([{ id: "a1", task_id: "task-1", worker_id: "w1", status: "assigned" }]);
  });

  it("[그림 확인]을 누르면 확인 API를 부르고, 서버가 확인함으로 돌려주면 보낼 수 있다", async () => {
    const user = userEvent.setup();
    createTask.mockResolvedValue({ id: "task-1", title: "직무", status: "draft", steps: [autoHigh] });
    render(<ManagerPage />);
    await typeAndDecompose(user);
    await screen.findByRole("checkbox", { name: /김근로/ });
    expect(screen.getByRole("button", { name: /게시하고 보내기/ })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "1단계 그림 확인" }));

    expect(reqMock).toHaveBeenCalledWith("/api/tasks/task-1/steps/s1/picture/confirm", { method: "POST" });
    expect(await screen.findByText("✓ 확인함")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /게시하고 보내기/ })).toBeEnabled();
  });

  it("확인 API가 실패하면 확인하지 않은 채로 두고 오류를 보인다", async () => {
    const user = userEvent.setup();
    createTask.mockResolvedValue({ id: "task-1", title: "직무", status: "draft", steps: [autoHigh] });
    reqMock.mockRejectedValue(new ApiError(422, "그림이 없는 단계는 확인할 수 없어요. 먼저 그림을 골라 주세요."));
    render(<ManagerPage />);
    await typeAndDecompose(user);
    await screen.findByRole("checkbox", { name: /김근로/ });

    await user.click(screen.getByRole("button", { name: "1단계 그림 확인" }));

    expect(await screen.findByText(/먼저 그림을 골라 주세요/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "1단계 그림 확인" })).toBeInTheDocument();
    expect(screen.queryByText("✓ 확인함")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /게시하고 보내기/ })).toBeDisabled();
  });

  it("서버가 이미 확인함(picture_state=confirmed)으로 준 자동 그림은 처음부터 확인함이다", async () => {
    const user = userEvent.setup();
    createTask.mockResolvedValue({
      id: "task-1", title: "직무", status: "draft",
      steps: [{ ...autoHigh, picture_state: "confirmed" }],
    });
    render(<ManagerPage />);
    await typeAndDecompose(user);
    await screen.findByRole("checkbox", { name: /김근로/ });

    expect(screen.queryByRole("button", { name: "1단계 그림 확인" })).not.toBeInTheDocument();
    expect(screen.getByText("✓ 확인함")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /게시하고 보내기/ })).toBeEnabled();
    expect(reqMock).not.toHaveBeenCalled();
  });

  it("고르기 상태(choose)의 그림도 확인해야 보낼 수 있다(서버 unconfirmed_auto와 같은 규칙)", async () => {
    const user = userEvent.setup();
    createTask.mockResolvedValue({
      id: "task-1", title: "직무", status: "draft",
      steps: [{ ...autoHigh, needs_fallback: true, picture_state: "choose" }],
    });
    render(<ManagerPage />);
    await typeAndDecompose(user);
    await screen.findByRole("checkbox", { name: /김근로/ });

    expect(screen.getByRole("button", { name: /게시하고 보내기/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "1단계 그림 확인" })).toBeInTheDocument();
  });
});

describe("ManagerPage — 보내기가 서버 검사(422)에 막히면 그 단계를 강조한다(2a-0)", () => {
  const confirmedAuto = {
    ...baseStep, symbol_url: "http://localhost:8000/api/aac/images/cafe/CAFE_012.webp",
    symbol_source: "LOCAL_AAC", needs_fallback: false, picture_state: "confirmed",
  };
  const detail = "2단계의 그림을 아직 확인하지 않았어요. 확인한 뒤 다시 보내 주세요.";

  beforeEach(() => {
    listWorkers.mockResolvedValue(workers);
    createTask.mockResolvedValue({
      id: "task-1", title: "직무", status: "draft",
      steps: [
        { ...confirmedAuto, id: "s1", order: 1 },
        { ...confirmedAuto, id: "s2", order: 2, sentence: "의자를 넣으세요" },
      ],
    });
    // 다른 창에서 2단계 그림을 바꿔 서버는 확인 전 상태다 — 이 화면은 아직 모른다.
    publish.mockRejectedValue(new ApiError(422, detail));
    reqMock.mockImplementation(async (path: string) => {
      if (path === "/api/tasks/task-1/send-check") {
        return {
          ok: false,
          blocking: [
            { code: "no_picture", done: 2, total: 2, step_ids: [] },
            { code: "unconfirmed_auto", done: 1, total: 2, step_ids: ["s2"] },
            { code: "unreviewed_split", done: 0, total: 0, step_ids: [] },
          ],
          warnings: [],
        };
      }
      if (path.endsWith("/steps/s2/picture/confirm")) {
        return { ...confirmedAuto, id: "s2", order: 2, sentence: "의자를 넣으세요" };
      }
      throw new Error(`목 없음: ${path}`);
    });
  });

  const stepItem = (id: string) => document.querySelector(`li[data-step-id="${id}"]`) as HTMLElement;

  it("서버 문장(detail)을 그대로 보이고, 점검표의 step_ids 단계만 강조한다", async () => {
    const user = userEvent.setup();
    render(<ManagerPage />);
    await typeAndDecompose(user);
    await screen.findByRole("checkbox", { name: /김근로/ });

    await user.click(screen.getByRole("button", { name: /게시하고 보내기/ }));

    expect((await screen.findAllByText(detail)).length).toBeGreaterThanOrEqual(1);
    await waitFor(() => expect(stepItem("s2")).toHaveAttribute("data-send-blocked", "true"));
    expect(stepItem("s1")).not.toHaveAttribute("data-send-blocked");
    expect(stepItem("s2").className).toContain("border-danger-700");
    expect(screen.getByText(/이 단계 때문에 보내지 못했어요\. 그림이 맞는지 확인해 주세요\./)).toBeInTheDocument();
    expect(reqMock).toHaveBeenCalledWith("/api/tasks/task-1/send-check", undefined);
    expect(assign).not.toHaveBeenCalled();
    // 막힌 단계는 다시 확인하게 하고, 그동안 보내기는 막힌다.
    expect(screen.getByRole("button", { name: /게시하고 보내기/ })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "1단계 그림 확인" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "2단계 그림 확인" }));

    expect(reqMock).toHaveBeenCalledWith("/api/tasks/task-1/steps/s2/picture/confirm", { method: "POST" });
    await waitFor(() => expect(stepItem("s2")).not.toHaveAttribute("data-send-blocked"));
    expect(screen.getByRole("button", { name: /게시하고 보내기/ })).toBeEnabled();
  });

  it("422가 아닌 실패(네트워크 등)는 점검표를 읽지 않고 강조도 하지 않는다", async () => {
    const user = userEvent.setup();
    publish.mockRejectedValue(new Error("인터넷 연결을 확인해 주세요."));
    render(<ManagerPage />);
    await typeAndDecompose(user);
    await screen.findByRole("checkbox", { name: /김근로/ });

    await user.click(screen.getByRole("button", { name: /게시하고 보내기/ }));

    expect((await screen.findAllByText("인터넷 연결을 확인해 주세요.")).length).toBeGreaterThanOrEqual(1);
    expect(reqMock).not.toHaveBeenCalled();
    expect(document.querySelector("[data-send-blocked]")).toBeNull();
  });
});
