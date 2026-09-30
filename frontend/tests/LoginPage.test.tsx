import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LoginPage from "../src/pages/LoginPage";

const loginEmployer = vi.fn();
const loginWorker = vi.fn();

vi.mock("../src/api", () => ({
  auth: {
    loginEmployer: (id: string, pw: string) => loginEmployer(id, pw),
    loginWorker: (code: string) => loginWorker(code),
  },
}));

beforeEach(() => {
  loginEmployer.mockReset();
  loginWorker.mockReset();
});

describe("LoginPage", () => {
  it("사업주 로그인 성공 시 onLogin 콜백을 호출한다", async () => {
    const state = { token: "t", role: "employer" as const, displayName: "데모" };
    loginEmployer.mockResolvedValue(state);
    const onLogin = vi.fn();
    render(<LoginPage onLogin={onLogin} />);

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("아이디"), "itda");
    await user.type(screen.getByLabelText("비밀번호"), "secret-pass");
    await user.click(screen.getByText("로그인"));
    await waitFor(() => expect(onLogin).toHaveBeenCalledWith(state));
    expect(loginEmployer).toHaveBeenCalledWith("itda", "secret-pass");
  });

  it("근로자 탭에서는 접속 코드로 로그인한다", async () => {
    loginWorker.mockResolvedValue({ token: "t", role: "worker", displayName: "김근로" });
    const onLogin = vi.fn();
    render(<LoginPage onLogin={onLogin} />);

    const user = userEvent.setup();
    await user.click(screen.getByText("근로자"));
    await user.type(screen.getByLabelText("접속 코드"), "482913");
    await user.click(screen.getByText("로그인"));
    await waitFor(() => expect(loginWorker).toHaveBeenCalledWith("482913"));
  });

  it("로그인 실패 시 에러 메시지를 보여준다", async () => {
    loginEmployer.mockRejectedValue(new Error("아이디 또는 비밀번호가 올바르지 않습니다."));
    render(<LoginPage onLogin={vi.fn()} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("아이디"), "itda");
    await user.type(screen.getByLabelText("비밀번호"), "wrong-pass");
    await user.click(screen.getByText("로그인"));
    await screen.findByText("아이디 또는 비밀번호가 올바르지 않습니다.");
  });

  it("입력칸은 비어 있고, 데모 계정 안내가 화면에 없다", () => {
    render(<LoginPage onLogin={vi.fn()} />);
    expect(screen.getByLabelText("아이디")).toHaveValue("");
    expect(screen.getByLabelText("비밀번호")).toHaveValue("");
    expect(screen.queryByText(/demo/i)).not.toBeInTheDocument();
  });

  it("입력이 비어 있으면 로그인 버튼이 눌리지 않는다", async () => {
    render(<LoginPage onLogin={vi.fn()} />);
    const button = screen.getByRole("button", { name: "로그인" });
    expect(button).toBeDisabled();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("아이디"), "itda");
    expect(button).toBeDisabled(); // 비밀번호가 아직 비어 있다
    await user.type(screen.getByLabelText("비밀번호"), "secret-pass");
    expect(button).toBeEnabled();
    expect(loginEmployer).not.toHaveBeenCalled();
  });
});
