import { describe, it, expect, vi, beforeEach } from "vitest";
import { ApiError, NetworkError } from "../../src/apiErrors";
import { blockedStepIdsAfterSendError, blockedStepIdsOf, sendApi } from "../../src/manager/api/send";

const reqMock = vi.fn();
vi.mock("../../src/api", () => ({ req: (path: string, init?: RequestInit) => reqMock(path, init) }));

// mockReset 뒤에 던지는 구현을 걸면 vitest 5가 그 오류를 시험 실패로 잡는다 — 지우기만 하고 구현은 시험마다 건다.
beforeEach(() => {
  reqMock.mockClear();
  reqMock.mockImplementation(async () => ({}));
});

describe("manager/api/send — 2a-0 새 호출", () => {
  it("경로·메서드·본문이 계약(contract §1.4)과 같다", async () => {
    reqMock.mockResolvedValue({});
    await sendApi.confirmPicture("t 1", "s/1");
    expect(reqMock).toHaveBeenLastCalledWith("/api/tasks/t%201/steps/s%2F1/picture/confirm", { method: "POST" });
    await sendApi.sendCheck("t1");
    expect(reqMock).toHaveBeenLastCalledWith("/api/tasks/t1/send-check", undefined);
    await sendApi.send("t1", ["w1", "w2"]);
    expect(reqMock).toHaveBeenLastCalledWith("/api/tasks/t1/send", {
      method: "POST", body: JSON.stringify({ worker_ids: ["w1", "w2"], day: "today" }),
    });
    await sendApi.send("t1", ["w1"], "2026-11-10");
    expect(JSON.parse(reqMock.mock.lastCall![1].body)).toEqual({ worker_ids: ["w1"], day: "2026-11-10" });
    await sendApi.recipients("t1");
    expect(reqMock).toHaveBeenLastCalledWith("/api/tasks/t1/recipients", undefined);
  });

  it("점검표에서 통과하지 못한 막는 줄의 단계만, 중복 없이 고른다", () => {
    expect(blockedStepIdsOf({
      ok: false,
      blocking: [
        { code: "no_picture", done: 1, total: 3, step_ids: ["s2", "s3"] },
        { code: "unconfirmed_auto", done: 0, total: 1, step_ids: ["s3", "s1"] },
        { code: "unreviewed_split", done: 0, total: 0, step_ids: ["x"] },
        { code: "no_steps", done: 1, total: 1, step_ids: ["y"] },
      ],
      warnings: [{ code: "too_long", count: 1, step_ids: ["z"] }],
    })).toEqual(["s2", "s3", "s1"]);
  });

  it("422·409일 때만 점검표를 읽고, 못 읽으면 빈 목록이다", async () => {
    reqMock.mockResolvedValue({
      ok: false, blocking: [{ code: "no_picture", done: 0, total: 1, step_ids: ["s1"] }], warnings: [],
    });
    expect(await blockedStepIdsAfterSendError("t1", new ApiError(422, "막힘"))).toEqual(["s1"]);
    expect(await blockedStepIdsAfterSendError("t1", new ApiError(409, "보관함"))).toEqual(["s1"]);
    expect(reqMock).toHaveBeenCalledTimes(2);
    expect(await blockedStepIdsAfterSendError("t1", new ApiError(500, "서버"))).toEqual([]);
    expect(await blockedStepIdsAfterSendError("t1", new NetworkError())).toEqual([]);
    expect(reqMock).toHaveBeenCalledTimes(2);
  });

  it("점검표를 못 읽으면 빈 목록이다(오류 문장은 호출한 쪽이 그대로 보인다)", async () => {
    reqMock.mockImplementation(async () => { throw new NetworkError(); });
    expect(await blockedStepIdsAfterSendError("t1", new ApiError(422, "막힘"))).toEqual([]);
  });
});
