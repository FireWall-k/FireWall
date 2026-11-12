import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { ToastProvider } from "../../src/components/ui";
import { NEW_TASK_DRAFT_KEY } from "../../src/manager/tasks/new/draft";
import { step, task } from "./editorFixtures";
import { editorMock as m, renderAt, resetMocks } from "./editorHarness";

// 새 직무(/m/tasks/new, 명세 5.4, tasks §4.3·4.4). 옛 ManagerPage·InputSplit 시험을 옮겨 왔다:
// 쓰는 순간 나누기(합치기·더 나누기·고치기·지우기) → [이대로 그림 고르기] → 초안 → 같은 Route의 편집기.
// 새로: 720 한 칸·보이는 라벨·글자 수·[예시 넣기]·'더 알려 주기'·개인정보 안내, 새로고침 뒤 원문 남음, 떠날 때 Dialog,
// 만드는 동안 편집기 모양 스켈레톤(퍼센트 없음), 나눈 방법·원문 조각·조심 제안을 함께 보냄.
vi.mock("../../src/manager/api/editor", async () => ({ editorApi: (await import("./editorHarness")).editorMock }));
vi.mock("../../src/manager/api/send", async () => ({ sendApi: (await import("./editorHarness")).sendMock }));
vi.mock("../../src/manager/api/tasks", async () => (await import("./editorHarness")).tasksMock);

vi.setConfig({ testTimeout: 15_000 });

const SOURCE = "컵 씻어서 건조대에 올려 놔";
const INPUT = "출근하면 앞치마 입고 손 씻고, 컵 씻어서 건조대에 올려 놔.";
const PREVIEW = {
  task_title: "출근 준비",
  job: "cafe",
  steps: [
    { order: 1, sentence: "앞치마를 입어요.", action_type: "wear", symbol_query: ["앞치마"], split_group: null, split_check: false, source_text: null },
    { order: 2, sentence: "손을 씻어요.", action_type: "clean", symbol_query: ["손"], split_group: null, split_check: false, source_text: null },
    { order: 3, sentence: "컵을 씻어요.", action_type: "clean", symbol_query: ["컵"], split_group: 1, split_check: true, source_text: SOURCE },
    { order: 4, sentence: "컵을 칼로 긁어요.", action_type: "move", symbol_query: ["칼"], split_group: 1, split_check: true, source_text: SOURCE, safety_flag: true },
  ],
};

beforeEach(() => {
  resetMocks();
  localStorage.clear();
  m.splitPreview.mockResolvedValue(PREVIEW);
  m.createTask.mockImplementation(async (_raw: string, opts: { steps: { sentence: string }[] }) =>
    task(opts.steps.map((s, i) => step(`s${i + 1}`, i + 1, s.sentence, "auto_high")), { id: "task-9", title: "출근 준비" }),
  );
});

async function openNew(path = "/m/tasks/new") {
  const user = userEvent.setup();
  await renderAt(path);
  await screen.findByRole("heading", { level: 1, name: "새 직무" });
  return user;
}

const input = () => screen.getByLabelText("어떤 일을 시킬까요?");
const rowTexts = () => screen.getAllByLabelText(/^\d+단계 문장$/).map((el) => (el as HTMLTextAreaElement).value);

async function split(user: ReturnType<typeof userEvent.setup>) {
  await user.type(input(), INPUT);
  await user.click(screen.getByRole("button", { name: "단계로 나누기" }));
  await screen.findByRole("heading", { name: /이렇게 나눴어요/ });
}

describe("입력 칸", () => {
  it("보이는 라벨 '어떤 일을 시킬까요?', 도움말, 8줄, 글자 수, [예시 넣기], 개인정보 안내, 'AI' 글자 없음", async () => {
    const user = await openNew();
    const box = input();
    expect(box).toHaveAttribute("rows", "8");
    expect(box).toHaveAccessibleDescription(/평소 말하듯 적어 주세요. 단계는 잡카드가 나눠요./);
    expect(screen.getByText("0/2000자")).toBeInTheDocument();
    expect(screen.getByText("근로자 이름은 A로 바꿔서 처리해요.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "예시 넣기" }));
    expect((box as HTMLTextAreaElement).value).toMatch(/손을 깨끗이 씻어요/);
    expect(document.body.textContent).not.toMatch(/\bAI\b/);
  });

  it("'더 알려 주기(선택)'는 접혀 있고, 펼치면 라벨이 위에 있는 업종·일하는 곳·근로자 특성", async () => {
    const user = await openNew();
    const toggle = screen.getByRole("button", { name: "더 알려 주기(선택)" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByLabelText("업종")).not.toBeVisible();
    await user.click(toggle);
    expect(screen.getByLabelText("업종")).toBeVisible();
    expect(screen.getByLabelText("일하는 곳")).toBeVisible();
    expect(screen.getByLabelText("근로자 특성")).toBeVisible();
  });

  it("?example=1이면 예시 지시문·업종을 채우고, 나누기는 사업주가 누를 때만 한다", async () => {
    await openNew("/m/tasks/new?example=1");
    expect((input() as HTMLTextAreaElement).value).toMatch(/손을 깨끗이 씻어요/);
    expect(screen.getByTestId("example-note")).toBeInTheDocument();
    expect(m.splitPreview).not.toHaveBeenCalled();
  });

  it("새로고침해도 적던 원문과 '더 알려 주기'가 남는다(이 기기에 임시 저장)", async () => {
    const user = await openNew();
    await user.type(input(), "컵을 씻어요");
    await user.click(screen.getByRole("button", { name: "더 알려 주기(선택)" }));
    await user.type(screen.getByLabelText("업종"), "카페");
    expect(JSON.parse(localStorage.getItem(NEW_TASK_DRAFT_KEY)!)).toMatchObject({ rawInput: "컵을 씻어요", businessType: "카페" });
    // 화면을 새로 그린다(새로고침 흉내).
    document.body.innerHTML = "";
    await openNew();
    expect((input() as HTMLTextAreaElement).value).toBe("컵을 씻어요");
    expect(screen.getByText("적던 내용을 다시 불러왔어요")).toBeInTheDocument();
    expect((screen.getByLabelText("업종") as HTMLInputElement).value).toBe("카페");
  });

  it("맞춤 대상 근로자를 고르면 worker_id를 함께 보내고, 고르지 않으면 보내지 않는다", async () => {
    m.listWorkers.mockResolvedValue([{ id: "w1", display_name: "김민지", access_code_hint: "12", access_code_length: 4 }]);
    const user = await openNew();
    await user.type(input(), INPUT);
    await user.click(screen.getByRole("button", { name: "단계로 나누기" }));
    await screen.findByRole("heading", { name: /이렇게 나눴어요/ });
    expect(m.splitPreview.mock.calls[0][1].worker_id).toBeUndefined();
    await user.click(screen.getByRole("button", { name: "더 알려 주기(선택)" }));
    await user.selectOptions(await screen.findByLabelText("맞춤 대상 근로자"), "w1");
    await user.type(input(), " ");
    await user.click(screen.getByRole("button", { name: "단계로 나누기" }));
    await waitFor(() => expect(m.splitPreview).toHaveBeenCalledTimes(2));
    expect(m.splitPreview.mock.calls[1][1].worker_id).toBe("w1");
  });
});

describe("쓰는 순간 나누기", () => {
  it("나누는 동안 '문장을 나누고 있어요'를 보이고, 직무는 아직 만들지 않는다", async () => {
    let resolve!: (v: unknown) => void;
    m.splitPreview.mockImplementation(() => new Promise((r) => (resolve = r)));
    const user = await openNew();
    await user.type(input(), INPUT);
    await user.click(screen.getByRole("button", { name: "단계로 나누기" }));
    expect(screen.getByText("문장을 나누고 있어요")).toBeInTheDocument();
    resolve(PREVIEW);
    await screen.findByRole("heading", { name: /이렇게 나눴어요/ });
    expect(m.createTask).not.toHaveBeenCalled();
  });

  it("애매한 줄만 노랗게, 원래 문장과 [합치기] — 합치면 원래 문장 한 줄로", async () => {
    const user = await openNew();
    await split(user);
    expect(screen.getByTestId("split-row-3")).toHaveAttribute("data-check", "true");
    expect(screen.getByTestId("split-row-1")).toHaveAttribute("data-check", "false");
    expect(screen.getByTestId("split-row-3")).toHaveTextContent(SOURCE);
    await user.click(screen.getByRole("button", { name: "3단계와 4단계 합치기" }));
    expect(rowTexts()).toEqual(["앞치마를 입어요.", "손을 씻어요.", SOURCE]);
    expect(document.activeElement).toBe(screen.getByLabelText("3단계 문장"));
  });

  it("뒤로 갔다 돌아와도(다시 그려도) 나눈 단계 목록과 고친 줄이 남는다(2회차 검증)", async () => {
    const user = await openNew();
    await split(user);
    const row2 = screen.getByLabelText("2단계 문장") as HTMLTextAreaElement;
    await user.clear(row2);
    await user.type(row2, "손을 비누로 씻어요.");
    document.body.innerHTML = "";
    await openNew();
    expect(rowTexts()).toEqual(["앞치마를 입어요.", "손을 비누로 씻어요.", "컵을 씻어요.", "컵을 칼로 긁어요."]);
    expect(screen.getByRole("button", { name: "이대로 그림 고르기" })).toBeInTheDocument();
    expect(m.splitPreview).toHaveBeenCalledTimes(1);
  });

  it("[더 나누기]는 커서 자리에서 자르고, 문장 칸 Enter는 줄바꿈을 넣지 않는다", async () => {
    const user = await openNew();
    await split(user);
    const row2 = screen.getByLabelText("2단계 문장") as HTMLTextAreaElement;
    await user.click(row2);
    await user.keyboard("{Enter}");
    expect(row2.value).toBe("손을 씻어요.");
    row2.setSelectionRange(2, 2);
    await user.click(screen.getByRole("button", { name: "2단계 더 나누기" }));
    expect(rowTexts().slice(1, 3)).toEqual(["손을", "씻어요."]);
  });

  it("빈 줄이 있으면 [이대로 그림 고르기] 전에 알려 준다", async () => {
    const user = await openNew();
    await split(user);
    await user.click(screen.getByRole("button", { name: "한 줄 추가" }));
    await user.click(screen.getByRole("button", { name: "이대로 그림 고르기" }));
    expect(screen.getByRole("alert")).toHaveTextContent("5단계가 비어 있어요");
    expect(m.createTask).not.toHaveBeenCalled();
  });

  it("나누기에 실패하면 한국어 오류를 보이고 초점은 다시 누를 수 있는 [단계로 나누기]로", async () => {
    m.splitPreview.mockRejectedValue(new Error("boom"));
    const user = await openNew();
    await user.type(input(), INPUT);
    screen.getByRole("button", { name: "단계로 나누기" }).focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent(/처리하지 못했어요|나누지 못했어요/);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "단계로 나누기" }));
  });

  it("키보드로 나누면 초점이 '이렇게 나눴어요' 제목으로 간다", async () => {
    const user = await openNew();
    await user.type(input(), INPUT);
    screen.getByRole("button", { name: "단계로 나누기" }).focus();
    await user.keyboard("{Enter}");
    const heading = await screen.findByRole("heading", { name: /이렇게 나눴어요/ });
    await waitFor(() => expect(document.activeElement).toBe(heading));
  });

  it("원문도 목록도 그대로면 다시 누를 수 없고, 고친 줄이 있으면 먼저 Dialog로 묻는다", async () => {
    const user = await openNew();
    await split(user);
    expect(screen.getByRole("button", { name: "단계로 나누기" })).toBeDisabled();
    await user.type(screen.getByLabelText("1단계 문장"), "!");
    await user.click(screen.getByRole("button", { name: "단계로 나누기" }));
    const dlg = await screen.findByRole("dialog", { name: "새로 나눌까요?" });
    await user.click(within(dlg).getByRole("button", { name: "취소" }));
    expect(m.splitPreview).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "단계로 나누기" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "새로 나누기" }));
    await waitFor(() => expect(m.splitPreview).toHaveBeenCalledTimes(2));
  });

  it("나눈 뒤 직무 내용을 고치면 다시 나누라고 알린다", async () => {
    const user = await openNew();
    await split(user);
    await user.type(input(), "!");
    expect(screen.getByText(/직무 내용을 고쳤어요/)).toBeInTheDocument();
  });

  it("화면에 '동작이 2개' 알림이 없다(나누기는 이 화면에서 끝냄)", async () => {
    const user = await openNew();
    await split(user);
    expect(document.body.textContent).not.toMatch(/동작이 2개/);
  });
});

describe("[이대로 그림 고르기] → 초안 → 편집기", () => {
  it("확인한 줄로 초안을 만든다: 나눈 방법·원래 지시문 조각·'✦ 자동 제안' 조심 표시를 함께, needs_review는 보내지 않는다", async () => {
    const user = await openNew();
    await split(user);
    await user.click(screen.getByRole("button", { name: "2단계 지우기" }));
    await user.click(screen.getByRole("button", { name: "이대로 그림 고르기" }));
    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(1));
    const [raw, opts] = m.createTask.mock.calls[0];
    expect(raw).toBe(INPUT);
    expect(opts.title).toBe("출근 준비");
    expect(opts.steps).toEqual([
      { sentence: "앞치마를 입어요.", action_type: "wear", symbol_query: ["앞치마"], split: { source: "", original_span: "앞치마를 입어요." } },
      { sentence: "컵을 씻어요.", action_type: "clean", symbol_query: ["컵"], split: { source: "model", original_span: SOURCE } },
      {
        sentence: "컵을 칼로 긁어요.", action_type: "move", symbol_query: ["칼"],
        split: { source: "model", original_span: SOURCE }, safety_flag: true,
      },
    ]);
    expect(JSON.stringify(opts.steps)).not.toMatch(/needs_review/);
  });

  it("만드는 동안 편집기 모양 스켈레톤: '그림을 고르고 있어요 → 목소리를 만들고 있어요', 퍼센트 숫자 없음", async () => {
    let resolve!: (v: unknown) => void;
    m.createTask.mockImplementation(() => new Promise((r) => (resolve = r)));
    const user = await openNew();
    await split(user);
    await user.click(screen.getByRole("button", { name: "이대로 그림 고르기" }));
    const sk = await screen.findByTestId("editor-skeleton");
    expect(sk).toHaveTextContent("그림을 고르고 있어요");
    expect(sk).toHaveTextContent("목소리를 만들고 있어요");
    expect(sk.textContent).not.toMatch(/%|퍼센트/);
    resolve(task([step("s1", 1, "앞치마를 입어요.", "auto_high")], { id: "task-9" }));
    await screen.findByTestId("task-editor");
  });

  it("초안을 만들면 같은 Route의 편집기(/m/tasks/:id)로 바뀌고, 방금 만든 초안을 다시 불러오지 않는다. 임시 저장도 지운다", async () => {
    const user = await openNew();
    await split(user);
    expect(localStorage.getItem(NEW_TASK_DRAFT_KEY)).not.toBeNull();
    await user.click(screen.getByRole("button", { name: "이대로 그림 고르기" }));
    await screen.findByTestId("task-editor");
    expect(screen.getByTestId("where")).toHaveTextContent("/m/tasks/task-9");
    expect(m.getTask).not.toHaveBeenCalled();
    expect(localStorage.getItem(NEW_TASK_DRAFT_KEY)).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "출근 준비" })).toBeInTheDocument();
  });

  it("[이대로 그림 고르기]가 실패하면 버튼 바로 아래에 이유를 보이고 입력 화면에 남는다", async () => {
    m.createTask.mockRejectedValue(new Error("x"));
    const user = await openNew();
    await split(user);
    await user.click(screen.getByRole("button", { name: "이대로 그림 고르기" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/처리하지 못했어요|초안을 만들지 못했어요/);
    expect(rowTexts()).toHaveLength(4);
  });
});

describe("떠날 때", () => {
  function renderWithLink() {
    return import("../../src/manager/tasks/TaskWorkspace").then(({ default: TaskWorkspace }) =>
      render(
        <ToastProvider>
          <MemoryRouter initialEntries={["/m/tasks/new"]}>
            <Link to="/m/tasks">사이드바 직무</Link>
            <Routes>
              <Route path="/m/tasks/:id" element={<TaskWorkspace key="ws" />} />
              <Route path="/m/tasks" element={<p>직무 목록</p>} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>,
      ),
    );
  }

  it("적던 내용이 있으면 다른 화면 링크를 누를 때 Dialog '적던 내용이 사라져요' — [계속 적기]면 남고 [나가기]면 떠난다", async () => {
    const user = userEvent.setup();
    await renderWithLink();
    await user.type(await screen.findByLabelText("어떤 일을 시킬까요?"), "컵을 씻어요");
    await user.click(screen.getByRole("link", { name: "사이드바 직무" }));
    const dlg = await screen.findByRole("dialog", { name: "적던 내용이 사라져요" });
    await user.click(within(dlg).getByRole("button", { name: "계속 적기" }));
    expect(screen.getByLabelText("어떤 일을 시킬까요?")).toHaveValue("컵을 씻어요");
    await user.click(screen.getByRole("link", { name: "사이드바 직무" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "나가기" }));
    expect(await screen.findByText("직무 목록")).toBeInTheDocument();
    expect(localStorage.getItem(NEW_TASK_DRAFT_KEY)).toBeNull();
  });

  it("비어 있으면 묻지 않고 떠난다", async () => {
    const user = userEvent.setup();
    await renderWithLink();
    await screen.findByLabelText("어떤 일을 시킬까요?");
    await user.click(screen.getByRole("link", { name: "사이드바 직무" }));
    expect(await screen.findByText("직무 목록")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
