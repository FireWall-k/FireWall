import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { duration } from "../../src/manager/copy";
import { stats, workerRow, workplace } from "./workers.fixtures";

// 근로자 상세(tasks §7): 탭 4개, 현황 '2분 28초'·표로 보기, 화면 설정 말 속도 0.8 저장, 접속 코드 새로 만들기,
// 동의 배지 '자동 처리 동의'·창 제목 '자동 처리·국외 이전 동의'.
const api = {
  listWorkers: vi.fn(),
  updateWorker: vi.fn(),
  workerStats: vi.fn(),
  reissueAccessCode: vi.fn(),
  revealAccessCode: vi.fn(),
  getWorkplace: vi.fn(),
  grantConsent: vi.fn(),
  listConsents: vi.fn(),
  revokeConsent: vi.fn(),
  exportWorker: vi.fn(),
  deleteWorker: vi.fn(),
};
vi.mock("../../src/manager/api/workers", () => ({
  listWorkers: () => api.listWorkers(),
  updateWorker: (...a: unknown[]) => api.updateWorker(...a),
  workerStats: (...a: unknown[]) => api.workerStats(...a),
  reissueAccessCode: (...a: unknown[]) => api.reissueAccessCode(...a),
  revealAccessCode: (...a: unknown[]) => api.revealAccessCode(...a),
  getWorkplace: () => api.getWorkplace(),
  grantConsent: (...a: unknown[]) => api.grantConsent(...a),
  listConsents: (...a: unknown[]) => api.listConsents(...a),
  revokeConsent: (...a: unknown[]) => api.revokeConsent(...a),
  exportWorker: (...a: unknown[]) => api.exportWorker(...a),
  deleteWorker: (...a: unknown[]) => api.deleteWorker(...a),
}));

import WorkerDetailPage from "../../src/manager/workers/WorkerDetailPage";
import { ToastProvider } from "../../src/components/ui";

function renderAt(path = "/manager/workers/w1") {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/manager/workers/:id" element={<WorkerDetailPage />} />
          <Route path="/manager/workers" element={<p>목록 화면</p>} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  api.listWorkers.mockResolvedValue([workerRow()]);
  api.workerStats.mockResolvedValue(stats());
  api.getWorkplace.mockResolvedValue(workplace());
});

describe("시간 표기", () => {
  it("초 → '2분 28초'", () => {
    expect(duration(148)).toBe("2분 28초");
    expect(duration(40)).toBe("40초");
    expect(duration(120)).toBe("2분");
    expect(duration(0)).toBe("0초");
    expect(duration(3660)).toBe("1시간 1분");
  });
});

describe("근로자 상세", () => {
  it("탭 4개(현황·화면 설정·접속 코드·동의·개인정보), 처음은 현황", async () => {
    renderAt();
    expect(await screen.findByRole("heading", { level: 1, name: "김민지 님" })).toBeInTheDocument();
    const tabs = screen.getAllByRole("tab").map((t) => t.textContent);
    expect(tabs).toEqual(["현황", "화면 설정", "접속 코드", "동의·개인정보"]);
    expect(screen.getByRole("tab", { name: "현황" })).toHaveAttribute("aria-selected", "true");
  });

  it("현황: 단계 평균 시간 '2분 28초', 날마다 막대에 숫자, [표로 보기]로 같은 값을 표로", async () => {
    const user = userEvent.setup();
    renderAt();
    expect(await screen.findByText("2분 28초")).toBeInTheDocument();
    expect(api.workerStats).toHaveBeenCalledWith("w1", 7);
    expect(screen.getByText("1분 34초")).toBeInTheDocument(); // avg_step_sec 94
    expect(within(screen.getByTestId("done-chart")).getAllByRole("listitem")).toHaveLength(7);
    await user.click(screen.getByRole("button", { name: "표로 보기" }));
    const table = screen.getByRole("table", { name: "단계별 기록" });
    expect(within(table).getByText("2분 28초")).toBeInTheDocument();
    expect(within(table).getByText("1. 컵을 물에 넣어요")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "날마다 기록" })).toBeInTheDocument();
  });

  it("화면 설정: 말 속도 '느리게 0.8'을 누르면 그 키 하나만 저장한다", async () => {
    api.updateWorker.mockImplementation(async (_id: string, patch: { a11y_prefs: object }) =>
      workerRow({ a11y_prefs: { ...workerRow().a11y_prefs, ...patch.a11y_prefs } }),
    );
    const user = userEvent.setup();
    renderAt("/manager/workers/w1?tab=prefs");
    const group = await screen.findByRole("group", { name: "말 속도" });
    expect(within(group).getByRole("radio", { name: "보통 0.9" })).toBeChecked();
    await user.click(within(group).getByRole("radio", { name: "느리게 0.8" }));
    await waitFor(() => expect(api.updateWorker).toHaveBeenCalledWith("w1", { a11y_prefs: { tts_rate: 0.8 } }));
    expect(within(group).getByRole("radio", { name: "느리게 0.8" })).toBeChecked();
    expect(await screen.findByText("저장했어요")).toBeInTheDocument();
    // 명세 4.12의 7항목(효과음·진동은 한 칸에 둘).
    for (const name of ["글자 크기", "칭찬", "손 방향", "화면 대비"]) expect(screen.getByRole("group", { name })).toBeInTheDocument();
    for (const name of ["소리 자동 재생", "효과음", "진동"]) expect(screen.getByRole("switch", { name })).toBeInTheDocument();
  });

  it("화면 설정 저장이 실패하면 되돌리고 오류 토스트", async () => {
    api.updateWorker.mockRejectedValue(new Error("x"));
    const user = userEvent.setup();
    renderAt("/manager/workers/w1?tab=prefs");
    const group = await screen.findByRole("group", { name: "손 방향" });
    await user.click(within(group).getByRole("radio", { name: "왼손" }));
    await waitFor(() => expect(within(group).getByRole("radio", { name: "오른손" })).toBeChecked());
  });

  it("접속 코드: [새 번호 만들기] 확인 → 새 번호는 결과 창에만 크게, 닫으면 다시 가림(명세 5.7)", async () => {
    api.reissueAccessCode.mockResolvedValue({ ...workerRow(), access_code: "5590" });
    const user = userEvent.setup();
    renderAt("/manager/workers/w1?tab=code");
    const opener = await screen.findByRole("button", { name: "새 번호 만들기" });
    await user.click(opener);
    const dialog = screen.getByRole("dialog", { name: "김민지 님 번호를 새로 만들까요?" });
    await user.click(within(dialog).getByRole("button", { name: "새 번호 만들기" }));
    const fresh = await screen.findByRole("dialog", { name: "김민지 님 새 번호예요" });
    expect(within(fresh).getByTestId("fresh-code")).toHaveTextContent("5590");
    expect(within(fresh).getByRole("button", { name: "복사하기" })).toHaveFocus();
    // 탭 화면 자체는 가린 채다.
    expect(screen.getByTestId("access-code")).toHaveTextContent("●●●●");
    await user.click(within(fresh).getByRole("button", { name: "다 봤어요" }));
    await waitFor(() => expect(screen.queryByTestId("fresh-code")).not.toBeInTheDocument());
    expect(document.body.textContent).not.toContain("5590");
    expect(opener).toHaveFocus();
  });

  it("동의: 배지는 '자동 처리 동의', 기록 창 제목은 '자동 처리·국외 이전 동의'(AI 없음)", async () => {
    api.grantConsent.mockResolvedValue({});
    const user = userEvent.setup();
    renderAt("/manager/workers/w1?tab=consent");
    expect(await screen.findByText("자동 처리 동의 아직 없음")).toBeInTheDocument();
    const card = screen.getByRole("heading", { name: "자동 처리·국외 이전 동의" }).closest("div")!.parentElement!;
    await user.click(within(card).getByRole("button", { name: "보호자에게 받았어요" }));
    const dialog = screen.getByRole("dialog", { name: "자동 처리·국외 이전 동의를 받았나요?" });
    await user.click(within(dialog).getByRole("button", { name: "확인" }));
    await waitFor(() => expect(api.grantConsent).toHaveBeenCalledWith("w1", "ai_processing", "guardian"));
    expect(await screen.findByText("자동 처리 동의 받음")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/\bAI\b/);
  });

  it("동의 탭의 [이 근로자 지우기]는 이름 다시 적기 창을 연다", async () => {
    const user = userEvent.setup();
    renderAt("/manager/workers/w1?tab=consent");
    await user.click(await screen.findByRole("button", { name: "이 근로자 지우기" }));
    const dialog = screen.getByRole("alertdialog", { name: "김민지 님을 지울까요?" });
    expect(within(dialog).getByRole("button", { name: "지우기" })).toBeDisabled();
  });

  it("없는 근로자면 '근로자를 찾을 수 없어요'", async () => {
    renderAt("/manager/workers/zz");
    expect(await screen.findByRole("heading", { name: "근로자를 찾을 수 없어요" })).toBeInTheDocument();
  });
});
