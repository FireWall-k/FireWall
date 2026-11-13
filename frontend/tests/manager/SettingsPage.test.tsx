import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ApiError } from "../../src/apiErrors";
import { workplace } from "./workers.fixtures";

// 설정(tasks §7): 사업장 이름·코드 복사, 기기 연결 QR·주소, 근로자 화면 기본값, 호칭(미리보기·한글 1~6자), 알림, 계정.
const api = { getWorkplace: vi.fn(), updateWorkplace: vi.fn() };
vi.mock("../../src/manager/api/workers", () => ({
  getWorkplace: () => api.getWorkplace(),
  updateWorkplace: (p: unknown) => api.updateWorkplace(p),
}));

import SettingsPage from "../../src/manager/settings/SettingsPage";
import { ToastProvider } from "../../src/components/ui";

const onLogout = vi.fn();
function renderPage() {
  return render(
    <ToastProvider>
      <MemoryRouter>
        <SettingsPage displayName="데모 사장님" onLogout={onLogout} />
      </MemoryRouter>
    </ToastProvider>,
  );
}

beforeEach(() => {
  api.getWorkplace.mockReset().mockResolvedValue(workplace());
  api.updateWorkplace.mockReset();
  onLogout.mockReset();
});

describe("설정", () => {
  it("사업장 코드·기기 연결 주소·QR이 보이고 PIN 칸은 없다", async () => {
    renderPage();
    expect(await screen.findByTestId("workplace-code")).toHaveTextContent("DEMO01");
    expect(screen.getByTestId("device-link")).toHaveTextContent("http://localhost:5173/worker?site=DEMO01");
    expect(screen.getByRole("img", { name: "기기 연결 주소" })).toBeInTheDocument();
    expect(screen.queryByText(/PIN|선생님 모드/)).toBeNull();
    expect(screen.getByRole("switch", { name: "도움 알림 받기" })).toBeDisabled();
  });

  it("호칭 미리보기: 받침 없는 '코치'를 적으면 '코치를 불렀어요'·'코치가 확인했어요'로 바로 바뀐다", async () => {
    const user = userEvent.setup();
    renderPage();
    const input = await screen.findByLabelText(/^호칭/);
    const preview = screen.getByTestId("title-preview");
    expect(preview).toHaveTextContent("선생님을 불렀어요. 여기서 기다려요.");
    expect(preview).toHaveTextContent("선생님이 확인했어요");
    await user.clear(input);
    await user.type(input, "코치");
    expect(preview).toHaveTextContent("코치를 불렀어요. 여기서 기다려요.");
    expect(preview).toHaveTextContent("코치가 확인했어요");
    expect(preview).toHaveTextContent("코치께 번호를 물어봐요.");
    api.updateWorkplace.mockResolvedValue(workplace({ teacher_title: "코치" }));
    await user.click(screen.getByRole("button", { name: "호칭 저장하기" }));
    await waitFor(() => expect(api.updateWorkplace).toHaveBeenCalledWith({ teacher_title: "코치" }));
    expect(await screen.findByText("호칭을 저장했어요")).toBeInTheDocument();
  });

  it("호칭이 한글 1~6자가 아니면 서버에 보내지 않고 같은 문장을 보인다", async () => {
    const user = userEvent.setup();
    renderPage();
    const input = await screen.findByLabelText(/^호칭/);
    await user.clear(input);
    await user.type(input, "Coach");
    await user.click(screen.getByRole("button", { name: "호칭 저장하기" }));
    expect(screen.getByText("호칭은 한글 1~6자로 적어 주세요.")).toBeInTheDocument();
    expect(api.updateWorkplace).not.toHaveBeenCalled();
  });

  it("서버가 422를 주면 서버 문장을 칸 아래에", async () => {
    api.updateWorkplace.mockRejectedValue(new ApiError(422, "사업장 이름을 1~40자로 적어 주세요."));
    const user = userEvent.setup();
    renderPage();
    const input = await screen.findByLabelText("사업장 이름");
    await user.clear(input);
    await user.type(input, "새 이름");
    await user.click(screen.getByRole("button", { name: "이름 저장하기" }));
    expect(await screen.findByText("사업장 이름을 1~40자로 적어 주세요.")).toBeInTheDocument();
  });

  it("근로자 화면 기본값: 말 속도 0.8은 worker_defaults 그 키만 보낸다", async () => {
    api.updateWorkplace.mockImplementation(async (p: { worker_defaults: object }) =>
      workplace({ worker_defaults: { ...workplace().worker_defaults, ...p.worker_defaults } }),
    );
    const user = userEvent.setup();
    renderPage();
    const group = await screen.findByRole("group", { name: "말 속도" });
    await user.click(within(group).getByRole("radio", { name: "느리게 0.8" }));
    await waitFor(() => expect(api.updateWorkplace).toHaveBeenCalledWith({ worker_defaults: { tts_rate: 0.8 } }));
    expect(screen.getByText("새로 추가하는 근로자에게 이 값이 들어가요. 이미 있는 근로자는 바뀌지 않아요.")).toBeInTheDocument();
  });

  it("[인쇄용 카드 만들기]는 사업장 이름·QR·사업장 코드 카드를 연다", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "인쇄용 카드 만들기" }));
    const card = screen.getByRole("dialog", { name: "기기 연결 카드" });
    expect(within(card).getByText("햇살카페")).toBeInTheDocument();
    expect(within(card).getByText("DEMO01")).toBeInTheDocument();
    expect(within(card).getByRole("img", { name: "기기 연결 QR 코드" })).toBeInTheDocument();
  });

  it("계정: 이름과 [로그아웃]", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText("데모 사장님")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "로그아웃" }));
    expect(onLogout).toHaveBeenCalled();
  });
});
