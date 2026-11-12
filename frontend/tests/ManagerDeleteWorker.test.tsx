// (2d 검증 1회차) 옛 새 직무 화면(/m/tasks/new, 2b-1이 지울 때까지)의 근로자 휴지통 단추.
// 서버는 이름을 다시 적어야 지운다(POST /delete). 이름 없이 보내 늘 422가 나던 회귀를 막는다.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ManagerPage from "../src/pages/ManagerPage";

const deleteWorker = vi.fn();

const PREVIEW = {
  task_title: "출근 준비",
  job: "cafe",
  steps: [
    { order: 1, sentence: "앞치마를 입어요.", action_type: "wear", symbol_query: ["앞치마"],
      split_group: null, split_check: false, source_text: null },
  ],
};

vi.mock("../src/api", () => ({
  api: {
    splitPreview: () => Promise.resolve(PREVIEW),
    createTask: (_raw: string, ctx: { steps: { sentence: string }[] }) =>
      Promise.resolve({
        id: "task-1", title: "출근 준비", status: "draft",
        steps: ctx.steps.map((st, i) => ({
          id: `s${i + 1}`, order: i + 1, sentence: st.sentence, action_type: "other", symbol_url: null,
          symbol_source: "fallback", needs_fallback: true, tts_audio_url: null,
        })),
      }),
    stepSymbolCandidates: (_t: string, s: string) => Promise.resolve({ step_id: s, reason: "no_candidate", candidates: [] }),
    listWorkers: () =>
      Promise.resolve([{ id: "w1", display_name: "김민지", access_code: null, access_code_hint: "21", access_code_length: 4 }]),
    deleteWorker: (id: string, name?: string) => deleteWorker(id, name),
    updateStep: vi.fn(),
  },
}));

let promptSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  deleteWorker.mockReset();
  deleteWorker.mockResolvedValue({ ok: true, name_mentions: [] });
});
afterEach(() => promptSpy?.mockRestore());

async function openWorkers(user: ReturnType<typeof userEvent.setup>) {
  render(<ManagerPage />);
  await user.type(screen.getByLabelText("직무 내용"), "앞치마 입어");
  await user.click(screen.getByRole("button", { name: "단계로 나누기" }));
  await user.click(await screen.findByRole("button", { name: "이대로 그림 고르기 ›" }));
  return screen.findByRole("button", { name: "근로자 김민지 삭제" });
}

describe("옛 새 직무 화면 — 근로자 지우기", () => {
  it("적은 이름을 함께 보내 지운다", async () => {
    promptSpy = vi.spyOn(window, "prompt").mockReturnValue("김민지");
    const user = userEvent.setup();
    await user.click(await openWorkers(user));
    await waitFor(() => expect(deleteWorker).toHaveBeenCalledWith("w1", "김민지"));
    expect(await screen.findByText(/삭제했습니다/)).toBeInTheDocument();
  });

  it("창을 닫으면(취소) 보내지 않는다", async () => {
    promptSpy = vi.spyOn(window, "prompt").mockReturnValue(null);
    const user = userEvent.setup();
    await user.click(await openWorkers(user));
    expect(promptSpy).toHaveBeenCalled();
    expect(deleteWorker).not.toHaveBeenCalled();
  });
});
