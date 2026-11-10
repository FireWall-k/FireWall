import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// App.tsx 주소표(contract §2.2): 옛 주소 replace, /m/login, 로그인 보호. 화면 본체는 가벼운 대역으로 바꾼다.
vi.mock("../../src/pages/ManagerPage", () => ({ default: () => <p>옛 직무 만들기</p> }));
vi.mock("../../src/pages/DashboardPage", () => ({ default: () => <p>옛 대시보드</p> }));
vi.mock("../../src/pages/WorkersPage", () => ({ default: () => <p>옛 근로자 관리</p> }));
vi.mock("../../src/manager/tasks/TaskListPage", () => ({ default: () => <p>직무 목록 화면</p> }));
// (2c) 홈은 오늘 현황 화면. 틀의 현황 폴링(getLive)은 빈 현황을 준다.
vi.mock("../../src/manager/home/HomePage", () => ({ default: () => <p>오늘 현황 화면</p> }));
vi.mock("../../src/manager/api/live", () => ({
  getLive: vi.fn().mockResolvedValue({
    server_now: "2026-11-10T01:00:00",
    summary: { working: 0, total_workers: 0, open_help: 0, stuck_steps: 0, needs_check_tasks: 0 },
    workers: [],
    help: [],
  }),
  getPushConfig: vi.fn().mockResolvedValue({ enabled: false, public_key: null }),
}));
vi.mock("../../src/worker/WorkerApp", () => ({ default: () => <p>근로자 화면</p> }));
vi.mock("../../src/api", async (orig) => {
  const real = await orig<typeof import("../../src/api")>();
  return {
    ...real,
    api: { ...real.api, employerHelp: vi.fn().mockResolvedValue([]) },
    auth: { ...real.auth, demoCredentials: vi.fn().mockResolvedValue(null) },
  };
});

import App from "../../src/App";

function loginAsEmployer() {
  localStorage.setItem("jobcard_token", "t");
  localStorage.setItem("jobcard_role", "employer");
  localStorage.setItem("jobcard_name", "테스트사장");
}

function go(path: string) {
  window.history.replaceState({}, "", path);
  render(<App />);
}

beforeEach(() => {
  localStorage.clear();
});
afterEach(() => {
  window.history.replaceState({}, "", "/");
});

describe("사업주 주소(2a-1)", () => {
  it.each([
    ["/manager", "/m/tasks/new", "옛 직무 만들기"],
    ["/dashboard", "/m", "오늘 현황 화면"],
    ["/workers", "/m/workers", "옛 근로자 관리"],
    ["/admin/tasks", "/m/tasks/new", "옛 직무 만들기"],
    ["/admin/dashboard", "/m", "오늘 현황 화면"],
  ])("옛 주소 %s → %s (replace)", async (from, to, text) => {
    loginAsEmployer();
    const before = window.history.length;
    go(from);
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(window.location.pathname).toBe(to);
    expect(window.history.length).toBe(before);
  });

  it("옛 주소의 ?쿼리는 그대로 넘긴다", async () => {
    loginAsEmployer();
    go("/manager?from=bookmark");
    await screen.findByText("옛 직무 만들기");
    expect(window.location.pathname + window.location.search).toBe("/m/tasks/new?from=bookmark");
  });

  it("모든 /m 화면이 새 틀 안에 있다(사이드바·상단 바)", async () => {
    loginAsEmployer();
    go("/m/workers");
    expect(await screen.findByText("옛 근로자 관리")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "주 메뉴" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "이동 경로" })).toHaveTextContent("근로자");
  });

  it("/m/settings는 '준비 중', /m/tasks/:id는 아직 열지 않고 목록으로", async () => {
    loginAsEmployer();
    go("/m/settings");
    expect(await screen.findByText("설정은 준비 중이에요")).toBeInTheDocument();
    // 준비 중 화면에도 화면 이름 h1(axe page-has-heading-one)
    expect(screen.getByRole("heading", { level: 1, name: "설정" })).toBeInTheDocument();
  });

  it("(2c) /m/tasks/:id는 편집기 자리: 주소(?step=)를 그대로 두고 '준비 중'(2b-1 편집기가 들어옴)", async () => {
    loginAsEmployer();
    go("/m/tasks/abc?step=s1");
    expect(await screen.findByText("단계 편집 화면은 준비 중이에요")).toBeInTheDocument();
    expect(window.location.pathname + window.location.search).toBe("/m/tasks/abc?step=s1");
  });

  it("(2c) 옛 대시보드는 /m/legacy-dashboard", async () => {
    loginAsEmployer();
    go("/m/legacy-dashboard");
    expect(await screen.findByText("옛 대시보드")).toBeInTheDocument();
  });

  it("로그인하지 않고 /m에 오면 /m/login 로그인 화면", async () => {
    go("/m/tasks");
    expect(await screen.findByRole("button", { name: "로그인" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/m/login");
  });

  it("로그인한 사업주가 /m/login에 오면 홈(/m)으로", async () => {
    loginAsEmployer();
    go("/m/login");
    expect(await screen.findByText("오늘 현황 화면")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/m");
  });

  it("근로자 로그인으로 /m에 오면 근로자 화면으로", async () => {
    localStorage.setItem("jobcard_token", "t");
    localStorage.setItem("jobcard_role", "worker");
    go("/m");
    expect(await screen.findByText("근로자 화면")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/w/today");
  });
});
