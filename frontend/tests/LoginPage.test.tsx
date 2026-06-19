import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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

    fireEvent.click(screen.getByText("로그인"));
    await waitFor(() => expect(onLogin).toHaveBeenCalledWith(state));
    expect(loginEmployer).toHaveBeenCalledWith("demo", "demo1234");
  });

  it("근로자 탭에서는 접속 코드로 로그인한다", async () => {
    loginWorker.mockResolvedValue({ token: "t", role: "worker", displayName: "김근로" });
    const onLogin = vi.fn();
    render(<LoginPage onLogin={onLogin} />);

    fireEvent.click(screen.getByText("근로자"));
    fireEvent.click(screen.getByText("로그인"));
    await waitFor(() => expect(loginWorker).toHaveBeenCalledWith("1234"));
  });

  it("로그인 실패 시 에러 메시지를 보여준다", async () => {
    loginEmployer.mockRejectedValue(new Error("아이디 또는 비밀번호가 올바르지 않습니다."));
    render(<LoginPage onLogin={vi.fn()} />);
    fireEvent.click(screen.getByText("로그인"));
    await screen.findByText("아이디 또는 비밀번호가 올바르지 않습니다.");
  });
});
