import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../src/apiErrors";
import {
  archiveTask,
  deleteTask,
  duplicateTask,
  listEmployerTasks,
  renameTask,
  unarchiveTask,
} from "../../src/manager/api/tasks";
import { relativeDate } from "../../src/manager/tasks/relativeDate";

// 직무 목록 API 호출 모양(contract §2.1). 네트워크는 쓰지 않는다(fetch 목).
const fetchMock = vi.fn();
function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
function called(i = 0) {
  const [url, init] = fetchMock.mock.calls[i] as [string, RequestInit | undefined];
  const u = new URL(url);
  return { path: u.pathname, search: u.searchParams, method: init?.method ?? "GET", body: init?.body };
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("jobcard_token", "t");
  localStorage.setItem("jobcard_role", "employer");
  fetchMock.mockReset().mockImplementation(async () => json(200, { items: [], counts: {} }));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("manager/api/tasks", () => {
  it("목록: GET /api/employer/tasks?filter=&q=(검색어 앞뒤 빈칸은 뺌, 비면 q 없음)", async () => {
    await listEmployerTasks("needs_check", "  컵 씻기 ");
    let c = called(0);
    expect(c.path).toBe("/api/employer/tasks");
    expect(c.method).toBe("GET");
    expect(c.search.get("filter")).toBe("needs_check");
    expect(c.search.get("q")).toBe("컵 씻기");
    await listEmployerTasks("all", "   ");
    c = called(1);
    expect(c.search.get("filter")).toBe("all");
    expect(c.search.has("q")).toBe(false);
  });

  it("보관·꺼내기·복제·지우기·제목 바꾸기의 주소와 방법", async () => {
    await archiveTask("a b");
    await unarchiveTask("t1");
    await duplicateTask("t1");
    await deleteTask("t1");
    await renameTask("t1", "새 제목");
    expect([0, 1, 2, 3, 4].map((i) => `${called(i).method} ${called(i).path}`)).toEqual([
      "POST /api/tasks/a%20b/archive",
      "POST /api/tasks/t1/unarchive",
      "POST /api/tasks/t1/duplicate",
      "DELETE /api/tasks/t1",
      "PATCH /api/tasks/t1",
    ]);
    expect(JSON.parse(called(4).body as string)).toEqual({ title: "새 제목" });
  });

  it("보관하지 않은 직무를 지우면 서버 문장(409)이 ApiError로 온다", async () => {
    fetchMock.mockImplementation(async () => json(409, { detail: "보관함으로 옮긴 직무만 완전히 지울 수 있어요." }));
    const err = await deleteTask("t1").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.message).toBe("보관함으로 옮긴 직무만 완전히 지울 수 있어요.");
  });
});

describe("고친 날(상대 시간)", () => {
  const now = new Date(2026, 10, 10, 15, 0, 0).getTime(); // 기기 시간 11월 10일 15시
  const iso = (t: number) => new Date(t).toISOString().replace("Z", ""); // 서버처럼 Z 없는 UTC
  it.each([
    [now - 20_000, "방금"],
    [now - 5 * 60_000, "5분 전"],
    [now - 3 * 3_600_000, "3시간 전"],
    [new Date(2026, 10, 9, 23, 0).getTime(), "어제"],
    [new Date(2026, 10, 7, 9, 0).getTime(), "3일 전"],
    [new Date(2026, 9, 2, 9, 0).getTime(), "10월 2일"],
    [new Date(2025, 11, 31, 9, 0).getTime(), "2025년 12월 31일"],
  ])("%s → %s", (t, label) => {
    expect(relativeDate(iso(t), now)).toBe(label);
  });
  it("읽을 수 없는 값은 빈 글자", () => {
    expect(relativeDate("not-a-date", now)).toBe("");
  });
});
