import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, AuthError, NetworkError, api, auth, getAuth, req } from "../src/api";
import { getSavedWorkplaceName } from "../src/workerCodes";

// api.ts의 오류 규칙(0차 2번): 로그인 401은 서버 문장 그대로, 그 밖의 401은 AuthError + 저장된 로그인 지움,
// 닿지 못하면 NetworkError(영어 "Failed to fetch"를 화면에 내지 않음). 네트워크는 쓰지 않는다(fetch 목).
function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const fetchMock = vi.fn();

beforeEach(() => {
  localStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

function loginAsEmployer() {
  localStorage.setItem("jobcard_token", "t");
  localStorage.setItem("jobcard_role", "employer");
  localStorage.setItem("jobcard_name", "사장님");
}

describe("req 오류 규칙", () => {
  it("2xx면 JSON을 돌려주고 토큰을 붙인다", async () => {
    loginAsEmployer();
    fetchMock.mockResolvedValue(jsonResponse(200, [{ id: "t1" }]));
    await expect(req("/api/tasks")).resolves.toEqual([{ id: "t1" }]);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer t");
  });

  it("서버 detail 문장은 ApiError.message·detail·status로 온다", async () => {
    fetchMock.mockResolvedValue(jsonResponse(422, { detail: "그림이 없는 단계가 있어요(2단계)." }));
    const err = await req("/api/tasks/x/publish", { method: "POST" }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).not.toBeInstanceOf(AuthError);
    expect(err.status).toBe(422);
    expect(err.detail).toBe("그림이 없는 단계가 있어요(2단계).");
    expect(err.message).toBe("그림이 없는 단계가 있어요(2단계).");
  });

  it("검증 오류(detail 배열)는 일반 문구로 바꾼다", async () => {
    fetchMock.mockResolvedValue(jsonResponse(422, { detail: [{ loc: ["body"], msg: "field required" }] }));
    const err = await req("/api/workers", { method: "POST" }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.detail).toBeNull();
    expect(err.message).toBe("입력값을 확인해 주세요.");
  });

  it("본문이 없으면 상태 코드를 담은 문구", async () => {
    fetchMock.mockResolvedValue(new Response("oops", { status: 502 }));
    const err = await req("/api/tasks").catch((e) => e);
    expect(err.status).toBe(502);
    expect(err.message).toBe("요청 실패 (502)");
  });

  it("로그인 밖의 401은 AuthError이고 저장된 로그인을 지운다", async () => {
    loginAsEmployer();
    fetchMock.mockResolvedValue(jsonResponse(401, { detail: "토큰이 만료되었습니다." }));
    const err = await req("/api/tasks").catch((e) => e);
    expect(err).toBeInstanceOf(AuthError);
    expect(err.status).toBe(401);
    expect(getAuth()).toBeNull();
  });

  it("로그인 요청의 401은 서버 문장 그대로이고 저장된 로그인을 지우지 않는다", async () => {
    loginAsEmployer();
    fetchMock.mockResolvedValue(jsonResponse(401, { detail: "사업장 코드 또는 접속 코드가 올바르지 않습니다." }));
    const err = await auth.loginWorker("DEMO01", "9999").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).not.toBeInstanceOf(AuthError);
    expect(err.message).toBe("사업장 코드 또는 접속 코드가 올바르지 않습니다.");
    expect(getAuth()).not.toBeNull();
  });

  it("서버에 닿지 못하면 NetworkError(영어 원문 없음)", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const err = await req("/api/tasks").catch((e) => e);
    expect(err).toBeInstanceOf(NetworkError);
    expect(err.message).not.toMatch(/[A-Za-z]/);
  });

  it("사진 올리기도 같은 규칙(서버 문장·NetworkError)", async () => {
    loginAsEmployer();
    const file = new File([new Uint8Array([1])], "p.png", { type: "image/png" });
    fetchMock.mockResolvedValueOnce(jsonResponse(413, { detail: "사진이 너무 커요." }));
    await expect(api.uploadStepPhoto("t", "s", file)).rejects.toMatchObject({ status: 413, message: "사진이 너무 커요." });
    fetchMock.mockResolvedValueOnce(new Response("", { status: 500 }));
    await expect(api.uploadStepPhoto("t", "s", file)).rejects.toMatchObject({ message: "사진 업로드 실패 (500)" });
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(api.uploadStepPhoto("t", "s", file)).rejects.toBeInstanceOf(NetworkError);
  });
});

describe("auth.loginWorker", () => {
  it("응답의 사업장 이름을 기기에 저장한다(번호 넣기 화면 위 띠)", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { token: "w", role: "worker", display_name: "김민수", workplace_name: "행복카페" }),
    );
    const state = await auth.loginWorker("DEMO01", "1234");
    expect(state).toEqual({ token: "w", role: "worker", displayName: "김민수" });
    expect(getSavedWorkplaceName()).toBe("행복카페");
  });

  it("믿는 기기 표시를 받아 두고 다음 로그인 때 보낸다(사업장 공용 잠금에 안 막히게)", async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(200, { token: "w", role: "worker", display_name: "김민수", device_token: "dev.sig" }),
    );
    await auth.loginWorker("DEMO01", "1234");
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({
      workplace_code: "DEMO01",
      access_code: "1234",
    });
    await auth.loginWorker("DEMO01", "1234");
    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body)).device_token).toBe("dev.sig");
  });

  it("사업장 이름이 없는 예전 서버여도 로그인된다", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { token: "w", role: "worker", display_name: "김민수" }));
    await auth.loginWorker("DEMO01", "1234");
    expect(getSavedWorkplaceName()).toBeNull();
  });
});

describe("사업주 도움 요청 호출", () => {
  it("목록·확인·해결 주소", async () => {
    loginAsEmployer();
    fetchMock.mockImplementation(async () => jsonResponse(200, []));
    await api.employerHelp();
    await api.ackHelp("h1");
    await api.resolveHelp("h1");
    await api.updateWorker("w1", { a11y_prefs: { autoplay_sound: false } });
    const calls = fetchMock.mock.calls.map(([url, init]) => [String(url).replace(/^https?:\/\/[^/]+/, ""), (init as RequestInit).method ?? "GET"]);
    expect(calls).toEqual([
      ["/api/employer/help?state=active", "GET"],
      ["/api/employer/help/h1/acknowledge", "POST"],
      ["/api/employer/help/h1/resolve", "POST"],
      ["/api/workers/w1", "PATCH"],
    ]);
    expect(JSON.parse((fetchMock.mock.calls[3][1] as RequestInit).body as string)).toEqual({ a11y_prefs: { autoplay_sound: false } });
  });
});
