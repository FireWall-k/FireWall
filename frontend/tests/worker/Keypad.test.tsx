import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ApiError, NetworkError } from "../../src/apiErrors";
import { FORBIDDEN_PATTERNS } from "../../src/worker/copy";
import EntryScreen from "../../src/worker/EntryScreen";

// /w 번호 넣기(창업자 결정 3): 4자리, 4번째 숫자에서 바로 들어감, [들어가기] 없음,
// 맨 아래 줄 [지우기][0][비우기], 틀리면 칸 비움 + 3번째부터 '선생님께 번호를 물어봐요.'
const loginWorker = vi.fn();
vi.mock("../../src/api", async (orig) => {
  const real = await orig<typeof import("../../src/api")>();
  return { ...real, auth: { ...real.auth, loginWorker: (w: string, c: string) => loginWorker(w, c) } };
});

const onLogin = vi.fn();

function renderEntry() {
  return render(
    <MemoryRouter initialEntries={["/w"]}>
      <Routes>
        <Route path="/w" element={<EntryScreen onLogin={onLogin} />} />
        <Route path="/w/today" element={<p>홈 화면</p>} />
        <Route path="/w/setup" element={<p>연결 화면</p>} />
        <Route path="/login" element={<p>로그인 화면</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

async function press(code: string) {
  for (const d of code) {
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: d }));
    });
  }
}

const wrong = () => new ApiError(401, "사업장 코드 또는 접속 코드가 올바르지 않습니다.");

beforeEach(() => {
  localStorage.clear();
  loginWorker.mockReset();
  onLogin.mockReset();
  localStorage.setItem("jobcard_workplace_code", "DEMO01");
  localStorage.setItem("jobcard_workplace_name", "행복카페");
});

describe("번호 넣기 키패드", () => {
  it("키 배치: 1~9, 맨 아래 [지우기][0][비우기], [들어가기]는 없다", () => {
    renderEntry();
    const keys = screen.getByTestId("keypad").querySelectorAll("button");
    expect([...keys].map((b) => b.textContent)).toEqual(["1", "2", "3", "4", "5", "6", "7", "8", "9", "지우기", "0", "비우기"]);
    expect(screen.queryByRole("button", { name: "들어가기" })).toBeNull();
    expect(screen.getByText("행복카페")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "내 번호를 눌러요" })).toBeInTheDocument();
  });

  it("4번째 숫자를 누르면 바로 들어간다", async () => {
    loginWorker.mockResolvedValue({ token: "t", role: "worker", displayName: "김민수" });
    renderEntry();
    await press("123");
    expect(loginWorker).not.toHaveBeenCalled();
    expect(screen.getByTestId("code-boxes")).toHaveTextContent("123");
    await press("4");
    expect(loginWorker).toHaveBeenCalledWith("DEMO01", "1234");
    await screen.findByText("홈 화면");
    expect(onLogin).toHaveBeenCalledWith({ token: "t", role: "worker", displayName: "김민수" });
  });

  it("[지우기]는 한 자리, [비우기]는 전부", async () => {
    renderEntry();
    await press("12");
    fireEvent.click(screen.getByRole("button", { name: "지우기" }));
    expect(screen.getByTestId("code-boxes")).toHaveTextContent(/^1$/);
    await press("23");
    fireEvent.click(screen.getByRole("button", { name: "비우기" }));
    expect(screen.getByTestId("code-boxes").textContent).toBe("");
  });

  it("틀리면 칸을 비우고 문구, 3번째부터 '선생님께 번호를 물어봐요.'를 덧붙인다(서버 문장은 보이지 않음)", async () => {
    loginWorker.mockRejectedValue(wrong());
    renderEntry();
    await press("1111");
    const notice = await screen.findByTestId("login-notice");
    expect(notice).toHaveTextContent("번호가 맞지 않아요. 다시 눌러 봐요.");
    expect(notice).not.toHaveTextContent("선생님께");
    // 안내는 제목·번호 칸 자리에 대신 나온다(키패드를 밀어내지 않게). 칸은 비워졌고, 첫 숫자를 누르면 다시 보인다.
    expect(screen.queryByTestId("code-boxes")).toBeNull();
    expect(document.body.textContent).not.toContain("접속 코드");
    await press("2");
    expect(screen.queryByTestId("login-notice")).toBeNull();
    expect(screen.getByTestId("code-boxes")).toHaveTextContent(/^2$/);
    await press("222");
    await waitFor(() => expect(loginWorker).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId("login-notice")).not.toHaveTextContent("선생님께");
    await press("3333");
    await waitFor(() => expect(screen.getByTestId("login-notice")).toHaveTextContent("선생님께 번호를 물어봐요."));
    for (const re of FORBIDDEN_PATTERNS) expect(screen.getByTestId("entry-screen").textContent).not.toMatch(re);
  });

  it("들어가는 중에는 키패드를 잠근다", async () => {
    let resolve!: (v: unknown) => void;
    loginWorker.mockReturnValue(new Promise((r) => (resolve = r)));
    renderEntry();
    await press("1234");
    expect(screen.getByText("들어가는 중이에요")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "5" })).toBeDisabled();
    await act(async () => resolve({ token: "t", role: "worker", displayName: "김" }));
  });

  it("시도가 너무 많으면(429) 쉬었다가 다시 누르라고 한다", async () => {
    loginWorker.mockRejectedValue(new ApiError(429, "로그인 시도가 너무 많습니다."));
    renderEntry();
    await press("1234");
    expect(await screen.findByTestId("login-notice")).toHaveTextContent("잠깐 쉬었다가 다시 눌러 봐요.");
  });

  it("인터넷이 안 되면 상태 화면 → [다시 해 보기]로 키패드", async () => {
    loginWorker.mockRejectedValue(new NetworkError());
    renderEntry();
    await press("1234");
    expect(await screen.findByText("인터넷이 안 돼요")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "다시 해 보기" }));
    expect(screen.getByTestId("keypad")).toBeInTheDocument();
  });

  it("연결 안 된 기기는 '연결 안 됨' 화면, 선생님 버튼으로 연결 화면", () => {
    localStorage.clear();
    renderEntry();
    expect(screen.getByText("이 기기를 아직 연결하지 않았어요")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "선생님용: 기기 연결하기" }));
    expect(screen.getByText("연결 화면")).toBeInTheDocument();
  });

  it("예전 긴 번호용 링크는 로그인 화면(근로자 탭)으로", () => {
    renderEntry();
    fireEvent.click(screen.getByRole("button", { name: "선생님용: 긴 번호로 들어가기" }));
    expect(screen.getByText("로그인 화면")).toBeInTheDocument();
  });
});
