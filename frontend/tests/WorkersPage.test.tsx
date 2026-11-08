import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WorkersPage from "../src/pages/WorkersPage";

const listWorkers = vi.fn();
const createWorker = vi.fn();
const reissueAccessCode = vi.fn();
const workplace = vi.fn();
const deleteWorker = vi.fn();
const exportWorker = vi.fn();
const updateWorker = vi.fn();
const grantConsent = vi.fn();
const listConsents = vi.fn();
const revokeConsent = vi.fn();

vi.mock("../src/api", () => ({
  AuthError: class AuthError extends Error {},
  api: {
    listWorkers: () => listWorkers(),
    createWorker: (name: string, code?: string) => createWorker(name, code),
    reissueAccessCode: (id: string) => reissueAccessCode(id),
    deleteWorker: (id: string) => deleteWorker(id),
    workplace: () => workplace(),
    exportWorker: (id: string) => exportWorker(id),
    updateWorker: (id: string, patch: unknown) => updateWorker(id, patch),
    grantConsent: (id: string, type: string, subject: string) => grantConsent(id, type, subject),
    listConsents: (id: string) => listConsents(id),
    revokeConsent: (wid: string, cid: string) => revokeConsent(wid, cid),
  },
}));

beforeEach(() => {
  listWorkers.mockReset().mockResolvedValue([
    { id: "w1", display_name: "김근로", access_code_hint: "34", access_code_length: 4 },
  ]);
  workplace.mockReset().mockResolvedValue({ workplace_code: "DEMO01", org_name: "잇다" });
  createWorker.mockReset();
  reissueAccessCode.mockReset();
  deleteWorker.mockReset().mockResolvedValue({ ok: true });
  exportWorker.mockReset();
  updateWorker.mockReset();
  grantConsent.mockReset();
  listConsents.mockReset();
  revokeConsent.mockReset();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("WorkersPage — 접속 코드", () => {
  it("코드를 비워 두면 서버가 만든 코드를 보여준다", async () => {
    const user = userEvent.setup();
    createWorker.mockResolvedValue({
      id: "w2", display_name: "박알바", access_code: "482913", access_code_hint: "13", access_code_length: 6,
    });
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
    await user.type(screen.getByLabelText("접속 코드"), "56");
    await user.click(screen.getByRole("button", { name: /추가/ }));

    expect(await screen.findByText(/4~12자리 숫자/, { selector: "[role=alert]" })).toBeInTheDocument();
    expect(createWorker).not.toHaveBeenCalled();
  });

  it("4자리 코드는 그대로 받아 준다(요청에 따라 완화된 최소 길이)", async () => {
    const user = userEvent.setup();
    createWorker.mockResolvedValue({
      id: "w3", display_name: "이근무", access_code: "5678", access_code_hint: "78", access_code_length: 4,
    });
    render(<WorkersPage />);
    await screen.findByText("김근로");

    await user.type(screen.getByLabelText("근로자 이름"), "이근무");
    await user.type(screen.getByLabelText("접속 코드"), "5678");
    await user.click(screen.getByRole("button", { name: /추가/ }));

    await waitFor(() => expect(createWorker).toHaveBeenCalledWith("이근무", "5678"));
  });

  // 창업자 결정 3: 4자리가 기본 번호다. 4자리 코드를 '짧은 코드'로 경고하지 않는다(대입은 서버 시도 제한이 막는다).
  it("4자리 코드는 경고하지 않고, 새로 만들면 새 코드로 바뀐다", async () => {
    const user = userEvent.setup();
    reissueAccessCode.mockResolvedValue({
      id: "w1", display_name: "김근로", access_code: "7305", access_code_hint: "05", access_code_length: 4,
    });
    render(<WorkersPage />);
    await screen.findByText("김근로");
    expect(screen.queryByText(/짧은 코드예요/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "근로자 김근로 접속 코드 새로 만들기" }));

    await waitFor(() => expect(reissueAccessCode).toHaveBeenCalledWith("w1"));
    expect(await screen.findByText(/새 접속 코드: 7305/)).toBeInTheDocument();
  });

  // 2026-11-07 사용자 요청: 사업주 화면에서는 접속 코드를 가리지 않고 전체를 보여 준다(근로자에게 다시 알려 줄 수 있게).
  it("사업장 코드와 근로자의 전체 접속 코드를 보여 준다", async () => {
    listWorkers.mockResolvedValue([
      { id: "w1", display_name: "김근로", access_code: "1234", access_code_hint: "34", access_code_length: 4 },
    ]);
    render(<WorkersPage />);
    expect(await screen.findByText("DEMO01")).toBeInTheDocument();
    const list = await screen.findByRole("list");
    await waitFor(() => expect(list).toHaveTextContent("접속 코드 1234"));
    expect(list).not.toHaveTextContent("••");
  });

  it("서버도 전체 코드를 모르는 예전 근로자는 뒤 2자리와 함께 보이는 방법을 안내한다", async () => {
    render(<WorkersPage />);
    const list = await screen.findByRole("list");
    await waitFor(() => expect(list).toHaveTextContent("••34"));
    expect(list).toHaveTextContent(/한 번 로그인하거나 코드를 새로 만들면 전체 번호가 보여요/);
  });

  it("새로 만든 근로자는 목록에도 전체 코드가 보인다", async () => {
    const user = userEvent.setup();
    createWorker.mockResolvedValue({
      id: "w2", display_name: "박알바", access_code: "482913", access_code_hint: "13", access_code_length: 6,
    });
    render(<WorkersPage />);
    await screen.findByText("김근로");
    await user.type(screen.getByLabelText("근로자 이름"), "박알바");
    await user.click(screen.getByRole("button", { name: /추가/ }));

    expect(await screen.findByRole("status")).toHaveTextContent("482913");
    expect(screen.getByRole("list")).toHaveTextContent("482913");
  });
});

describe("WorkersPage — 근로자 추가 결과 위치", () => {
  // 화면 맨 위 배너에 띄우면 아래쪽 추가 폼을 보고 있는 사업주가 오류를 못 봤다(사용자 피드백).
  const addSection = () => screen.getByRole("heading", { name: "근로자 추가" }).closest("section") as HTMLElement;

  it("서버가 거절한 오류는 근로자 추가 폼 안(바로 아래)에 보인다", async () => {
    const user = userEvent.setup();
    createWorker.mockRejectedValue(new Error("이미 사용 중인 접속 코드입니다. 다른 코드를 입력해 주세요."));
    render(<WorkersPage />);
    await screen.findByText("김근로");
    await user.type(screen.getByLabelText("근로자 이름"), "박알바");
    await user.type(screen.getByLabelText("접속 코드"), "1234");
    await user.click(screen.getByRole("button", { name: /추가/ }));

    const alert = await screen.findByText(/이미 사용 중인 접속 코드/);
    expect(addSection()).toContainElement(alert);
  });

  it("입력 검사 오류와 추가 성공 안내도 폼 안에 보인다", async () => {
    const user = userEvent.setup();
    render(<WorkersPage />);
    await screen.findByText("김근로");
    await user.type(screen.getByLabelText("근로자 이름"), "박알바");
    await user.type(screen.getByLabelText("접속 코드"), "56");
    await user.click(screen.getByRole("button", { name: /추가/ }));
    expect(addSection()).toContainElement(await screen.findByText(/4~12자리 숫자로 정해/));

    createWorker.mockResolvedValue({
      id: "w2", display_name: "박알바", access_code: "482913", access_code_hint: "13", access_code_length: 6,
    });
    await user.clear(screen.getByLabelText("접속 코드"));
    await user.click(screen.getByRole("button", { name: /추가/ }));
    expect(addSection()).toContainElement(await screen.findByText(/접속 코드: 482913/));
    expect(screen.queryByText(/4~12자리 숫자로 정해/)).not.toBeInTheDocument();
  });
});

describe("WorkersPage — 개인정보(동의·메모·내보내기·삭제)", () => {
  it("내보내기는 서버 JSON을 파일로 저장하고 파일 이름에 근로자 이름을 넣지 않는다", async () => {
    const user = userEvent.setup();
    exportWorker.mockResolvedValue({ worker: { id: "w1", display_name: "김근로" } });
    const createObjectURL = vi.fn(() => "blob:x");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const clicked: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.download);
    });
    render(<WorkersPage />);
    await user.click(await screen.findByRole("button", { name: "근로자 김근로 데이터 내보내기" }));

    await waitFor(() => expect(exportWorker).toHaveBeenCalledWith("w1"));
    expect(createObjectURL).toHaveBeenCalled();
    expect(clicked).toEqual(["worker-w1.json"]);
    click.mockRestore();
  });

  it("삭제는 확인을 받은 뒤에만 서버에 요청하고 목록에서 뺀다", async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    render(<WorkersPage />);
    const del = await screen.findByRole("button", { name: "근로자 김근로 삭제" });

    await user.click(del);
    expect(deleteWorker).not.toHaveBeenCalled();
    expect(confirm.mock.calls[0][0]).toMatch(/되돌릴 수 없어요/);

    await user.click(del);
    await waitFor(() => expect(deleteWorker).toHaveBeenCalledWith("w1"));
    await waitFor(() => expect(screen.queryByText("김근로")).not.toBeInTheDocument());
  });

  it("삭제 확인 문구는 직무 문장 속 이름이 남는다고 알리고, 삭제 뒤 이름이 남은 직무를 보여 준다", async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    deleteWorker.mockResolvedValue({
      ok: true, wal_checkpointed: true, name_mentions: [{ task_id: "t1", title: "김근로 포장 직무" }],
    });
    render(<WorkersPage />);
    await user.click(await screen.findByRole("button", { name: "근로자 김근로 삭제" }));

    expect(confirm.mock.calls[0][0]).toMatch(/직무 문장에 적은 이름은 지워지지 않아요/);
    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent("직무 1개에 남아 있어요");
    expect(notice).toHaveTextContent("김근로 포장 직무");
  });

  it("일반 낱말과 같은 이름이면 경고를 보여 준다", async () => {
    listWorkers.mockResolvedValue([
      { id: "w9", display_name: "하나", access_code_hint: "34", access_code_length: 6, name_ambiguous: true },
    ]);
    render(<WorkersPage />);
    expect(await screen.findByText(/이름이 일반 낱말과 같아요/)).toBeInTheDocument();
  });

  it("보호자 동의를 기록하면 AI 처리 동의가 '기록됨'으로 바뀐다", async () => {
    const user = userEvent.setup();
    grantConsent.mockResolvedValue({ id: "c1" });
    render(<WorkersPage />);
    expect(await screen.findByText("없음")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "근로자 김근로 보호자 동의 기록" }));

    await waitFor(() => expect(grantConsent).toHaveBeenCalledWith("w1", "ai_processing", "guardian"));
    expect(await screen.findByText("기록됨")).toBeInTheDocument();
  });

  it("개인정보 수집·이용 동의도 화면에서 기록한다", async () => {
    const user = userEvent.setup();
    grantConsent.mockResolvedValue({ id: "c1" });
    render(<WorkersPage />);
    expect(await screen.findByText("미기록")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "근로자 김근로 당사자 개인정보 수집·이용 동의 기록" }));

    await waitFor(() => expect(grantConsent).toHaveBeenCalledWith("w1", "personal_info", "self"));
    expect(await screen.findByText("받음")).toBeInTheDocument();
    // AI 처리 동의는 따로다 — 수집·이용 동의만으로 AI 전송이 켜지지 않는다.
    expect(screen.getByText("없음")).toBeInTheDocument();
  });

  it("개인정보 동의 철회는 살아 있는 수집·이용 동의만 철회한다", async () => {
    const user = userEvent.setup();
    listWorkers.mockResolvedValue([
      { id: "w1", display_name: "김근로", access_code_hint: "34", access_code_length: 6,
        ai_consent: true, personal_info_consent: true },
    ]);
    listConsents.mockResolvedValue([
      { id: "c-pi", consent_type: "personal_info", revoked_at: null },
      { id: "c-ai", consent_type: "ai_processing", revoked_at: null },
    ]);
    revokeConsent.mockResolvedValue({});
    render(<WorkersPage />);
    await user.click(await screen.findByRole("button", { name: "근로자 김근로 개인정보 수집·이용 동의 철회 기록" }));

    await waitFor(() => expect(revokeConsent).toHaveBeenCalledTimes(1));
    expect(revokeConsent).toHaveBeenCalledWith("w1", "c-pi");
    expect(await screen.findByText("미기록")).toBeInTheDocument();
    expect(screen.getByText("기록됨")).toBeInTheDocument();
  });

  it("동의 철회는 살아 있는 AI 처리 동의만 철회한다", async () => {
    const user = userEvent.setup();
    listWorkers.mockResolvedValue([
      { id: "w1", display_name: "김근로", access_code_hint: "34", access_code_length: 6, ai_consent: true },
    ]);
    listConsents.mockResolvedValue([
      { id: "c-old", consent_type: "ai_processing", revoked_at: "2026-01-01T00:00:00" },
      { id: "c-pi", consent_type: "personal_info", revoked_at: null },
      { id: "c-ai", consent_type: "ai_processing", revoked_at: null },
    ]);
    revokeConsent.mockResolvedValue({});
    render(<WorkersPage />);
    await user.click(await screen.findByRole("button", { name: "근로자 김근로 AI 처리 동의 철회 기록" }));

    await waitFor(() => expect(revokeConsent).toHaveBeenCalledTimes(1));
    expect(revokeConsent).toHaveBeenCalledWith("w1", "c-ai");
    expect(await screen.findByText("없음")).toBeInTheDocument();
  });

  it("'소리 자동 재생'은 기본 켬이고, 끄면 a11y_prefs.autoplay_sound만 서버에 보낸다(창업자 결정 4)", async () => {
    const user = userEvent.setup();
    updateWorker.mockResolvedValue({
      id: "w1", display_name: "김근로", access_code_hint: "34", access_code_length: 4,
      a11y_prefs: { font_size: "normal", autoplay_sound: false, tts_rate: 0.9, sfx: true, vibration: false, praise: "normal", hand: "right", contrast: "normal" },
    });
    render(<WorkersPage />);
    const sw = await screen.findByRole("switch", { name: "근로자 김근로 소리 자동 재생" });
    expect(sw).toBeChecked();

    await user.click(sw);

    await waitFor(() => expect(updateWorker).toHaveBeenCalledWith("w1", { a11y_prefs: { autoplay_sound: false } }));
    await waitFor(() => expect(screen.getByRole("switch", { name: "근로자 김근로 소리 자동 재생" })).not.toBeChecked());
  });

  it("'AI 코칭에 메모 사용'은 기본 꺼짐이고, 켜면 서버에 저장한다", async () => {
    const user = userEvent.setup();
    updateWorker.mockResolvedValue({
      id: "w1", display_name: "김근로", access_code_hint: "34", access_code_length: 4, ai_note_allowed: true,
    });
    render(<WorkersPage />);
    const box = await screen.findByRole("checkbox", { name: "근로자 김근로 AI 코칭에 메모 사용" });
    expect(box).not.toBeChecked();

    await user.click(box);

    await waitFor(() => expect(updateWorker).toHaveBeenCalledWith("w1", { ai_note_allowed: true }));
    expect(await screen.findByText(/동의가 기록되기 전에는 메모를 AI에 보내지 않아요/)).toBeInTheDocument();
  });

  it("메모는 저장 버튼을 눌러야 서버로 간다", async () => {
    const user = userEvent.setup();
    updateWorker.mockResolvedValue({
      id: "w1", display_name: "김근로", access_code_hint: "34", access_code_length: 4, note: "그림 선호",
    });
    render(<WorkersPage />);
    await user.type(await screen.findByLabelText("근로자 김근로 메모"), "그림 선호");
    expect(updateWorker).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "근로자 김근로 메모 저장" }));
    await waitFor(() => expect(updateWorker).toHaveBeenCalledWith("w1", { note: "그림 선호" }));
  });
});
