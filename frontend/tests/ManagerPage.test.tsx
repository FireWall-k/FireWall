import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ManagerPage from "../src/pages/ManagerPage";

const createTask = vi.fn();
const uploadStepPhoto = vi.fn();
const removeStepPhoto = vi.fn();
const listWorkers = vi.fn();
const createWorker = vi.fn();
const publish = vi.fn();
const assign = vi.fn();
// 자동 채택 못 한(needs_fallback=true) 단계는 마운트 시 후보를 조회한다 — 목이 없으면 깨진다.
const stepSymbolCandidates = vi.fn().mockResolvedValue({ step_id: "s1", reason: "no_candidate", candidates: [] });

vi.mock("../src/api", () => ({
  api: {
    createTask: (raw: string, ctx: unknown) => createTask(raw, ctx),
    uploadStepPhoto: (t: string, s: string, f: File) => uploadStepPhoto(t, s, f),
    removeStepPhoto: (t: string, s: string) => removeStepPhoto(t, s),
    stepSymbolCandidates: (t: string, s: string) => stepSymbolCandidates(t, s),
    listWorkers: () => listWorkers(),
    createWorker: (name: string, code?: string) => createWorker(name, code),
    publish: (id: string) => publish(id),
    assign: (id: string, workerIds: string[]) => assign(id, workerIds),
    updateStep: vi.fn(),
  },
}));

// 단계로 나누기 버튼은 직무 내용이 비어 있으면 비활성 상태다 — 모든 테스트가 이걸 거친다.
async function typeAndDecompose(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("직무 내용"), "상자를 옮겨주세요.");
  await user.click(screen.getByRole("button", { name: "단계로 나누기" }));
}

const baseStep = {
  id: "s1", order: 1, sentence: "상자를 옮기세요", action_type: "move",
  symbol_url: null as string | null, symbol_source: "fallback", needs_fallback: true,
  tts_audio_url: null as string | null,
};

beforeEach(() => {
  createTask.mockReset();
  uploadStepPhoto.mockReset();
  removeStepPhoto.mockReset();
  listWorkers.mockReset();
  publish.mockReset();
  assign.mockReset();
  createTask.mockResolvedValue({ id: "task-1", title: "직무", status: "draft", steps: [baseStep] });
  listWorkers.mockResolvedValue([]);
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

  it("목록에는 전체 접속 코드가 보인다", async () => {
    const user = userEvent.setup();
    listWorkers.mockResolvedValue([
      { id: "w1", display_name: "김근로", access_code: "1234", access_code_hint: "34", access_code_length: 4 },
    ]);
    render(<ManagerPage />);
    await typeAndDecompose(user);
    expect(await screen.findByRole("checkbox", { name: /김근로 \(코드 1234\)/ })).toBeInTheDocument();
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
    publish.mockResolvedValue({ id: "task-1", title: "직무", status: "published", steps: [baseStep] });
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
    expect(createTask.mock.calls[0][1]).toMatchObject({ worker_id: undefined });

    await user.selectOptions(select, "w1");
    await user.type(screen.getByLabelText("근로자 특성"), "그림 선호");
    await user.click(screen.getByRole("button", { name: "단계로 나누기" }));
    await waitFor(() => expect(createTask).toHaveBeenCalledTimes(2));
    expect(createTask.mock.calls[1][1]).toMatchObject({ worker_id: "w1", worker_note: "그림 선호" });
  });
});
