import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// App.tsx 주소표(contract §2.2): 옛 주소 replace, /m/login, 로그인 보호. 화면 본체는 가벼운 대역으로 바꾼다.
vi.mock("../../src/pages/ManagerPage", () => ({ default: () => <p>옛 직무 만들기</p> }));
vi.mock("../../src/pages/DashboardPage", () => ({ default: () => <p>옛 대시보드</p> }));
vi.mock("../../src/pages/WorkersPage", () => ({ default: () => <p>옛 근로자 관리</p> }));
vi.mock("../../src/manager/tasks/TaskListPage", () => ({ default: () => <p>직무 목록 화면</p> }));
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
    ["/dashboard", "/m", "옛 대시보드"],
    ["/workers", "/m/workers", "옛 근로자 관리"],
    ["/admin/tasks", "/m/tasks/new", "옛 직무 만들기"],
    ["/admin/dashboard", "/m", "옛 대시보드"],
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
  });

  it("/m/tasks/:id → /m/tasks", async () => {
    loginAsEmployer();
    go("/m/tasks/abc");
    expect(await screen.findByText("직무 목록 화면")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/m/tasks");
  });

  it("로그인하지 않고 /m에 오면 /m/login 로그인 화면", async () => {
    go("/m/tasks");
    expect(await screen.findByRole("button", { name: "로그인" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/m/login");
  });

  it("로그인한 사업주가 /m/login에 오면 홈(/m)으로", async () => {
    loginAsEmployer();
    go("/m/login");
    expect(await screen.findByText("옛 대시보드")).toBeInTheDocument();
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
