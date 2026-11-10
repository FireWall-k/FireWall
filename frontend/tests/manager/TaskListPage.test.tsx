import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { ApiError, NetworkError } from "../../src/apiErrors";
import type { TaskCounts, TaskFilter, TaskListOut, TaskSummaryOut } from "../../src/manager/api/types";

// 직무 목록(tasks §3.3·3.4): 겹치는 걸러보기 개수, 보관 이동·되살리기, 복제, 완전히 지우기(보관에서만), 검색, 빈 상태.
// 서버(GET /api/employer/tasks 등)는 아직 없으므로 manager/api/tasks를 통째로 목으로 바꾼다(contract §2.1 모양 그대로).
const listEmployerTasks = vi.fn<(f: TaskFilter, q: string) => Promise<TaskListOut>>();
const archiveTask = vi.fn();
const unarchiveTask = vi.fn();
const duplicateTask = vi.fn();
const deleteTask = vi.fn();

vi.mock("../../src/manager/api/tasks", () => ({
  listEmployerTasks: (f: TaskFilter, q: string) => listEmployerTasks(f, q),
  archiveTask: (id: string) => archiveTask(id),
  unarchiveTask: (id: string) => unarchiveTask(id),
  duplicateTask: (id: string) => duplicateTask(id),
  deleteTask: (id: string) => deleteTask(id),
  renameTask: vi.fn(),
}));

// (2b-1) [다시 보내기]가 여는 보내기 시트의 서버 호출.
const sendCheck = vi.fn();
const recipients = vi.fn();
const send = vi.fn();
const listWorkers = vi.fn();
vi.mock("../../src/manager/api/send", () => ({
  sendApi: {
    sendCheck: (id: string) => sendCheck(id),
    recipients: (id: string) => recipients(id),
    send: (id: string, ids: string[], day: string) => send(id, ids, day),
  },
}));
vi.mock("../../src/manager/api/editor", () => ({ editorApi: { listWorkers: () => listWorkers() } }));

import TaskListPage from "../../src/manager/tasks/TaskListPage";
import { ToastProvider } from "../../src/components/ui";

const NOW_ISO = new Date().toISOString().replace("Z", "");

function row(over: Partial<TaskSummaryOut>): TaskSummaryOut {
  return {
    id: "t1", title: "컵 씻기", state: "draft", needs_check_count: 0, has_unsent_changes: false, step_count: 4,
    cover_url: null, recipients: [], recipients_more: 0, updated_at: NOW_ISO, current_version_no: null,
    ...over,
  };
}

// 확인할 것이 있는 초안(t1)은 '초안'과 '확인 필요' 양쪽에, 보낸 뒤 고쳐 확인할 것이 생긴 직무(t3)는 '보냄'과 '확인 필요'에 센다.
const DRAFT_CHECK = row({ id: "t1", title: "컵 씻기", state: "draft", needs_check_count: 2 });
const DRAFT = row({ id: "t2", title: "앞치마 입기", state: "draft" });
const SENT_EDITED = row({
  id: "t3", title: "상자 옮기기", state: "published", needs_check_count: 1, has_unsent_changes: true, current_version_no: 2,
  recipients: [{ worker_id: "w1", initials: "김" }, { worker_id: "w2", initials: "이" }, { worker_id: "w3", initials: "박" }],
  recipients_more: 2,
});
const ARCHIVED = row({ id: "t9", title: "옛 청소", state: "archived", current_version_no: 1 });
const COUNTS: TaskCounts = { all: 3, draft: 2, needs_check: 2, published: 1, archived: 1 };

function byFilter(f: TaskFilter): TaskSummaryOut[] {
  const live = [DRAFT_CHECK, DRAFT, SENT_EDITED];
  if (f === "draft") return live.filter((r) => r.state === "draft");
  if (f === "published") return live.filter((r) => r.state === "published");
  if (f === "needs_check") return live.filter((r) => r.needs_check_count > 0);
  if (f === "archived") return [ARCHIVED];
  return live;
}

function serve(counts: TaskCounts = COUNTS) {
  listEmployerTasks.mockImplementation(async (f, q) => ({
    items: byFilter(f).filter((r) => !q || r.title.includes(q)),
    counts,
  }));
}

function Where() {
  const l = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output data-testid="where">{l.pathname + l.search}</output>
      {/* 사이드바 '직무' 링크와 브라우저 뒤로 가기 흉내 */}
      <Link to="/m/tasks">사이드바 직무</Link>
      <button type="button" onClick={() => navigate(-1)}>
        뒤로 가기
      </button>
    </>
  );
}

function renderPage(path = "/m/tasks") {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/m/tasks" element={<TaskListPage />} />
          <Route path="/m/tasks/new" element={<p>새 직무 화면</p>} />
          <Route path="/m/tasks/:id" element={<p>편집기 화면</p>} />
        </Routes>
        <Where />
      </MemoryRouter>
    </ToastProvider>,
  );
}

async function openMenu(title: string) {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: `${title} 메뉴` }));
  return { user, menu: screen.getByRole("menu", { name: `${title} 메뉴` }) };
}

beforeEach(() => {
  listEmployerTasks.mockReset();
  archiveTask.mockReset().mockResolvedValue(row({ ...DRAFT, state: "archived" }));
  unarchiveTask.mockReset().mockResolvedValue(DRAFT);
  duplicateTask.mockReset().mockResolvedValue({ id: "t10", title: "앞치마 입기 (복사본)", status: "draft", steps: [] });
  deleteTask.mockReset().mockResolvedValue({ ok: true });
  serve();
});

describe("직무 목록 걸러보기", () => {
  it("탭 5개에 서버가 센 개수를 그대로 보인다(겹침: 초안 2 + 보냄 1 ≠ 전체 3 + 확인 필요 2)", async () => {
    renderPage();
    const tabs = await screen.findByRole("tablist", { name: "직무 걸러보기" });
    await waitFor(() => expect(within(tabs).getByRole("tab", { name: /전체/ })).toHaveTextContent("전체3"));
    expect(within(tabs).getByRole("tab", { name: /초안/ })).toHaveTextContent("초안2");
    expect(within(tabs).getByRole("tab", { name: /확인 필요/ })).toHaveTextContent("확인 필요2");
    expect(within(tabs).getByRole("tab", { name: /보냄/ })).toHaveTextContent("보냄1");
    expect(within(tabs).getByRole("tab", { name: /보관/ })).toHaveTextContent("보관1");
    expect(listEmployerTasks).toHaveBeenCalledWith("all", "");
  });

  it("'확인 필요'를 누르면 초안과 보낸 직무가 함께 나오고, 주소에 ?filter가 남는다", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("앞치마 입기");
    await user.click(screen.getByRole("tab", { name: /확인 필요/ }));
    await waitFor(() => expect(listEmployerTasks).toHaveBeenLastCalledWith("needs_check", ""));
    await waitFor(() => expect(screen.queryByText("앞치마 입기")).not.toBeInTheDocument());
    expect(screen.getByText("컵 씻기")).toBeInTheDocument();
    expect(screen.getByText("상자 옮기기")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /확인 필요/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("where")).toHaveTextContent("/m/tasks?filter=needs_check");
  });

  it("주소의 ?filter=archived로 바로 열 수 있고, 모르는 값은 '전체'로 본다", async () => {
    renderPage("/m/tasks?filter=archived");
    expect(await screen.findByText("옛 청소")).toBeInTheDocument();
    expect(listEmployerTasks).toHaveBeenCalledWith("archived", "");
  });

  it("모르는 걸러보기 값은 '전체'", async () => {
    renderPage("/m/tasks?filter=bogus");
    await screen.findByText("컵 씻기");
    expect(listEmployerTasks).toHaveBeenCalledWith("all", "");
  });

  it("늦게 온 옛 걸러보기 응답이 새 결과를 덮지 않는다", async () => {
    let releaseAll: (v: TaskListOut) => void = () => {};
    listEmployerTasks.mockImplementationOnce(() => new Promise((r) => (releaseAll = r)));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("tab", { name: /보관/ }));
    expect(await screen.findByText("옛 청소")).toBeInTheDocument();
    releaseAll({ items: byFilter("all"), counts: COUNTS });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.getByText("옛 청소")).toBeInTheDocument();
    expect(screen.queryByText("컵 씻기")).not.toBeInTheDocument();
  });
});

describe("직무 목록 행", () => {
  it("열: 대표 그림·제목, 단계 수, 상태 배지, 받은 사람 아바타 3 + '+n', 고친 날", async () => {
    renderPage();
    const title = await screen.findByText("상자 옮기기");
    const tr = title.closest("tr")!;
    const cells = within(tr);
    expect(cells.getByText("4단계")).toBeInTheDocument();
    // 상태는 넓은 화면의 상태 열과 휴대폰의 제목 아래에 같은 것을 그린다(CSS로 하나만 보임)
    expect(cells.getAllByText("보냄").length).toBeGreaterThan(0);
    expect(cells.getAllByText("확인 필요 1").length).toBeGreaterThan(0);
    expect(cells.getAllByText("고친 내용 안 보냄").length).toBeGreaterThan(0);
    expect(cells.getByRole("group", { name: "받은 사람 5명" })).toHaveTextContent("+2");
    // 고친 날은 넓은 화면의 열과 휴대폰 둘째 줄에 같은 것을 그린다(CSS로 하나만 보임)
    expect(cells.getAllByText("방금").length).toBeGreaterThan(0);
    // 확인할 것이 없는 초안에는 배지가 없다
    const plain = within(screen.getByText("앞치마 입기").closest("tr")!);
    expect(plain.queryByText(/확인 필요/)).not.toBeInTheDocument();
    expect(plain.getByText("아직 안 보냄")).toBeInTheDocument();
  });

  it("영어 상태 값(draft·published)이 화면에 보이지 않는다", async () => {
    renderPage();
    await screen.findByText("컵 씻기");
    expect(document.body.textContent).not.toMatch(/draft|published|archived|needs_check/);
  });

  it("(2b-1) 고치기를 누르면 편집기(/m/tasks/:id)로 간다", async () => {
    renderPage();
    const { user, menu } = await openMenu("컵 씻기");
    const edit = within(menu).getByRole("menuitem", { name: "고치기" });
    expect(edit).not.toHaveAttribute("aria-disabled");
    await user.click(edit);
    expect(await screen.findByText("편집기 화면")).toBeInTheDocument();
  });

  it("(2b-1) 제목을 누르면 편집기로 간다", async () => {
    renderPage();
    const link = await screen.findByRole("link", { name: "컵 씻기" });
    expect(link).toHaveAttribute("href", "/m/tasks/t1");
  });

  it("초안에는 [다시 보내기]가 없다", async () => {
    renderPage();
    const { menu } = await openMenu("컵 씻기");
    expect(within(menu).queryByRole("menuitem", { name: /다시 보내기/ })).not.toBeInTheDocument();
    // 보관하지 않은 직무에는 완전히 지우기가 없다(먼저 보관)
    expect(within(menu).queryByRole("menuitem", { name: "완전히 지우기" })).not.toBeInTheDocument();
  });
});

describe("보관·되살리기·복제·완전히 지우기", () => {
  it("보관하기 → archive 호출, 목록을 다시 받고, 토스트의 [실행 취소]로 되살린다", async () => {
    renderPage();
    const { user, menu } = await openMenu("앞치마 입기");
    const callsBefore = listEmployerTasks.mock.calls.length;
    await user.click(within(menu).getByRole("menuitem", { name: "보관하기" }));
    expect(archiveTask).toHaveBeenCalledWith("t2");
    expect(await screen.findByText("'앞치마 입기'를 보관함으로 옮겼어요")).toBeInTheDocument();
    await waitFor(() => expect(listEmployerTasks.mock.calls.length).toBeGreaterThan(callsBefore));
    await user.click(screen.getByRole("button", { name: "실행 취소" }));
    expect(unarchiveTask).toHaveBeenCalledWith("t2");
  });

  it("보관 걸러보기에서 꺼내기 → unarchive 호출", async () => {
    renderPage("/m/tasks?filter=archived");
    const { user, menu } = await openMenu("옛 청소");
    await user.click(within(menu).getByRole("menuitem", { name: "보관함에서 꺼내기" }));
    expect(unarchiveTask).toHaveBeenCalledWith("t9");
    expect(await screen.findByText("'옛 청소'를 보관함에서 꺼냈어요")).toBeInTheDocument();
  });

  it("복제해서 고치기 → duplicate 호출, 새 제목으로 알림, 목록을 다시 받는다", async () => {
    renderPage();
    const { user, menu } = await openMenu("앞치마 입기");
    const callsBefore = listEmployerTasks.mock.calls.length;
    await user.click(within(menu).getByRole("menuitem", { name: "복제해서 고치기" }));
    expect(duplicateTask).toHaveBeenCalledWith("t2");
    expect(await screen.findByText("'앞치마 입기 (복사본)'을 새 초안으로 만들었어요")).toBeInTheDocument();
    await waitFor(() => expect(listEmployerTasks.mock.calls.length).toBeGreaterThan(callsBefore));
  });

  it("완전히 지우기는 보관 걸러보기에서만, 지워지는 것 목록을 보이는 위험 창으로 확인받는다", async () => {
    renderPage("/m/tasks?filter=archived");
    const { user, menu } = await openMenu("옛 청소");
    await user.click(within(menu).getByRole("menuitem", { name: "완전히 지우기" }));
    const dialog = screen.getByRole("alertdialog", { name: "'옛 청소'를 완전히 지울까요?" });
    expect(within(dialog).getByText("수행 기록과 도움 요청 기록")).toBeInTheDocument();
    // 처음 초점은 [취소](Enter를 잘못 눌러 지우지 않게)
    expect(within(dialog).getByRole("button", { name: "취소" })).toHaveFocus();
    expect(deleteTask).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "완전히 지우기" }));
    expect(deleteTask).toHaveBeenCalledWith("t9");
    expect(await screen.findByText("'옛 청소'를 완전히 지웠어요")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("서버가 막으면(409) 서버 문장을 오류 토스트로 보이고 저절로 닫지 않는다", async () => {
    deleteTask.mockRejectedValue(new ApiError(409, "보관함으로 옮긴 직무만 완전히 지울 수 있어요."));
    renderPage("/m/tasks?filter=archived");
    const { user, menu } = await openMenu("옛 청소");
    await user.click(within(menu).getByRole("menuitem", { name: "완전히 지우기" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "완전히 지우기" }));
    expect(await screen.findByText("보관함으로 옮긴 직무만 완전히 지울 수 있어요.")).toBeInTheDocument();
  });

  it("보관하지 못하면(연결 끊김) 영어 없이 다음 할 일을 알린다", async () => {
    archiveTask.mockRejectedValue(new NetworkError());
    renderPage();
    const { user, menu } = await openMenu("앞치마 입기");
    await user.click(within(menu).getByRole("menuitem", { name: "보관하기" }));
    expect(await screen.findByText(/서버에 닿지 못했어요/)).toBeInTheDocument();
  });
});

describe("검색·빈 상태·오류", () => {
  it("제목으로 찾기: 적기를 멈추면 q로 다시 받고, 결과가 없으면 [검색 지우기]", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("컵 씻기");
    await user.type(screen.getByLabelText("제목으로 찾기"), "상자");
    await waitFor(() => expect(listEmployerTasks).toHaveBeenLastCalledWith("all", "상자"));
    await waitFor(() => expect(screen.queryByText("컵 씻기")).not.toBeInTheDocument());
    expect(screen.getByText("상자 옮기기")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("q=");

    await user.clear(screen.getByLabelText("제목으로 찾기"));
    await user.type(screen.getByLabelText("제목으로 찾기"), "없는말");
    expect(await screen.findByText("'없는말'로 찾은 직무가 없어요")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "검색 지우기" })[0]);
    await waitFor(() => expect(listEmployerTasks).toHaveBeenLastCalledWith("all", ""));
  });

  it("직무가 하나도 없으면 [새 직무 만들기]·[예시로 만들어 보기](?example=1)", async () => {
    listEmployerTasks.mockResolvedValue({ items: [], counts: { all: 0, draft: 0, needs_check: 0, published: 0, archived: 0 } });
    renderPage();
    expect(await screen.findByText("아직 만든 직무가 없어요")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "새 직무 만들기" })).toHaveAttribute("href", "/m/tasks/new");
    // 새 직무 화면(옛 ManagerPage)이 ?example=1을 읽어 예시 지시문을 채운다.
    expect(screen.getByRole("link", { name: "예시로 만들어 보기" })).toHaveAttribute("href", "/m/tasks/new?example=1");
  });

  it("걸러보기에 맞는 직무가 없으면 그 걸러보기 이름으로 알린다", async () => {
    listEmployerTasks.mockResolvedValue({ items: [], counts: { ...COUNTS, published: 0 } });
    renderPage("/m/tasks?filter=published");
    expect(await screen.findByText("'보냄'에 해당하는 직무가 없어요")).toBeInTheDocument();
  });

  it("목록을 못 받으면 오류 칸과 [다시 시도]", async () => {
    listEmployerTasks.mockRejectedValueOnce(new NetworkError());
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("불러오지 못했어요");
    await user.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(await screen.findByText("컵 씻기")).toBeInTheDocument();
  });
});

describe("검색칸과 주소의 q가 함께 간다", () => {
  it("사이드바 '직무'(/m/tasks)로 가면 검색이 풀리고 검색어가 되살아나지 않는다", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("컵 씻기");
    await user.type(screen.getByLabelText("제목으로 찾기"), "컵");
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("q="));
    await user.click(screen.getByRole("link", { name: "사이드바 직무" }));
    expect(screen.getByLabelText("제목으로 찾기")).toHaveValue("");
    // 잠깐 멈춘 뒤에도 옛 검색어가 주소에 다시 쓰이지 않는다
    await new Promise((r) => setTimeout(r, 600));
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/m\/tasks$/);
    await waitFor(() => expect(listEmployerTasks).toHaveBeenLastCalledWith("all", ""));
  });

  it("뒤로 가기를 하면 주소의 q와 검색칸이 함께 돌아온다", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("컵 씻기");
    await user.type(screen.getByLabelText("제목으로 찾기"), "컵");
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("q="));
    await user.click(screen.getByRole("tab", { name: /초안/ })); // 기록 하나 쌓기(?q=컵&filter=draft)
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("filter=draft"));
    await user.click(screen.getAllByRole("button", { name: "검색 지우기" })[0]);
    expect(screen.getByLabelText("제목으로 찾기")).toHaveValue("");
    await user.click(screen.getByRole("button", { name: "뒤로 가기" }));
    expect(screen.getByTestId("where")).toHaveTextContent("q=");
    expect(screen.getByLabelText("제목으로 찾기")).toHaveValue("컵");
    await new Promise((r) => setTimeout(r, 600));
    expect(screen.getByTestId("where")).toHaveTextContent("q=");
    expect(screen.getByLabelText("제목으로 찾기")).toHaveValue("컵");
  });
});

describe("행이 사라진 뒤 키보드 초점(WCAG 2.4.3)", () => {
  it("보관하기로 행이 사라지면 그 자리 다음 행의 … 단추로 초점이 간다", async () => {
    renderPage();
    const { user, menu } = await openMenu("앞치마 입기");
    // 보관한 뒤의 목록에서는 t2가 빠진다
    archiveTask.mockImplementation(async () => {
      listEmployerTasks.mockImplementation(async (f) => ({
        items: byFilter(f).filter((r) => r.id !== "t2"),
        counts: COUNTS,
      }));
      return row({ ...DRAFT, state: "archived" });
    });
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(within(menu).getByRole("menuitem", { name: "보관하기" })).toHaveFocus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(screen.queryByRole("button", { name: "앞치마 입기 메뉴" })).not.toBeInTheDocument());
    await waitFor(() => expect(document.activeElement).toHaveAttribute("data-task-menu"));
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toHaveAccessibleName("상자 옮기기 메뉴");
  });

  it("[실행 취소]로 되살리면 그 직무의 … 단추로 초점이 돌아간다", async () => {
    renderPage();
    const { user, menu } = await openMenu("앞치마 입기");
    await user.click(within(menu).getByRole("menuitem", { name: "보관하기" }));
    await user.click(await screen.findByRole("button", { name: "실행 취소" }));
    expect(unarchiveTask).toHaveBeenCalledWith("t2");
    await waitFor(() => expect(screen.getByRole("button", { name: "앞치마 입기 메뉴" })).toHaveFocus());
  });

  it("[실행 취소]가 서버 오류로 실패해도 초점이 body로 빠지지 않고 행의 … 단추로 간다", async () => {
    renderPage();
    archiveTask.mockImplementation(async () => {
      listEmployerTasks.mockImplementation(async (f) => ({ items: byFilter(f).filter((r) => r.id !== "t2"), counts: COUNTS }));
      return row({ ...DRAFT, state: "archived" });
    });
    unarchiveTask.mockRejectedValue(new ApiError(500, "잠시 뒤에 다시 해 주세요"));
    const { user, menu } = await openMenu("앞치마 입기");
    await user.click(within(menu).getByRole("menuitem", { name: "보관하기" }));
    const undo = await screen.findByRole("button", { name: "실행 취소" });
    undo.focus();
    const callsBefore = listEmployerTasks.mock.calls.length;
    await user.keyboard("{Enter}");
    expect(unarchiveTask).toHaveBeenCalledWith("t2");
    await waitFor(() => expect(listEmployerTasks.mock.calls.length).toBeGreaterThan(callsBefore));
    await waitFor(() => expect(document.activeElement).toHaveAttribute("data-task-menu"));
    expect(document.activeElement).not.toBe(document.body);
  });

  it("완전히 지워 목록이 비면 목록 칸(tabpanel)으로 초점이 간다", async () => {
    renderPage("/m/tasks?filter=archived");
    const { user, menu } = await openMenu("옛 청소");
    deleteTask.mockImplementation(async () => {
      listEmployerTasks.mockResolvedValue({ items: [], counts: { ...COUNTS, archived: 0 } });
      return { ok: true };
    });
    await user.click(within(menu).getByRole("menuitem", { name: "완전히 지우기" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "완전히 지우기" }));
    await waitFor(() => expect(screen.getByRole("tabpanel")).toHaveFocus());
  });

  it("검색칸의 [X]·빈 상태의 [검색 지우기]를 누르면 초점이 검색칸으로 간다", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("컵 씻기");
    const input = screen.getByLabelText("제목으로 찾기");
    await user.type(input, "없는말");
    expect(await screen.findByText("'없는말'로 찾은 직무가 없어요")).toBeInTheDocument();
    const clearButtons = screen.getAllByRole("button", { name: "검색 지우기" });
    await user.click(clearButtons[clearButtons.length - 1]); // 빈 상태의 단추
    expect(input).toHaveFocus();
    await user.type(input, "컵");
    await user.click(screen.getByRole("button", { name: "검색 지우기" })); // 검색칸 옆 [X]
    expect(input).toHaveFocus();
    expect(input).toHaveValue("");
  });
});

describe("행동 뒤 다시 받기는 지금 걸러보기·검색어로(2회차 검증)", () => {
  it("보관 → '보관' 탭으로 옮김 → [실행 취소]: 보관 탭 목록이 보이고 스켈레톤에 멈추지 않는다", async () => {
    renderPage();
    const { user, menu } = await openMenu("앞치마 입기");
    await user.click(within(menu).getByRole("menuitem", { name: "보관하기" }));
    await screen.findByText("'앞치마 입기'를 보관함으로 옮겼어요");
    await user.click(screen.getByRole("tab", { name: /보관/ }));
    expect(await screen.findByText("옛 청소")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "실행 취소" }));
    expect(unarchiveTask).toHaveBeenCalledWith("t2");
    await waitFor(() => expect(listEmployerTasks).toHaveBeenLastCalledWith("archived", ""));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.getByText("옛 청소")).toBeInTheDocument();
    expect(screen.getByRole("table")).not.toHaveAttribute("aria-busy");
    expect(screen.getByTestId("where")).toHaveTextContent("/m/tasks?filter=archived");
  });

  it("보관 요청이 끝나기 전에 '초안' 탭을 누르면, 끝난 뒤에도 초안 목록이 보인다", async () => {
    let finish: (v: TaskSummaryOut) => void = () => {};
    archiveTask.mockImplementation(() => new Promise((r) => (finish = r)));
    renderPage();
    const { user, menu } = await openMenu("앞치마 입기");
    await user.click(within(menu).getByRole("menuitem", { name: "보관하기" }));
    await user.click(screen.getByRole("tab", { name: /초안/ }));
    await waitFor(() => expect(listEmployerTasks).toHaveBeenLastCalledWith("draft", ""));
    finish(row({ ...DRAFT, state: "archived" }));
    await screen.findByText("'앞치마 입기'를 보관함으로 옮겼어요");
    await waitFor(() => expect(listEmployerTasks).toHaveBeenLastCalledWith("draft", ""));
    expect(await screen.findByText("컵 씻기")).toBeInTheDocument();
    expect(screen.queryByText("상자 옮기기")).not.toBeInTheDocument();
    expect(screen.getByRole("table")).not.toHaveAttribute("aria-busy");
  });
});

describe("결과 알림(WCAG 4.1.3)과 휴대폰 행 둘째 줄", () => {
  it("처음 열 때는 조용하고, 걸러보기·검색을 바꾸면 결과 수나 '맞는 직무가 없어요'를 알린다", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("컵 씻기");
    const live = screen.getByTestId("task-result-status");
    expect(live).toHaveAttribute("role", "status");
    expect(live).toHaveTextContent("");
    await user.click(screen.getByRole("tab", { name: /확인 필요/ }));
    await waitFor(() => expect(live).toHaveTextContent("직무가 2개 있어요"));
    await user.type(screen.getByLabelText("제목으로 찾기"), "없는직무");
    await waitFor(() => expect(live).toHaveTextContent("맞는 직무가 없어요"));
  });

  it("탭을 바꾼 뒤 보관하면 결과 수 알림은 그대로다(같은 걸러보기 안의 다시 받기는 알리지 않음 — 토스트와 두 번 읽히지 않게)", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("컵 씻기");
    const live = screen.getByTestId("task-result-status");
    await user.click(screen.getByRole("tab", { name: /초안/ }));
    await waitFor(() => expect(live).toHaveTextContent("직무가 2개 있어요"));
    await user.click(screen.getByRole("tab", { name: /전체/ }));
    await waitFor(() => expect(live).toHaveTextContent("직무가 3개 있어요"));
    archiveTask.mockImplementation(async () => {
      listEmployerTasks.mockImplementation(async (f) => ({ items: byFilter(f).filter((r) => r.id !== "t2"), counts: COUNTS }));
      return row({ ...DRAFT, state: "archived" });
    });
    const { menu } = await openMenu("앞치마 입기");
    await user.click(within(menu).getByRole("menuitem", { name: "보관하기" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "앞치마 입기 메뉴" })).not.toBeInTheDocument());
    expect(live).toHaveTextContent("직무가 3개 있어요");
  });

  it("행마다 '4단계 · 고친 날 · 받은 사람 n명'(없으면 '아직 안 보냄') 줄이 있고 md 이상에서는 숨는다", async () => {
    renderPage();
    await screen.findByText("상자 옮기기");
    const metas = screen.getAllByTestId("task-row-meta");
    expect(metas).toHaveLength(3);
    for (const m of metas) expect(m).toHaveClass("md:hidden");
    const sent = metas.find((m) => m.textContent?.includes("받은 사람 5명"));
    expect(sent).toBeDefined();
    expect(sent).toHaveTextContent(/^4단계 · .+ · 받은 사람 5명$/);
    expect(metas.some((m) => m.textContent?.endsWith("아직 안 보냄"))).toBe(true);
  });

  it("직무가 하나도 없으면 표 머리 줄(정렬 단추)을 숨긴다", async () => {
    listEmployerTasks.mockResolvedValue({ items: [], counts: { all: 0, draft: 0, needs_check: 0, published: 0, archived: 0 } });
    renderPage();
    await screen.findByText("아직 만든 직무가 없어요");
    expect(screen.getByRole("table").querySelector("thead")).toHaveClass("hidden");
  });
});

describe("(2b-1) 다시 보내기 — 클릭 3번", () => {
  const SENT = row({
    id: "t4", title: "바닥 청소", state: "published", current_version_no: 1,
    recipients: [{ worker_id: "w1", initials: "김" }],
  });
  beforeEach(() => {
    listEmployerTasks.mockImplementation(async () => ({ items: [SENT, SENT_EDITED], counts: COUNTS }));
    sendCheck.mockResolvedValue({
      ok: true,
      blocking: [
        { code: "no_picture", done: 4, total: 4, step_ids: [] },
        { code: "unconfirmed_auto", done: 4, total: 4, step_ids: [] },
        { code: "unreviewed_split", done: 0, total: 0, step_ids: [] },
      ],
      warnings: [],
    });
    recipients.mockResolvedValue({
      last_batch_worker_ids: ["w1"], all_ever_worker_ids: ["w1"], workplace_last_batch_worker_ids: ["w1"],
      today_status: { w1: "none", w2: "none" },
    });
    listWorkers.mockResolvedValue([
      { id: "w1", display_name: "김민지", access_code_hint: "34", access_code_length: 4, access_code: "1234" },
      { id: "w2", display_name: "이서준", access_code_hint: "78", access_code_length: 4, access_code: "5678" },
    ]);
    send.mockResolvedValue({ version_no: 1, version_created: false, day: "2026-11-10", results: [{ worker_id: "w1", display_name: "김민지", outcome: "created" }] });
  });

  it("… → [다시 보내기] → [1명에게 보내기]: 지난번 받은 사람이 미리 체크되어 있고 접속 코드는 시트에 없다", async () => {
    renderPage();
    const { user, menu } = await openMenu("바닥 청소");
    await user.click(within(menu).getByRole("menuitem", { name: "다시 보내기" }));
    const sheet = await screen.findByRole("dialog", { name: "보내기 전에 확인해요" });
    expect(await within(sheet).findByRole("checkbox", { name: /김민지 님/ })).toBeChecked();
    expect(within(sheet).getByRole("checkbox", { name: /이서준 님/ })).not.toBeChecked();
    expect(within(sheet).getByText("지난번 받은 사람을 골라 두었어요")).toBeInTheDocument();
    expect(sheet.textContent).not.toMatch(/1234|5678/);
    await user.click(within(sheet).getByRole("button", { name: "1명에게 보내기" }));
    await waitFor(() => expect(send).toHaveBeenCalledWith("t4", ["w1"], "today"));
    expect(await screen.findByText("1명에게 보냈어요")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "현황 보기" })).toBeInTheDocument();
  });

  it("확인할 것이 남은 직무는 '확인할 것 n개가 남았어요'를 보이고, 누르면 편집기의 첫 확인 단계로 간다", async () => {
    renderPage();
    const { user, menu } = await openMenu("상자 옮기기");
    const item = within(menu).getByRole("menuitem", { name: /다시 보내기/ });
    expect(item).toHaveTextContent("확인할 것 1개가 남았어요");
    await user.click(item);
    expect(await screen.findByText("편집기 화면")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/m/tasks/t3?review=1");
    expect(sendCheck).not.toHaveBeenCalled();
  });
});
