import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ManagerPage from "../src/pages/ManagerPage";

// 입력 화면에서 나누기를 끝낸다(한 줄 = 한 동작 = 그림 1장): [단계로 나누기] → 나눈 줄을 그 자리에서
// 합치기·더 나누기·고치기·지우기 → [이대로 그림 고르기]를 눌러야 초안을 만든다.
// 편집기에서는 '동작이 2개예요' 알림 없이, 문장을 고쳐 저장하며 나눴으면 [되돌리기]를 띄운다.

const createTask = vi.fn();
const splitPreview = vi.fn();
const rewriteStep = vi.fn();
const mergeSteps = vi.fn();
const addStep = vi.fn();
const deleteStep = vi.fn();

vi.mock("../src/api", () => ({
  api: {
    createTask: (raw: string, ctx: unknown) => createTask(raw, ctx),
    splitPreview: (raw: string, ctx: unknown) => splitPreview(raw, ctx),
    rewriteStep: (t: string, s: string, sentence: string) => rewriteStep(t, s, sentence),
    mergeSteps: (t: string, ids: string[], sentence: string, actionType?: string) =>
      mergeSteps(t, ids, sentence, actionType),
    addStep: (t: string, sentence: string) => addStep(t, sentence),
    deleteStep: (t: string, s: string) => deleteStep(t, s),
    stepSymbolCandidates: (_t: string, s: string) =>
      Promise.resolve({ step_id: s, reason: "no_candidate", candidates: [] }),
    listWorkers: () => Promise.resolve([]),
    updateStep: vi.fn(),
  },
}));

const SOURCE = "컵 씻어서 건조대에 올려 놔";
const INPUT = "출근하면 앞치마 입고 손 씻고, 컵 씻어서 건조대에 올려 놔.";

const PREVIEW = {
  task_title: "출근 준비",
  job: "cafe",
  steps: [
    { order: 1, sentence: "앞치마를 입어요.", action_type: "wear", symbol_query: ["앞치마"],
      split_group: null, split_check: false, source_text: null },
    { order: 2, sentence: "손을 씻어요.", action_type: "clean", symbol_query: ["손"],
      split_group: null, split_check: false, source_text: null },
    { order: 3, sentence: "컵을 씻어요.", action_type: "clean", symbol_query: ["컵"],
      split_group: 1, split_check: true, source_text: SOURCE },
    { order: 4, sentence: "컵을 건조대에 올려요.", action_type: "move", symbol_query: ["건조대"],
      split_group: 1, split_check: true, source_text: SOURCE },
  ],
};

function taskStep(id: string, order: number, sentence: string) {
  return {
    id, order, sentence, action_type: "other", symbol_url: null, symbol_source: "fallback",
    needs_fallback: true, tts_audio_url: null,
  };
}

beforeEach(() => {
  createTask.mockReset();
  splitPreview.mockReset();
  rewriteStep.mockReset();
  mergeSteps.mockReset();
  addStep.mockReset();
  deleteStep.mockReset();
  splitPreview.mockResolvedValue(PREVIEW);
  createTask.mockImplementation((_raw: string, ctx: { steps: { sentence: string }[] }) =>
    Promise.resolve({
      id: "task-1", title: "출근 준비", status: "draft",
      steps: ctx.steps.map((s, i) => taskStep(`s${i + 1}`, i + 1, s.sentence)),
    }));
});

async function split(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("직무 내용"), INPUT);
  await user.click(screen.getByRole("button", { name: "단계로 나누기" }));
  await screen.findByRole("heading", { name: /이렇게 나눴어요/ });
}

const rowTexts = () =>
  screen.getAllByLabelText(/^\d+단계 문장$/).map((el) => (el as HTMLInputElement).value);

describe("입력 화면 — 쓰는 순간 나누기", () => {
  it("나누는 동안 '문장을 나누고 있어요'를 보이고, 직무는 아직 만들지 않는다", async () => {
    const user = userEvent.setup();
    let resolve!: (v: typeof PREVIEW) => void;
    splitPreview.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<ManagerPage />);
    await user.type(screen.getByLabelText("직무 내용"), INPUT);
    await user.click(screen.getByRole("button", { name: "단계로 나누기" }));
    expect(await screen.findByText(/문장을 나누고 있어요/)).toBeInTheDocument();
    resolve(PREVIEW);
    await screen.findByRole("heading", { name: /이렇게 나눴어요/ });
    expect(rowTexts()).toEqual(["앞치마를 입어요.", "손을 씻어요.", "컵을 씻어요.", "컵을 건조대에 올려요."]);
    expect(createTask).not.toHaveBeenCalled();
    // 편집기는 아직 없다
    expect(screen.queryByText(/검토 · 수정/)).not.toBeInTheDocument();
  });

  it("애매한 줄만 노랗게 칠하고 원래 문장과 [합치기]를 보여 준다", async () => {
    const user = userEvent.setup();
    render(<ManagerPage />);
    await split(user);
    expect(screen.getByTestId("split-row-1")).toHaveAttribute("data-check", "false");
    expect(screen.getByTestId("split-row-3")).toHaveAttribute("data-check", "true");
    expect(screen.getByTestId("split-row-4")).toHaveAttribute("data-check", "true");
    expect(within(screen.getByTestId("split-row-3")).getByText(new RegExp(SOURCE))).toBeInTheDocument();
    expect(screen.getByText(/노란 줄 2개는 나눈 곳이 애매해요/)).toBeInTheDocument();
    // 확실한 줄에는 합치기가 없고, 모든 줄에 더 나누기가 있다
    expect(within(screen.getByTestId("split-row-1")).queryByRole("button", { name: /합치기/ })).toBeNull();
    expect(screen.getAllByRole("button", { name: /단계 더 나누기$/ })).toHaveLength(4);
  });

  it("나누지 못한 노란 줄(묶음 없음)은 [더 나누기]로 나누라고 안내하고 [합치기]는 없다", async () => {
    // GPT가 안 될 때 규칙이 동작 여럿을 한 줄로 남긴 경우(split_group=null, split_check=true).
    const user = userEvent.setup();
    splitPreview.mockResolvedValue({
      ...PREVIEW,
      steps: [{ order: 1, sentence: "카드를 받아서 결제하고 영수증을 손님에게 드려요", action_type: "other",
        symbol_query: [], split_group: null, split_check: true, source_text: null }],
    });
    render(<ManagerPage />);
    await split(user);
    const row = screen.getByTestId("split-row-1");
    expect(row).toHaveAttribute("data-check", "true");
    expect(within(row).getByText(/동작이 여러 개일 수 있어요/)).toBeInTheDocument();
    expect(within(row).queryByText(/나눈 곳 확인/)).toBeNull();
    expect(within(row).queryByRole("button", { name: /합치기/ })).toBeNull();
  });

  it("문장 칸에서 Enter는 줄바꿈을 넣지 않는다(한 줄 = 한 동작)", async () => {
    const user = userEvent.setup();
    render(<ManagerPage />);
    await split(user);
    const field = screen.getByLabelText("1단계 문장");
    await user.click(field);
    await user.keyboard("{End}{Enter}");
    expect((field as HTMLTextAreaElement).value).toBe("앞치마를 입어요.");
  });

  it("[합치기]를 누르면 두 줄이 한 줄로 합쳐지고 초점이 그 줄로 간다", async () => {
    const user = userEvent.setup();
    render(<ManagerPage />);
    await split(user);
    await user.click(screen.getByRole("button", { name: "3단계와 4단계 합치기" }));
    // 한 원래 문장에서 나온 두 줄을 모두 합쳤으니 사업주가 쓴 원래 문장으로 되돌린다
    expect(rowTexts()).toEqual(["앞치마를 입어요.", "손을 씻어요.", SOURCE]);
    expect(screen.getByTestId("split-row-3")).toHaveAttribute("data-check", "false");
    expect(screen.getByLabelText("3단계 문장")).toHaveFocus();
    expect(screen.queryByText(/노란 줄/)).not.toBeInTheDocument();
  });

  it("[더 나누기]는 커서를 둔 곳에서 두 줄로 자른다", async () => {
    const user = userEvent.setup();
    splitPreview.mockResolvedValue({
      ...PREVIEW,
      steps: [{ ...PREVIEW.steps[0], sentence: "송장을 붙이고 바코드를 찍어요" }],
    });
    render(<ManagerPage />);
    await split(user);
    const input = screen.getByLabelText("1단계 문장") as HTMLInputElement;
    await user.click(input);
    input.setSelectionRange("송장을 붙이고".length, "송장을 붙이고".length);
    await user.click(screen.getByRole("button", { name: "1단계 더 나누기" }));
    expect(rowTexts()).toEqual(["송장을 붙이고", "바코드를 찍어요"]);
    expect(screen.getByLabelText("2단계 문장")).toHaveFocus();
  });

  it("[더 나누기]를 커서 없이 누르면 빈 줄이 생기고, 비운 채 확인하면 알려 준다", async () => {
    const user = userEvent.setup();
    render(<ManagerPage />);
    await split(user);
    await user.click(screen.getByRole("button", { name: "2단계 더 나누기" }));
    expect(rowTexts()).toEqual(["앞치마를 입어요.", "손을 씻어요.", "", "컵을 씻어요.", "컵을 건조대에 올려요."]);
    expect(screen.getByLabelText("3단계 문장")).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "이대로 그림 고르기 ›" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("3단계가 비어 있어요");
    expect(createTask).not.toHaveBeenCalled();
    // 빈 줄에 적으면 보낼 수 있다
    await user.type(screen.getByLabelText("3단계 문장"), "손을 말려요.");
    await user.click(screen.getByRole("button", { name: "이대로 그림 고르기 ›" }));
    await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
  });

  it("고치고·지운 뒤 [이대로 그림 고르기]를 누르면 확인한 줄로 초안을 만들고 편집기를 연다", async () => {
    const user = userEvent.setup();
    render(<ManagerPage />);
    await split(user);
    const second = screen.getByLabelText("2단계 문장");
    await user.clear(second);
    await user.type(second, "손을 비누로 씻어요.");
    await user.click(screen.getByRole("button", { name: "1단계 지우기" }));
    expect(rowTexts()).toEqual(["손을 비누로 씻어요.", "컵을 씻어요.", "컵을 건조대에 올려요."]);

    await user.click(screen.getByRole("button", { name: "이대로 그림 고르기 ›" }));
    await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
    const [raw, ctx] = createTask.mock.calls[0];
    expect(raw).toBe(INPUT);
    expect(ctx).toMatchObject({
      title: "출근 준비", job: "cafe",
      steps: [
        { sentence: "손을 비누로 씻어요." },
        { sentence: "컵을 씻어요.", action_type: "clean", symbol_query: ["컵"] },
        { sentence: "컵을 건조대에 올려요.", action_type: "move", symbol_query: ["건조대"] },
      ],
    });
    // 고친 줄은 AI 검색어를 보내지 않는다(서버가 문장에서 다시 뽑는다)
    expect(ctx.steps[0]).toEqual({ sentence: "손을 비누로 씻어요." });

    const heading = await screen.findByRole("heading", { name: /검토 · 수정/ });
    await waitFor(() => expect(heading).toHaveFocus());
    expect(screen.queryByRole("heading", { name: /이렇게 나눴어요/ })).not.toBeInTheDocument();
    // 편집기에는 '동작이 2개예요' 같은 나누기 알림이 없다
    expect(screen.queryByText(/동작이 \d개/)).not.toBeInTheDocument();
  });

  it("나누기에 실패하면 한국어 오류를 보여 준다", async () => {
    const user = userEvent.setup();
    splitPreview.mockRejectedValue(new Error("직무를 단계로 나누지 못했습니다. 잠시 뒤 다시 시도해 주세요."));
    render(<ManagerPage />);
    await user.type(screen.getByLabelText("직무 내용"), INPUT);
    await user.click(screen.getByRole("button", { name: "단계로 나누기" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("직무를 단계로 나누지 못했습니다");
  });

  it("나눈 뒤 직무 내용을 고치면 다시 나누라고 알려 준다", async () => {
    const user = userEvent.setup();
    render(<ManagerPage />);
    await split(user);
    await user.type(screen.getByLabelText("직무 내용"), " 그리고 바닥을 닦아.");
    expect(screen.getByText(/새로 나누려면 \[단계로 나누기\]를 다시/)).toBeInTheDocument();
  });

  it("키보드만으로 합치기·확인까지 할 수 있다", async () => {
    const user = userEvent.setup();
    render(<ManagerPage />);
    await split(user);
    const merge = screen.getByRole("button", { name: "3단계와 4단계 합치기" });
    merge.focus();
    await user.keyboard("{Enter}");
    expect(rowTexts()).toHaveLength(3);
    screen.getByRole("button", { name: "이대로 그림 고르기 ›" }).focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
  });
});

describe("편집기 — 저장하는 순간 나누기와 되돌리기", () => {
  async function openEditor(user: ReturnType<typeof userEvent.setup>) {
    splitPreview.mockResolvedValue({ ...PREVIEW, steps: PREVIEW.steps.slice(0, 2) });
    render(<ManagerPage />);
    await split(user);
    await user.click(screen.getByRole("button", { name: "이대로 그림 고르기 ›" }));
    await screen.findByRole("heading", { name: /검토 · 수정/ });
  }

  it("고친 문장에 동작이 둘이면 두 단계로 나누고 [되돌리기]로 한 단계로 돌린다", async () => {
    const user = userEvent.setup();
    await openEditor(user);
    const typed = "손 씻고 수건으로 닦아요";
    rewriteStep.mockResolvedValue({
      task: { id: "task-1", title: "출근 준비", status: "draft", steps: [
        taskStep("s1", 1, "앞치마를 입어요."), taskStep("n1", 2, "손을 씻어요."), taskStep("n2", 3, "손을 수건으로 닦아요."),
      ] },
      split_step_ids: ["n1", "n2"],
      sentence: typed,
    });
    mergeSteps.mockResolvedValue({ id: "task-1", title: "출근 준비", status: "draft", steps: [
      taskStep("s1", 1, "앞치마를 입어요."), taskStep("m1", 2, typed),
    ] });

    const input = screen.getByLabelText("2단계 문장");
    await user.clear(input);
    await user.type(input, typed);
    await user.tab();
    await waitFor(() => expect(rewriteStep).toHaveBeenCalledWith("task-1", "s2", typed));
    expect(await screen.findByText("동작이 둘이라 두 단계로 나눴어요.")).toBeInTheDocument();
    expect((screen.getByLabelText("3단계 문장") as HTMLInputElement).value).toBe("손을 수건으로 닦아요.");
    // 경고가 아니라 알림 + 되돌리기다
    expect(screen.queryByText(/동작이 \d개/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "되돌리기" }));
    // 나누기 전 단계의 동작 종류를 함께 보내 원래 단계를 되살린다
    await waitFor(() => expect(mergeSteps).toHaveBeenCalledWith("task-1", ["n1", "n2"], typed, "other"));
    expect((await screen.findByLabelText("2단계 문장") as HTMLInputElement).value).toBe(typed);
    expect(screen.queryByLabelText("3단계 문장")).not.toBeInTheDocument();
    expect(screen.queryByText("동작이 둘이라 두 단계로 나눴어요.")).not.toBeInTheDocument();
  });

  it("보낸 직무에서 문장을 고쳐 나뉘어도 [되돌리기]가 뜬다(2a-0 — 서버가 보낸 직무도 나누고 합친다)", async () => {
    const user = userEvent.setup();
    await openEditor(user);
    const typed = "쓰레기통을 비우고 봉투를 갈아요";
    rewriteStep.mockResolvedValue({
      task: { id: "task-1", title: "출근 준비", status: "published", steps: [
        taskStep("s1", 1, "앞치마를 입어요."), taskStep("n1", 2, "쓰레기통을 비워요."), taskStep("n2", 3, "봉투를 갈아요."),
      ] },
      split_step_ids: ["n1", "n2"],
      sentence: typed,
    });
    mergeSteps.mockResolvedValue({ id: "task-1", title: "출근 준비", status: "published", steps: [
      taskStep("s1", 1, "앞치마를 입어요."), taskStep("m1", 2, typed),
    ] });

    const input = screen.getByLabelText("2단계 문장");
    await user.clear(input);
    await user.type(input, typed);
    await user.tab();
    await user.click(await screen.findByRole("button", { name: "되돌리기" }));
    await waitFor(() => expect(mergeSteps).toHaveBeenCalledWith("task-1", ["n1", "n2"], typed, "other"));
    expect((await screen.findByLabelText("2단계 문장") as HTMLInputElement).value).toBe(typed);
  });

  it("한 동작이면 그대로 저장하고 되돌리기를 띄우지 않는다", async () => {
    const user = userEvent.setup();
    await openEditor(user);
    rewriteStep.mockResolvedValue({
      task: { id: "task-1", title: "출근 준비", status: "draft", steps: [
        taskStep("s1", 1, "앞치마를 입어요."), taskStep("s2", 2, "손을 깨끗이 씻어요."),
      ] },
      split_step_ids: [],
      sentence: "손을 깨끗이 씻어요.",
    });
    const input = screen.getByLabelText("2단계 문장");
    await user.clear(input);
    await user.type(input, "손을 깨끗이 씻어요.");
    await user.tab();
    await waitFor(() => expect(rewriteStep).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/두 단계로 나눴어요/)).not.toBeInTheDocument();
  });

  it("저장에 실패하면 한국어 오류를 보여 준다", async () => {
    const user = userEvent.setup();
    await openEditor(user);
    rewriteStep.mockRejectedValue(new Error("문장을 저장하지 못했어요."));
    const input = screen.getByLabelText("2단계 문장");
    await user.type(input, " 꼼꼼히");
    await user.tab();
    expect(await screen.findByRole("alert")).toHaveTextContent("문장을 저장하지 못했어요");
  });
});

describe("1차 검증 반영 — 입력 화면", () => {
  it("[이대로 그림 고르기]가 실패하면 버튼 바로 아래에 이유를 보여 준다", async () => {
    const user = userEvent.setup();
    createTask.mockRejectedValue(new Error("직무를 만들지 못했어요."));
    render(<ManagerPage />);
    await split(user);
    await user.click(screen.getByRole("button", { name: "이대로 그림 고르기 ›" }));
    const list = screen.getByRole("heading", { name: /이렇게 나눴어요/ }).closest("section") as HTMLElement;
    expect(await within(list).findByRole("alert")).toHaveTextContent("직무를 만들지 못했어요.");
    // 목록과 고친 내용은 그대로다
    expect(rowTexts()).toHaveLength(4);
  });

  it("원문도 목록도 그대로면 [단계로 나누기]를 다시 누를 수 없고, 고친 줄이 있으면 먼저 묻는다", async () => {
    const user = userEvent.setup();
    render(<ManagerPage />);
    await split(user);
    const again = screen.getByRole("button", { name: "단계로 나누기" });
    expect(again).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "1단계 지우기" }));
    expect(again).toBeEnabled();
    const ask = vi.spyOn(window, "confirm").mockReturnValue(false);
    await user.click(again);
    expect(ask).toHaveBeenCalledWith(expect.stringContaining("고친 줄이 있어요"));
    expect(splitPreview).toHaveBeenCalledTimes(1);
    expect(rowTexts()).toHaveLength(3);
    ask.mockReturnValue(true);
    await user.click(again);
    await waitFor(() => expect(splitPreview).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(rowTexts()).toHaveLength(4));
    ask.mockRestore();
  });
});

describe("1차 검증 반영 — 편집기", () => {
  async function openEditor(user: ReturnType<typeof userEvent.setup>) {
    splitPreview.mockResolvedValue({ ...PREVIEW, steps: PREVIEW.steps.slice(0, 2) });
    render(<ManagerPage />);
    await split(user);
    await user.click(screen.getByRole("button", { name: "이대로 그림 고르기 ›" }));
    await screen.findByRole("heading", { name: /검토 · 수정/ });
  }

  it("[단계 추가]로 넣은 문장에 동작이 둘이면 나눠 넣고 [되돌리기]를 띄운다", async () => {
    const user = userEvent.setup();
    await openEditor(user);
    const typed = "컵을 씻고 건조대에 올려요";
    addStep.mockResolvedValue({
      id: "task-1", title: "출근 준비", status: "draft",
      steps: [taskStep("s1", 1, "앞치마를 입어요."), taskStep("s2", 2, "손을 씻어요."),
              taskStep("n1", 3, "컵을 씻어요."), taskStep("n2", 4, "컵을 건조대에 올려요.")],
      split_step_ids: ["n1", "n2"], sentence: typed,
    });
    mergeSteps.mockResolvedValue({ id: "task-1", title: "출근 준비", status: "draft", steps: [
      taskStep("s1", 1, "앞치마를 입어요."), taskStep("s2", 2, "손을 씻어요."), taskStep("m1", 3, typed),
    ] });
    await user.type(screen.getByLabelText("새 단계 문장"), typed);
    await user.click(screen.getByRole("button", { name: /단계 추가/ }));
    expect(await screen.findByText("동작이 둘이라 두 단계로 나눴어요.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "되돌리기" }));
    await waitFor(() => expect(mergeSteps).toHaveBeenCalledWith("task-1", ["n1", "n2"], typed, undefined));
  });

  it("나눈 단계 하나를 지우면 [되돌리기]를 내린다", async () => {
    const user = userEvent.setup();
    await openEditor(user);
    rewriteStep.mockResolvedValue({
      task: { id: "task-1", title: "출근 준비", status: "draft", steps: [
        taskStep("s1", 1, "앞치마를 입어요."), taskStep("n1", 2, "손을 씻어요."), taskStep("n2", 3, "손을 닦아요."),
      ] },
      split_step_ids: ["n1", "n2"], sentence: "손 씻고 닦아요",
    });
    deleteStep.mockResolvedValue({ id: "task-1", title: "출근 준비", status: "draft", steps: [
      taskStep("s1", 1, "앞치마를 입어요."), taskStep("n1", 2, "손을 씻어요."),
    ] });
    const input = screen.getByLabelText("2단계 문장");
    await user.clear(input);
    await user.type(input, "손 씻고 닦아요");
    await user.tab();
    expect(await screen.findByText("동작이 둘이라 두 단계로 나눴어요.")).toBeInTheDocument();
    const ok = vi.spyOn(window, "confirm").mockReturnValue(true);
    await user.click(screen.getByRole("button", { name: "3단계 삭제" }));
    await waitFor(() => expect(screen.queryByText("동작이 둘이라 두 단계로 나눴어요.")).not.toBeInTheDocument());
    ok.mockRestore();
  });

  it("문장을 저장(나누기 확인)하는 동안 '저장하는 중'을 보이고 다른 문장 칸은 읽기 전용이다", async () => {
    const user = userEvent.setup();
    await openEditor(user);
    let resolve!: (v: unknown) => void;
    rewriteStep.mockReturnValue(new Promise((r) => { resolve = r; }));
    const input = screen.getByLabelText("2단계 문장");
    await user.type(input, " 꼼꼼히");
    await user.tab();
    expect(await screen.findByText(/저장하는 중/)).toBeInTheDocument();
    expect(screen.getByLabelText("1단계 문장")).toHaveAttribute("readonly");
    resolve({
      task: { id: "task-1", title: "출근 준비", status: "draft", steps: [
        taskStep("s1", 1, "앞치마를 입어요."), taskStep("s2", 2, "손을 씻어요. 꼼꼼히"),
      ] },
      split_step_ids: [], sentence: "손을 씻어요. 꼼꼼히",
    });
    await waitFor(() => expect(screen.queryByText(/저장하는 중/)).not.toBeInTheDocument());
    expect(screen.getByLabelText("1단계 문장")).not.toHaveAttribute("readonly");
  });
});

describe("2차 검증 반영", () => {
  async function openEditor(user: ReturnType<typeof userEvent.setup>) {
    splitPreview.mockResolvedValue({ ...PREVIEW, steps: PREVIEW.steps.slice(0, 2) });
    render(<ManagerPage />);
    await split(user);
    await user.click(screen.getByRole("button", { name: "이대로 그림 고르기 ›" }));
    await screen.findByRole("heading", { name: /검토 · 수정/ });
  }

  it("[이대로 그림 고르기] 뒤 초점이 편집기 제목으로 간다", async () => {
    const user = userEvent.setup();
    await openEditor(user);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("heading", { name: /검토 · 수정/ })));
  });

  it("[되돌리기] 뒤 초점이 합친 단계의 문장 칸으로 간다", async () => {
    const user = userEvent.setup();
    await openEditor(user);
    const typed = "손 씻고 수건으로 닦아요";
    rewriteStep.mockResolvedValue({
      task: { id: "task-1", title: "출근 준비", status: "draft", steps: [
        taskStep("s1", 1, "앞치마를 입어요."), taskStep("n1", 2, "손을 씻어요."), taskStep("n2", 3, "손을 수건으로 닦아요."),
      ] },
      split_step_ids: ["n1", "n2"], sentence: typed,
    });
    mergeSteps.mockResolvedValue({ id: "task-1", title: "출근 준비", status: "draft", steps: [
      taskStep("s1", 1, "앞치마를 입어요."), taskStep("m1", 2, typed),
    ] });
    const input = screen.getByLabelText("2단계 문장");
    await user.clear(input);
    await user.type(input, typed);
    await user.tab();
    await user.click(await screen.findByRole("button", { name: "되돌리기" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("2단계 문장")));
  });

  it("앞뒤 빈칸만 다른 문장은 칸을 다시 지나가도 또 저장하지 않는다", async () => {
    const user = userEvent.setup();
    await openEditor(user);
    rewriteStep.mockResolvedValue({
      task: { id: "task-1", title: "출근 준비", status: "draft", steps: [
        taskStep("s1", 1, "앞치마를 입어요."), taskStep("s2", 2, "우유를 부어요"),
      ] },
      split_step_ids: [], sentence: "우유를 부어요",
    });
    const input = screen.getByLabelText("2단계 문장");
    await user.clear(input);
    await user.type(input, "  우유를 부어요  ");
    await user.tab();
    await waitFor(() => expect(rewriteStep).toHaveBeenCalledWith("task-1", "s2", "우유를 부어요"));
    await waitFor(() => expect((screen.getByLabelText("2단계 문장") as HTMLTextAreaElement).value).toBe("우유를 부어요"));
    await user.click(screen.getByLabelText("2단계 문장"));
    await user.tab();
    expect(rewriteStep).toHaveBeenCalledTimes(1);
  });

  it("목록을 만든 뒤 직무 내용을 고쳐도 [이대로 그림 고르기]는 목록(과 목록을 만든 글)으로 만든다고 알리고 그렇게 한다", async () => {
    const user = userEvent.setup();
    render(<ManagerPage />);
    await split(user);
    await user.type(screen.getByLabelText("직무 내용"), " 그리고 바닥을 닦아.");
    expect(screen.getByText(/아래 목록대로/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "이대로 그림 고르기 ›" }));
    await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
    expect(createTask.mock.calls[0][0]).toBe(INPUT);
    expect(createTask.mock.calls[0][1].steps).toHaveLength(4);
  });

  it("30줄을 넘거나 한 줄이 너무 길면 확인 전에 막는다", async () => {
    const user = userEvent.setup();
    splitPreview.mockResolvedValue({
      ...PREVIEW,
      steps: Array.from({ length: 30 }, (_, i) => ({
        order: i + 1, sentence: `컵 ${i + 1}번을 씻어요.`, action_type: "clean", symbol_query: [],
        split_group: null, split_check: false, source_text: null,
      })),
    });
    render(<ManagerPage />);
    await split(user);
    expect(screen.getByRole("button", { name: /한 줄 추가/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "1단계 더 나누기" })).toBeDisabled();
    expect(screen.getByLabelText("1단계 문장")).toHaveAttribute("maxlength", "500");
  });
});
