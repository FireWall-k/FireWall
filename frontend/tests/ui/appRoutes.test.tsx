import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// App.tsx 주소표(contract §2.2): 옛 주소 replace, /manager/login, 로그인 보호. 화면 본체는 가벼운 대역으로 바꾼다.
vi.mock("../../src/manager/tasks/TaskWorkspace", () => ({ default: () => <p>새 직무·편집기 화면</p> }));
vi.mock("../../src/manager/workers/WorkerListPage", () => ({ default: () => <p>근로자 목록 화면</p> }));
vi.mock("../../src/manager/workers/WorkerDetailPage", () => ({ default: () => <p>근로자 상세 화면</p> }));
vi.mock("../../src/manager/settings/SettingsPage", () => ({ default: () => <h1>설정</h1> }));
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
    ["/m", "/manager", "오늘 현황 화면"],
    ["/m/tasks/new", "/manager/tasks/new", "새 직무·편집기 화면"],
    ["/m/workers", "/manager/workers", "근로자 목록 화면"],
    ["/dashboard", "/manager", "오늘 현황 화면"],
    ["/workers", "/manager/workers", "근로자 목록 화면"],
    ["/admin/tasks", "/manager/tasks/new", "새 직무·편집기 화면"],
    ["/admin/dashboard", "/manager", "오늘 현황 화면"],
  ])("옛 주소 %s → %s (replace)", async (from, to, text) => {
    loginAsEmployer();
    const before = window.history.length;
    go(from);
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(window.location.pathname).toBe(to);
    expect(window.history.length).toBe(before);
  });

  it("옛 주소의 ?쿼리와 #은 그대로 넘긴다", async () => {
    loginAsEmployer();
    go("/m/tasks/new?from=bookmark#help");
    await screen.findByText("새 직무·편집기 화면");
    expect(window.location.pathname + window.location.search + window.location.hash).toBe(
      "/manager/tasks/new?from=bookmark#help",
    );
  });

  it("인쇄한 근로자 QR(/w?site=…)은 /worker?site=…로 넘어간다", async () => {
    go("/w?site=DEMO01");
    await screen.findByText("근로자 화면");
    expect(window.location.pathname + window.location.search).toBe("/worker?site=DEMO01");
  });

  it("짧은 근로자 주소의 뒤 주소도 그대로 넘긴다(/w/job/… → /worker/job/…)", async () => {
    go("/w/job/asg-1/step/2");
    await screen.findByText("근로자 화면");
    expect(window.location.pathname).toBe("/worker/job/asg-1/step/2");
  });

  it("모든 /manager 화면이 새 틀 안에 있다(사이드바·상단 바)", async () => {
    loginAsEmployer();
    go("/manager/workers");
    expect(await screen.findByText("근로자 목록 화면")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "주 메뉴" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "이동 경로" })).toHaveTextContent("근로자");
  });

  it("(2d) /manager/settings는 설정 화면", async () => {
    loginAsEmployer();
    go("/manager/settings");
    expect(await screen.findByRole("heading", { level: 1, name: "설정" })).toBeInTheDocument();
  });

  it("(2d) /manager/workers/:id → 근로자 상세", async () => {
    loginAsEmployer();
    go("/manager/workers/w1");
    expect(await screen.findByText("근로자 상세 화면")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "이동 경로" })).toHaveTextContent("근로자 상세");
  });

  it("(2c) /m은 홈·오늘 현황 화면", async () => {
    loginAsEmployer();
    go("/manager");
    expect(await screen.findByText("오늘 현황 화면")).toBeInTheDocument();
  });

  it("(2b-1) /manager/tasks/new와 /manager/tasks/:id는 같은 화면(새 직무·편집기)을 연다(2c 링크의 ?step=은 그대로)", async () => {
    loginAsEmployer();
    go("/manager/tasks/abc?step=s1");
    expect(await screen.findByText("새 직무·편집기 화면")).toBeInTheDocument();
    expect(window.location.pathname + window.location.search).toBe("/manager/tasks/abc?step=s1");
  });

  it("(2d) 옛 대시보드 주소 /manager/legacy-dashboard는 지웠다 — 홈(/manager)으로", async () => {
    loginAsEmployer();
    go("/manager/legacy-dashboard");
    expect(await screen.findByText("오늘 현황 화면")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/manager");
  });

  it("로그인하지 않고 /m에 오면 /manager/login 로그인 화면", async () => {
    go("/manager/tasks");
    expect(await screen.findByRole("button", { name: "로그인" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/manager/login");
  });

  it("로그인한 사업주가 /manager/login에 오면 홈(/manager)으로", async () => {
    loginAsEmployer();
    go("/manager/login");
    expect(await screen.findByText("오늘 현황 화면")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/manager");
  });

  it("근로자 로그인으로 /m에 오면 근로자 화면으로", async () => {
    localStorage.setItem("jobcard_token", "t");
    localStorage.setItem("jobcard_role", "worker");
    go("/manager");
    expect(await screen.findByText("근로자 화면")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/worker/today");
  });
});
