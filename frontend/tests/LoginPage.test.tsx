import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LoginPage from "../src/pages/LoginPage";

const loginEmployer = vi.fn();
const loginWorker = vi.fn();
const demoCredentials = vi.fn();

vi.mock("../src/api", () => ({
  auth: {
    loginEmployer: (id: string, pw: string) => loginEmployer(id, pw),
    loginWorker: (workplace: string, code: string) => loginWorker(workplace, code),
    demoCredentials: () => demoCredentials(),
  },
}));

beforeEach(() => {
  loginEmployer.mockReset();
  loginWorker.mockReset();
  demoCredentials.mockReset();
  // 기본은 데모 계정이 없는 서버(운영) — 기존 테스트는 빈 칸에서 시작한다.
  demoCredentials.mockResolvedValue(null);
  localStorage.clear();
});

describe("LoginPage 데모 계정 미리 채우기", () => {
  const demo = {
    employer: { login_id: "demo", password: "demo1234" },
    worker: { workplace_code: "HGP2ET", access_code: "1234" },
  };

  it("사업주: 로그인만 누르면 데모 계정으로 로그인한다", async () => {
    demoCredentials.mockResolvedValue(demo);
    loginEmployer.mockResolvedValue({ token: "t", role: "employer", displayName: "데모" });
    render(<LoginPage onLogin={vi.fn()} />);
    await waitFor(() => expect(screen.getByLabelText("아이디")).toHaveValue("demo"));
    expect(screen.getByText(/데모 계정이 미리 채워져/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "로그인" }));
    await waitFor(() => expect(loginEmployer).toHaveBeenCalledWith("demo", "demo1234"));
  });

  it("근로자: 사업장 코드와 접속 코드가 채워져 로그인만 누르면 된다", async () => {
    demoCredentials.mockResolvedValue(demo);
    loginWorker.mockResolvedValue({ token: "t", role: "worker", displayName: "김근로" });
    render(<LoginPage onLogin={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "근로자" }));
    await waitFor(() => expect(screen.getByLabelText("접속 코드")).toHaveValue("1234"));
    await user.click(screen.getByRole("button", { name: "로그인" }));
    await waitFor(() => expect(loginWorker).toHaveBeenCalledWith("HGP2ET", "1234"));
  });

  it("데모 계정이 없는 서버(운영)에서는 아무것도 채우지 않는다", async () => {
    render(<LoginPage onLogin={vi.fn()} />);
    await waitFor(() => expect(demoCredentials).toHaveBeenCalled());
    expect(screen.getByLabelText("아이디")).toHaveValue("");
    expect(screen.queryByText(/데모 계정이 미리 채워져/)).not.toBeInTheDocument();
  });

  it("응답 전에 입력한 값은 덮어쓰지 않는다", async () => {
    let resolve: (v: typeof demo) => void = () => {};
    demoCredentials.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<LoginPage onLogin={vi.fn()} />);
    await userEvent.setup().type(screen.getByLabelText("아이디"), "itda");
    resolve(demo);
    await waitFor(() => expect(screen.getByLabelText("비밀번호")).toHaveValue("demo1234"));
    expect(screen.getByLabelText("아이디")).toHaveValue("itda");
  });

  it("이 기기에 다른 사업장이 저장돼 있으면 데모 근로자 코드를 넣지 않는다", async () => {
    localStorage.setItem("jobcard_workplace_code", "OTHER9");
    demoCredentials.mockResolvedValue(demo);
    render(<LoginPage onLogin={vi.fn()} />);
    await userEvent.setup().click(screen.getByRole("tab", { name: "근로자" }));
    await waitFor(() => expect(screen.getByText(/데모 계정이 미리 채워져/)).toBeInTheDocument());
    expect(screen.getByLabelText("접속 코드")).toHaveValue("");
  });
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
    await user.click(screen.getByRole("button", { name: "로그인" }));
    await waitFor(() => expect(onLogin).toHaveBeenCalledWith(state));
    expect(loginEmployer).toHaveBeenCalledWith("itda", "secret-pass");
  });

  it("근로자 탭에서는 사업장 코드 + 접속 코드로 로그인한다", async () => {
    loginWorker.mockResolvedValue({ token: "t", role: "worker", displayName: "김근로" });
    const onLogin = vi.fn();
    render(<LoginPage onLogin={onLogin} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "근로자" }));
    await user.type(screen.getByLabelText("사업장 코드"), "DEMO01");
    await user.type(screen.getByLabelText("접속 코드"), "482913");
    await user.click(screen.getByRole("button", { name: "로그인" }));
    await waitFor(() => expect(loginWorker).toHaveBeenCalledWith("DEMO01", "482913"));
  });

  it("로그인 실패 시 에러 메시지를 보여준다", async () => {
    loginEmployer.mockRejectedValue(new Error("아이디 또는 비밀번호가 올바르지 않습니다."));
    render(<LoginPage onLogin={vi.fn()} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("아이디"), "itda");
    await user.type(screen.getByLabelText("비밀번호"), "wrong-pass");
    await user.click(screen.getByRole("button", { name: "로그인" }));
    await screen.findByText("아이디 또는 비밀번호가 올바르지 않습니다.");
  });

  it("입력칸은 비어 있고, 데모 계정 안내가 화면에 없다", () => {
    render(<LoginPage onLogin={vi.fn()} />);
    expect(screen.getByLabelText("아이디")).toHaveValue("");
    expect(screen.getByLabelText("비밀번호")).toHaveValue("");
    expect(screen.queryByText(/demo/i)).not.toBeInTheDocument();
  });

  it("로그인에 성공하면 사업장 코드를 기기에 저장하고, 다음부터는 접속 코드만 묻는다", async () => {
    loginWorker.mockResolvedValue({ token: "t", role: "worker", displayName: "김근로" });
    const user = userEvent.setup();
    const { unmount } = render(<LoginPage onLogin={vi.fn()} />);
    await user.click(screen.getByRole("tab", { name: "근로자" }));
    await user.type(screen.getByLabelText("사업장 코드"), " demo-01 ");
    await user.type(screen.getByLabelText("접속 코드"), "1234");
    await user.click(screen.getByRole("button", { name: "로그인" }));
    await waitFor(() => expect(loginWorker).toHaveBeenCalled());
    expect(localStorage.getItem("jobcard_workplace_code")).toBe("DEMO01");
    unmount();

    // 같은 기기에서 다음 근로자가 로그인할 때
    render(<LoginPage onLogin={vi.fn()} />);
    await user.click(screen.getByRole("tab", { name: "근로자" }));
    expect(screen.queryByLabelText("사업장 코드")).not.toBeInTheDocument();
    expect(screen.getByText("DEMO01")).toBeInTheDocument();
    await user.type(screen.getByLabelText("접속 코드"), "5678");
    await user.click(screen.getByRole("button", { name: "로그인" }));
    await waitFor(() => expect(loginWorker).toHaveBeenLastCalledWith("DEMO01", "5678"));
  });

  it("로그인에 실패하면 사업장 코드를 저장하지 않는다", async () => {
    loginWorker.mockRejectedValue(new Error("사업장 코드 또는 접속 코드가 올바르지 않습니다."));
    const user = userEvent.setup();
    render(<LoginPage onLogin={vi.fn()} />);
    await user.click(screen.getByRole("tab", { name: "근로자" }));
    await user.type(screen.getByLabelText("사업장 코드"), "WRONG1");
    await user.type(screen.getByLabelText("접속 코드"), "1234");
    await user.click(screen.getByRole("button", { name: "로그인" }));
    await screen.findByText("사업장 코드 또는 접속 코드가 올바르지 않습니다.");
    expect(localStorage.getItem("jobcard_workplace_code")).toBeNull();
  });

  it("'이 기기 사업장 변경'으로 저장된 사업장 코드를 바꿀 수 있다", async () => {
    localStorage.setItem("jobcard_workplace_code", "OLDWP2");
    loginWorker.mockResolvedValue({ token: "t", role: "worker", displayName: "김근로" });
    const user = userEvent.setup();
    render(<LoginPage onLogin={vi.fn()} />);
    await user.click(screen.getByRole("tab", { name: "근로자" }));
    expect(screen.getByText("OLDWP2")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "이 기기 사업장 변경" }));
    const input = screen.getByLabelText("사업장 코드");
    expect(input).toHaveValue("");
    await user.type(input, "NEWWP3");
    await user.type(screen.getByLabelText("접속 코드"), "1234");
    await user.click(screen.getByRole("button", { name: "로그인" }));
    await waitFor(() => expect(loginWorker).toHaveBeenCalledWith("NEWWP3", "1234"));
    expect(localStorage.getItem("jobcard_workplace_code")).toBe("NEWWP3");
  });

  it("사업장 코드가 없으면 근로자 로그인 버튼이 눌리지 않는다", async () => {
    const user = userEvent.setup();
    render(<LoginPage onLogin={vi.fn()} />);
    await user.click(screen.getByRole("tab", { name: "근로자" }));
    await user.type(screen.getByLabelText("접속 코드"), "1234");
    expect(screen.getByRole("button", { name: "로그인" })).toBeDisabled();
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

describe("LoginPage 오류 문구·근로자 입구(0차)", () => {
  it("번호가 틀리면(401) 서버 문장을 그대로 보인다", async () => {
    const user = userEvent.setup();
    localStorage.setItem("jobcard_workplace_code", "DEMO01");
    loginWorker.mockRejectedValue(new Error("사업장 코드 또는 접속 코드가 올바르지 않습니다."));
    render(<LoginPage onLogin={vi.fn()} />);
    await user.click(screen.getByRole("tab", { name: "근로자" }));
    await user.type(screen.getByLabelText("접속 코드"), "9999");
    await user.click(screen.getByRole("button", { name: "로그인" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("사업장 코드 또는 접속 코드가 올바르지 않습니다.");
    expect(screen.queryByText(/로그인이 필요합니다/)).not.toBeInTheDocument();
  });

  it("'근로자이신가요? 근로자 화면으로 ›' 링크가 /w로 간다", () => {
    render(<LoginPage onLogin={vi.fn()} />);
    expect(screen.getByRole("link", { name: "근로자 화면으로 ›" })).toHaveAttribute("href", "/worker");
  });

  it("/login?tab=worker로 오면 근로자 탭이 열려 있다(예전 긴 번호용 우회로)", () => {
    window.history.pushState({}, "", "/login?tab=worker");
    try {
      render(<LoginPage onLogin={vi.fn()} />);
      expect(screen.getByLabelText("접속 코드")).toBeInTheDocument();
    } finally {
      window.history.pushState({}, "", "/");
    }
  });
});

describe("LoginPage 새 화면(2a-1, 명세 5.1)", () => {
  it("Enter로 제출된다(form)", async () => {
    const state = { token: "t", role: "employer" as const, displayName: "데모" };
    loginEmployer.mockResolvedValue(state);
    const onLogin = vi.fn();
    render(<LoginPage onLogin={onLogin} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("아이디"), "itda");
    await user.type(screen.getByLabelText("비밀번호"), "secret-pass{Enter}");
    await waitFor(() => expect(loginEmployer).toHaveBeenCalledWith("itda", "secret-pass"));
    await waitFor(() => expect(onLogin).toHaveBeenCalledWith(state));
  });

  it("빈 칸에서 Enter를 눌러도 서버를 부르지 않는다", async () => {
    render(<LoginPage onLogin={vi.fn()} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("아이디"), "itda{Enter}");
    expect(loginEmployer).not.toHaveBeenCalled();
  });

  it("근로자 탭에서도 Enter로 제출된다", async () => {
    localStorage.setItem("jobcard_workplace_code", "DEMO01");
    loginWorker.mockResolvedValue({ token: "t", role: "worker", displayName: "김근로" });
    render(<LoginPage onLogin={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "근로자" }));
    await user.type(screen.getByLabelText("접속 코드"), "1234{Enter}");
    await waitFor(() => expect(loginWorker).toHaveBeenCalledWith("DEMO01", "1234"));
  });

  it("라벨이 눈에 보인다(placeholder가 라벨 노릇을 하지 않음)", () => {
    const { container } = render(<LoginPage onLogin={vi.fn()} />);
    for (const name of ["아이디", "비밀번호"]) {
      const input = screen.getByLabelText(name);
      const label = container.querySelector(`label[for="${input.id}"]`);
      expect(label).toHaveTextContent(name);
      expect(input).not.toHaveAttribute("placeholder");
    }
  });

  it("소개 패널: 로고·소개 문구·단계 카드 예시 3장, 로그인 버튼은 type=submit", () => {
    render(<LoginPage onLogin={vi.fn()} />);
    const intro = screen.getByTestId("login-intro");
    expect(intro).toHaveTextContent("잡카드");
    expect(intro).toHaveTextContent("말로 적으면, 그림 카드 일 안내가 됩니다");
    expect(screen.getByRole("list", { name: "단계 카드 예시" }).querySelectorAll("li")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "로그인" })).toHaveAttribute("type", "submit");
  });

  it("사업주/근로자는 탭으로 고른다(←/→ 키로도 옮김)", async () => {
    render(<LoginPage onLogin={vi.fn()} />);
    const user = userEvent.setup();
    const employer = screen.getByRole("tab", { name: "사업주" });
    expect(employer).toHaveAttribute("aria-selected", "true");
    employer.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "근로자" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "근로자" })).toHaveFocus();
    expect(screen.getByLabelText("접속 코드")).toBeInTheDocument();
  });
});
