import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { EmployerHelp } from "../../src/api";

const employerHelp = vi.fn();

vi.mock("../../src/api", () => ({
  api: {
    employerHelp: (s?: string) => employerHelp(s),
    ackHelp: vi.fn().mockResolvedValue({}),
    resolveHelp: vi.fn().mockResolvedValue({}),
  },
}));

import AppShell from "../../src/manager/shell/AppShell";
import { HELP_FEED_POLL_MS } from "../../src/manager/shell/useHelpFeed";
import { crumbsFor, isFullWidth } from "../../src/manager/shell/navItems";

function help(over: Partial<EmployerHelp> = {}): EmployerHelp {
  return {
    id: "h1", state: "open", created_at: new Date().toISOString().replace("Z", ""), acknowledged_at: null,
    worker_id: "w1", worker_name: "김민지", assignment_id: "a1", task_id: "t1", task_title: "컵 씻기",
    step_id: "s3", step_order: 3, step_sentence: "컵을 물에 넣어요", step_symbol_url: null,
    ...over,
  };
}

function renderShell(path = "/m/tasks", onLogout = vi.fn()) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/m/*"
          element={
            <AppShell displayName="테스트사장" onLogout={onLogout}>
              <Routes>
                <Route index element={<p>홈 본문</p>} />
                <Route path="tasks" element={<p>직무 본문</p>} />
                <Route path="tasks/new" element={<p>새 직무 본문</p>} />
                <Route path="settings" element={<p>설정 본문</p>} />
              </Routes>
            </AppShell>
          }
        />
        <Route path="/m/login" element={<p>로그인 화면</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  employerHelp.mockReset().mockResolvedValue([]);
});
afterEach(() => {
  vi.useRealTimers();
});

describe("AppShell(사이드바·상단 바·아래 탭바)", () => {
  it("주 메뉴는 홈·직무·근로자·설정, '그림'은 숨긴다", () => {
    renderShell();
    const nav = screen.getByRole("navigation", { name: "주 메뉴" });
    expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual(["홈", "직무", "근로자", "설정"]);
    expect(screen.queryByRole("link", { name: "그림" })).not.toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "직무" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "홈" })).not.toHaveAttribute("aria-current");
  });

  it("사이드바는 1280 미만 72·이상 240, 768 미만은 숨기고 아래 탭바(홈·직무·근로자·더보기)", () => {
    renderShell();
    expect(screen.getByTestId("sidebar")).toHaveClass("hidden", "md:flex", "w-rail", "xl:w-sidebar");
    const tabbar = screen.getByTestId("mobile-tabbar");
    expect(tabbar).toHaveClass("md:hidden");
    expect(within(tabbar).getAllByRole("link").map((a) => a.textContent)).toEqual(["홈", "직무", "근로자"]);
    expect(within(tabbar).getByRole("button", { name: "더보기" })).toHaveAttribute("aria-haspopup", "menu");
  });

  it("상단 바: 이동 경로, [새 직무], 도움 종, 사용자 메뉴", () => {
    renderShell("/m/tasks/new");
    const crumbs = screen.getByRole("navigation", { name: "이동 경로" });
    expect(within(crumbs).getByRole("link", { name: "직무" })).toHaveAttribute("href", "/m/tasks");
    expect(within(crumbs).getByText("새 직무")).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "새 직무" })).toHaveAttribute("href", "/m/tasks/new");
    expect(screen.getByRole("button", { name: "도움 요청 없음" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /테스트사장\s*계정 메뉴/ })).toBeInTheDocument();
    expect(screen.getByText("새 직무 본문")).toBeInTheDocument();
  });

  it("사용자 메뉴 [로그아웃] → onLogout + /m/login", async () => {
    const user = userEvent.setup();
    const onLogout = vi.fn();
    renderShell("/m", onLogout);
    await user.click(screen.getByRole("button", { name: /테스트사장\s*계정 메뉴/ }));
    await user.click(screen.getByRole("menuitem", { name: "로그아웃" }));
    expect(onLogout).toHaveBeenCalled();
    expect(screen.getByText("로그인 화면")).toBeInTheDocument();
  });

  it("본문으로 건너뛰기 링크와 main 영역", () => {
    renderShell();
    expect(screen.getByRole("link", { name: "본문으로 건너뛰기" })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
  });

  it("이동 경로·폭 규칙: 편집기만 꽉 채우고 목록·홈은 최대 1200", () => {
    expect(crumbsFor("/m").map((c) => c.label)).toEqual(["홈"]);
    expect(crumbsFor("/m/tasks/abc").map((c) => c.label)).toEqual(["직무", "직무 고치기"]);
    expect(crumbsFor("/m/workers/w1").map((c) => c.label)).toEqual(["근로자", "근로자 상세"]);
    expect(isFullWidth("/m/tasks/abc")).toBe(true);
    expect(isFullWidth("/m/tasks/new")).toBe(false);
    expect(isFullWidth("/m/tasks")).toBe(false);
    expect(isFullWidth("/m")).toBe(false);
  });
});

describe("도움 띠·종이 useHelpFeed 하나를 나눠 쓴다(contract §2.2)", () => {
  it("띠와 종이 함께 있어도 도움 요청 주소를 한 번만 부른다", async () => {
    vi.useFakeTimers();
    employerHelp.mockResolvedValue([help(), help({ id: "h2", worker_name: "이수진" })]);
    renderShell("/m/tasks");
    await act(async () => {});
    expect(employerHelp).toHaveBeenCalledTimes(1);
    expect(employerHelp).toHaveBeenCalledWith("active");
    // 띠(본문 위)와 종 배지가 같은 목록을 보인다.
    expect(screen.getByTestId("help-alert-strip")).toHaveTextContent("김민지 님이 도움을 요청했어요");
    expect(screen.getByRole("button", { name: "도움 요청 2건 · 띠로 가기" }).querySelector("[data-badge]")).toHaveAttribute("data-badge", "2");
    await act(async () => {
      vi.advanceTimersByTime(HELP_FEED_POLL_MS);
    });
    expect(employerHelp).toHaveBeenCalledTimes(2);
  });

  it("화면을 옮겨도 틀은 그대로라 다시 부르지 않고, 모든 /m 화면에서 띠가 보인다", async () => {
    employerHelp.mockResolvedValue([help()]);
    const user = userEvent.setup();
    renderShell("/m");
    await screen.findByTestId("help-alert-strip");
    for (const name of ["직무", "설정", "홈"]) {
      await user.click(within(screen.getByRole("navigation", { name: "주 메뉴" })).getByRole("link", { name }));
      expect(screen.getByTestId("help-alert-strip")).toBeInTheDocument();
    }
    expect(employerHelp).toHaveBeenCalledTimes(1);
  });

  it("종을 누르면 띠의 첫 버튼으로 초점이 간다", async () => {
    employerHelp.mockResolvedValue([help()]);
    const user = userEvent.setup();
    renderShell("/m/tasks");
    const bell = await screen.findByRole("button", { name: "도움 요청 1건 · 띠로 가기" });
    await user.click(bell);
    await waitFor(() => expect(screen.getByRole("button", { name: "확인했어요" })).toHaveFocus());
  });
});
