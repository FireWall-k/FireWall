import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WorkersPage from "../src/pages/WorkersPage";

const listWorkers = vi.fn();
const createWorker = vi.fn();
const reissueAccessCode = vi.fn();

vi.mock("../src/api", () => ({
  AuthError: class AuthError extends Error {},
  api: {
    listWorkers: () => listWorkers(),
    createWorker: (name: string, code?: string) => createWorker(name, code),
    reissueAccessCode: (id: string) => reissueAccessCode(id),
    deleteWorker: vi.fn(),
  },
}));

beforeEach(() => {
  listWorkers.mockReset().mockResolvedValue([
    { id: "w1", display_name: "김근로", access_code: "1234" },
  ]);
  createWorker.mockReset();
  reissueAccessCode.mockReset();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("WorkersPage — 접속 코드", () => {
  it("코드를 비워 두면 서버가 만든 코드를 보여준다", async () => {
    const user = userEvent.setup();
    createWorker.mockResolvedValue({ id: "w2", display_name: "박알바", access_code: "482913" });
    render(<WorkersPage />);
    await screen.findByText("김근로");

    await user.type(screen.getByLabelText("근로자 이름"), "박알바");
    await user.click(screen.getByRole("button", { name: /추가/ }));

    await waitFor(() => expect(createWorker).toHaveBeenCalledWith("박알바", undefined));
    expect(await screen.findByText(/접속 코드: 482913/)).toBeInTheDocument();
  });

  it("짧은 코드를 직접 입력하면 서버에 보내지 않고 안내한다", async () => {
    const user = userEvent.setup();
    render(<WorkersPage />);
    await screen.findByText("김근로");

    await user.type(screen.getByLabelText("근로자 이름"), "박알바");
    await user.type(screen.getByLabelText("접속 코드"), "5678");
    await user.click(screen.getByRole("button", { name: /추가/ }));

    expect(await screen.findByText(/6~12자리 숫자/, { selector: "[role=alert]" })).toBeInTheDocument();
    expect(createWorker).not.toHaveBeenCalled();
  });

  it("예전 짧은 코드는 경고하고, 새로 만들면 새 코드로 바뀐다", async () => {
    const user = userEvent.setup();
    reissueAccessCode.mockResolvedValue({ id: "w1", display_name: "김근로", access_code: "730514" });
    render(<WorkersPage />);
    expect(await screen.findByText(/짧은 코드예요/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "근로자 김근로 접속 코드 새로 만들기" }));

    await waitFor(() => expect(reissueAccessCode).toHaveBeenCalledWith("w1"));
    expect(await screen.findByText(/새 접속 코드: 730514/)).toBeInTheDocument();
    expect(screen.queryByText(/짧은 코드예요/)).not.toBeInTheDocument();
  });
});
