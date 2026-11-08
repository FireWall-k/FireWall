import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, AuthError, NetworkError } from "../../src/apiErrors";
import { Outbox, OUTBOX_PREFIX, getOutbox, resetOutboxRegistry } from "../../src/worker/outbox";
import type { LogBody } from "../../src/worker/workerApi";

// 오프라인 기록 대기열(contract §6.3): 기록을 잃지 않고, 같은 기록을 두 번 세지 않는다.
const base = { duration_sec: 3, replay_count: 0, stuck: false, completed: true };

beforeEach(() => {
  localStorage.clear();
  resetOutboxRegistry();
});

describe("Outbox", () => {
  it("기기에 저장하고, 같은 단계는 마지막 기록만 남긴다(event id는 새로)", () => {
    const box = new Outbox("w1");
    const a = box.put({ ...base, assignment_id: "a1", step_id: "s1" });
    box.put({ ...base, assignment_id: "a1", step_id: "s2" });
    const b = box.put({ ...base, assignment_id: "a1", step_id: "s1", replay_count: 2 });
    expect(box.list().map((x) => x.step_id)).toEqual(["s2", "s1"]);
    expect(b.client_event_id).not.toBe(a.client_event_id);
    expect(box.list()[1].replay_count).toBe(2);
    // 새로 만들어도(새로고침) 남아 있다. 근로자별 키.
    const again = new Outbox("w1");
    expect(again.size).toBe(2);
    expect(localStorage.getItem(`${OUTBOX_PREFIX}w1`)).toContain("s2");
    expect(new Outbox("w2").size).toBe(0);
  });

  it("2xx면 지우고, 네트워크 오류면 남기고 멈춘다(다음에 같은 event id로 다시 보낸다)", async () => {
    const box = new Outbox("w1");
    const item = box.put({ ...base, assignment_id: "a1", step_id: "s1" });
    box.put({ ...base, assignment_id: "a1", step_id: "s2" });
    const send = vi.fn<(b: LogBody) => Promise<unknown>>().mockRejectedValueOnce(new NetworkError());
    const r1 = await box.flush(send);
    expect(r1).toMatchObject({ sent: 0, failed: true, remaining: 2 });
    expect(send).toHaveBeenCalledTimes(1);

    send.mockResolvedValue({ ok: true });
    const r2 = await box.flush(send);
    expect(r2).toMatchObject({ sent: 2, remaining: 0, failed: false });
    expect(send.mock.calls[1][0].client_event_id).toBe(item.client_event_id);
    expect(send.mock.calls[1][0]).not.toHaveProperty("key");
    expect(localStorage.getItem(`${OUTBOX_PREFIX}w1`)).toBeNull();
  });

  it("400·404·422는 버리고 다음 것을 보낸다, 429·5xx는 남긴다", async () => {
    const box = new Outbox("w1");
    box.put({ ...base, assignment_id: "a1", step_id: "gone" });
    box.put({ ...base, assignment_id: "a1", step_id: "ok" });
    box.put({ ...base, assignment_id: "a1", step_id: "busy" });
    const send = vi.fn(async (b: LogBody) => {
      if (b.step_id === "gone") throw new ApiError(404, "배정을 찾을 수 없습니다.");
      if (b.step_id === "busy") throw new ApiError(503, null);
      return { ok: true };
    });
    const r = await box.flush(send);
    expect(r).toMatchObject({ sent: 1, dropped: 1, failed: true, remaining: 1 });
    expect(box.list().map((x) => x.step_id)).toEqual(["busy"]);

    send.mockImplementation(async () => {
      throw new ApiError(429, null);
    });
    expect((await box.flush(send)).remaining).toBe(1);
  });

  it("401이면 대기열을 그대로 두고 expired를 알린다", async () => {
    const box = new Outbox("w1");
    box.put({ ...base, assignment_id: "a1", step_id: "s1" });
    const r = await box.flush(async () => {
      throw new AuthError();
    });
    expect(r).toMatchObject({ expired: true, remaining: 1 });
  });

  it("서버가 중복(200 duplicate)·옛 기록(applied=false)이라고 해도 2xx이므로 지운다", async () => {
    const box = new Outbox("w1");
    box.put({ ...base, assignment_id: "a1", step_id: "s1" });
    await box.flush(async () => ({ ok: true, duplicate: true, applied: false }));
    expect(box.size).toBe(0);
  });

  it("보내는 중에 같은 단계가 새로 들어오면 새 기록은 남는다", async () => {
    const box = new Outbox("w1");
    box.put({ ...base, assignment_id: "a1", step_id: "s1" });
    let release!: () => void;
    const send = vi.fn(() => new Promise<unknown>((res) => (release = () => res({ ok: true }))));
    const p = box.flush(send);
    const newer = box.put({ ...base, assignment_id: "a1", step_id: "s1", replay_count: 5 });
    release();
    await p;
    expect(box.list().map((x) => x.client_event_id)).toEqual([newer.client_event_id]);
  });

  it("동시에 두 번 flush해도 한 번만 보낸다", async () => {
    const box = getOutbox("w1");
    box.put({ ...base, assignment_id: "a1", step_id: "s1" });
    const send = vi.fn(async () => ({ ok: true }));
    await Promise.all([box.flush(send), box.flush(send)]);
    expect(send).toHaveBeenCalledTimes(1);
    expect(getOutbox("w1")).toBe(box);
  });

  it("localStorage가 막혀도 메모리로 동작한다", async () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const box = new Outbox("w9");
    box.put({ ...base, assignment_id: "a1", step_id: "s1" });
    expect(box.size).toBe(1);
    expect((await box.flush(async () => ({ ok: true }))).sent).toBe(1);
    spy.mockRestore();
  });
});
