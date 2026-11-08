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

vi.mock("../src/api", () => ({
  api: {
    createTask: (raw: string, ctx: unknown) => createTask(raw, ctx),
    splitPreview: (raw: string, ctx: unknown) => splitPreview(raw, ctx),
    rewriteStep: (t: string, s: string, sentence: string) => rewriteStep(t, s, sentence),
    mergeSteps: (t: string, ids: string[], sentence: string) => mergeSteps(t, ids, sentence),
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

  it("[합치기]를 누르면 두 줄이 한 줄로 합쳐지고 초점이 그 줄로 간다", async () => {
    const user = userEvent.setup();
    render(<ManagerPage />);
    await split(user);
    await user.click(screen.getByRole("button", { name: "3단계와 4단계 합치기" }));
    expect(rowTexts()).toEqual(["앞치마를 입어요.", "손을 씻어요.", "컵을 씻어요. 컵을 건조대에 올려요."]);
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
    await waitFor(() => expect(mergeSteps).toHaveBeenCalledWith("task-1", ["n1", "n2"], typed));
    expect((await screen.findByLabelText("2단계 문장") as HTMLInputElement).value).toBe(typed);
    expect(screen.queryByLabelText("3단계 문장")).not.toBeInTheDocument();
    expect(screen.queryByText("동작이 둘이라 두 단계로 나눴어요.")).not.toBeInTheDocument();
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
