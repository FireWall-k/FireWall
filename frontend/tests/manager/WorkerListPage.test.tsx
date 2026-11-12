import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ApiError } from "../../src/apiErrors";
import { workerRow, workplace } from "./workers.fixtures";

// 근로자 목록(tasks §7 FEATURE·시험): 번호 ●●●● + 눈 5초 뒤 다시 가림, 근로자 추가 → 4자리 크게·복사·인쇄 카드,
// 이름을 다르게 적으면 [지우기]가 꺼짐, 서버에 이름을 함께 보냄. 서버 호출은 manager/api/workers를 통째로 목으로.
const api = {
  listWorkers: vi.fn(),
  createWorker: vi.fn(),
  revealAccessCode: vi.fn(),
  deleteWorker: vi.fn(),
  getWorkplace: vi.fn(),
};
vi.mock("../../src/manager/api/workers", () => ({
  listWorkers: () => api.listWorkers(),
  createWorker: (n: string, note?: string) => api.createWorker(n, note),
  revealAccessCode: (id: string) => api.revealAccessCode(id),
  deleteWorker: (id: string, name: string) => api.deleteWorker(id, name),
  getWorkplace: () => api.getWorkplace(),
}));

import WorkerListPage from "../../src/manager/workers/WorkerListPage";
import { ToastProvider } from "../../src/components/ui";
import { REVEAL_MS } from "../../src/manager/workers/helpers";

function renderPage() {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={["/m/workers"]}>
        <Routes>
          <Route path="/m/workers" element={<WorkerListPage />} />
          <Route path="/m/workers/:id" element={<p>상세 화면</p>} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  api.listWorkers.mockResolvedValue([workerRow(), workerRow({ id: "w2", display_name: "이준호", today_badge: "help_coming", consent_state: "complete" })]);
  api.getWorkplace.mockResolvedValue(workplace());
});
afterEach(() => {
  vi.useRealTimers();
});

describe("근로자 목록", () => {
  it("열: 이름·오늘 배지('도움 가는 중' 포함)·7일 완료·도움 수·동의('자동 처리 미동의')·번호는 ●●●●", async () => {
    renderPage();
    const row = (await screen.findByRole("link", { name: "김민지" })).closest("tr")!;
    expect(within(row).getAllByText("하는 중").length).toBeGreaterThan(0);
    expect(within(row).getByRole("img", { name: "최근 7일 동안 5번 다 했어요" })).toBeInTheDocument();
    expect(within(row).getAllByText("자동 처리 미동의").length).toBeGreaterThan(0);
    expect(within(row).getByTestId("access-code")).toHaveTextContent("●●●●");
    const row2 = screen.getByRole("link", { name: "이준호" }).closest("tr")!;
    expect(within(row2).getAllByText("도움 가는 중").length).toBeGreaterThan(0);
    // 화면 어디에도 'AI'가 없다.
    expect(document.body.textContent).not.toMatch(/\bAI\b/);
  });

  it("눈을 누르면 번호를 서버에서 받아 보이고, 5초 뒤 다시 가린다", async () => {
    api.revealAccessCode.mockResolvedValue({ code: "4821" });
    renderPage();
    const row = (await screen.findByRole("link", { name: "김민지" })).closest("tr")!;
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(within(row).getByRole("button", { name: "김민지 님 번호 5초 보기" }));
    await waitFor(() => expect(within(row).getByTestId("access-code")).toHaveTextContent("4821"));
    expect(api.revealAccessCode).toHaveBeenCalledWith("w1");
    expect(within(row).getByRole("button", { name: "김민지 님 번호 가리기" })).toHaveAttribute("aria-pressed", "true");
    act(() => {
      vi.advanceTimersByTime(REVEAL_MS - 100);
    });
    expect(within(row).getByTestId("access-code")).toHaveTextContent("4821");
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(within(row).getByTestId("access-code")).toHaveTextContent("●●●●");
    expect(REVEAL_MS).toBe(5000);
  });

  it("너무 자주 열면(429) 서버 문장을 오류 토스트로 보이고 번호는 가린 채로 둔다", async () => {
    api.revealAccessCode.mockRejectedValue(new ApiError(429, "번호를 너무 자주 열었어요. 1분 뒤에 다시 눌러 주세요."));
    const user = userEvent.setup();
    renderPage();
    const row = (await screen.findByRole("link", { name: "김민지" })).closest("tr")!;
    await user.click(within(row).getByRole("button", { name: "김민지 님 번호 5초 보기" }));
    expect(await screen.findByText("번호를 너무 자주 열었어요. 1분 뒤에 다시 눌러 주세요.")).toBeInTheDocument();
    expect(within(row).getByTestId("access-code")).toHaveTextContent("●●●●");
  });

  it("[근로자 추가하기] → 이름·메모 → 4자리 번호를 크게, [복사하기]·[인쇄용 카드 만들기](QR·번호)", async () => {
    api.createWorker.mockResolvedValue({ ...workerRow({ id: "w3", display_name: "박서연" }), access_code: "0712" });
    const writeText = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    // userEvent.setup()이 자기 클립보드를 붙이므로 그 뒤에 바꾼다.
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderPage();
    await screen.findByRole("link", { name: "김민지" });
    await user.click(screen.getByRole("button", { name: "근로자 추가하기" }));
    const dialog = screen.getByRole("dialog", { name: "근로자 추가하기" });
    await user.type(within(dialog).getByLabelText(/이름/), "박서연");
    await user.type(within(dialog).getByLabelText(/특성 메모/), "그림을 좋아해요");
    await user.click(within(dialog).getByRole("button", { name: "추가하기" }));
    const done = await screen.findByRole("dialog", { name: "박서연 님을 추가했어요" });
    expect(api.createWorker).toHaveBeenCalledWith("박서연", "그림을 좋아해요");
    expect(within(done).getByTestId("new-worker-code")).toHaveTextContent(/^\d{4}$/);
    expect(within(done).getByTestId("new-worker-code")).toHaveTextContent("0712");
    await user.click(within(done).getByRole("button", { name: "복사하기" }));
    expect(writeText).toHaveBeenCalledWith("0712");
    await user.click(within(done).getByRole("button", { name: "인쇄용 카드 만들기" }));
    const card = await screen.findByRole("dialog", { name: "인쇄용 카드" });
    expect(within(card).getByTestId("print-code")).toHaveTextContent("0712");
    expect(within(card).getByText("박서연 님")).toBeInTheDocument();
    await waitFor(() => expect(within(card).getByRole("img", { name: "기기 연결 QR 코드" })).toBeInTheDocument());
    // 목록에도 새 근로자가 붙는다.
    expect(screen.getByRole("link", { name: "박서연" })).toBeInTheDocument();
  });

  it("지우기: 이름을 다르게 적으면 [지우기]가 꺼지고, 같게 적으면 이름과 함께 서버로 보낸다", async () => {
    api.deleteWorker.mockResolvedValue({ ok: true, name_mentions: [{ task_id: "t1", title: "김민지 컵 씻기" }] });
    const user = userEvent.setup();
    renderPage();
    const row = (await screen.findByRole("link", { name: "김민지" })).closest("tr")!;
    await user.click(within(row).getByRole("button", { name: "김민지 님 메뉴" }));
    await user.click(screen.getByRole("menuitem", { name: /지우기/ }));
    const dialog = screen.getByRole("alertdialog", { name: "김민지 님을 지울까요?" });
    const confirm = within(dialog).getByRole("button", { name: "지우기" });
    expect(confirm).toBeDisabled();
    const input = within(dialog).getByRole("textbox");
    await user.type(input, "김민수");
    expect(confirm).toBeDisabled();
    await user.clear(input);
    await user.type(input, "김민지");
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    await waitFor(() => expect(api.deleteWorker).toHaveBeenCalledWith("w1", "김민지"));
    expect(await screen.findByText("김민지 님을 지웠어요 · 직무 1개에 이름이 남아 있어요 · 직무 문장을 고쳐 주세요")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("link", { name: "김민지" })).toBeNull());
  });

  it("근로자가 없으면 빈 상태", async () => {
    api.listWorkers.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText("아직 근로자가 없어요")).toBeInTheDocument();
  });
});
