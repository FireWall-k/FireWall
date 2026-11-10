import { beforeEach, describe, expect, it, vi } from "vitest";

// manager/api/editor(contract §3.4): 경로·메서드·본문, 예전 응답에 없는 편집 칸 채우기.
const reqMock = vi.fn();
vi.mock("../../src/api", () => ({
  req: (path: string, init?: RequestInit) => reqMock(path, init),
  api: { splitPreview: vi.fn(), uploadStepPhoto: vi.fn(), removeStepPhoto: vi.fn(), searchAac: vi.fn(), listWorkers: vi.fn() },
}));

import { editorApi, normalizeStep } from "../../src/manager/api/editor";

const TASK = { id: "t1", title: "x", status: "draft", steps: [{ id: "s1", sentence: "손을 씻어요." }] };

beforeEach(() => {
  reqMock.mockClear();
  reqMock.mockImplementation(async (path: string) => {
    if (path.endsWith("/rewrite")) return { task: TASK, split_step_ids: [], sentence: "" };
    if (path.endsWith("/pictures/confirm")) return [{ id: "s1", sentence: "손을 씻어요.", picture_state: "confirmed" }];
    if (/\/steps\/[^/]+(\/picture(\/confirm)?)?$/.test(path) && !path.endsWith("/steps/reorder")) return { id: "s1", sentence: "a" };
    return TASK;
  });
});

describe("편집기 호출 경로(contract §3.4)", () => {
  it("자동 저장 PATCH: defer_media·expected_updated_at을 그대로 보낸다", async () => {
    await editorApi.patchStep("t 1", "s/1", { sentence: "a", defer_media: true, expected_updated_at: "2026-11-10T01:00:00" });
    expect(reqMock).toHaveBeenLastCalledWith("/api/tasks/t%201/steps/s%2F1", {
      method: "PATCH", body: JSON.stringify({ sentence: "a", defer_media: true, expected_updated_at: "2026-11-10T01:00:00" }),
    });
  });

  it("일괄 확인·그림 적용·모든 단계 후보·목소리", async () => {
    await editorApi.confirmPictures("t1", ["s1", "s2"]);
    expect(reqMock).toHaveBeenLastCalledWith("/api/tasks/t1/pictures/confirm", { method: "POST", body: JSON.stringify({ step_ids: ["s1", "s2"] }) });
    await editorApi.applyPicture("t1", "s1", { card_id: "A1", url: "u", label: "컵" });
    expect(reqMock).toHaveBeenLastCalledWith("/api/tasks/t1/steps/s1/picture", { method: "POST", body: JSON.stringify({ card_id: "A1", url: "u", label: "컵" }) });
    await editorApi.candidates("t1");
    expect(reqMock).toHaveBeenLastCalledWith("/api/tasks/t1/candidates", undefined);
    await editorApi.stepTts("t1", "s1");
    expect(reqMock).toHaveBeenLastCalledWith("/api/tasks/t1/steps/s1/tts", { method: "POST" });
    await editorApi.rewriteStep("t1", "s1", "새 문장");
    expect(reqMock).toHaveBeenLastCalledWith("/api/tasks/t1/steps/s1/rewrite", { method: "POST", body: JSON.stringify({ sentence: "새 문장" }) });
    // 1회차 검증: 칸을 벗어날 때 저장도 이 창이 본 updated_at을 보내 다른 창 검사(409)를 받는다.
    await editorApi.rewriteStep("t1", "s1", "새 문장", "2026-11-11T01:02:03");
    expect(reqMock).toHaveBeenLastCalledWith("/api/tasks/t1/steps/s1/rewrite", {
      method: "POST",
      body: JSON.stringify({ sentence: "새 문장", expected_updated_at: "2026-11-11T01:02:03" }),
    });
  });

  it("새 직무: split·safety_flag를 담아 POST /api/tasks", async () => {
    await editorApi.createTask("원문", { title: "t", steps: [{ sentence: "칼로 열어요.", split: { source: "model", original_span: "원" }, safety_flag: true }] });
    const [path, init] = reqMock.mock.lastCall!;
    expect(path).toBe("/api/tasks");
    expect(JSON.parse(init.body)).toEqual({
      raw_input: "원문", title: "t", steps: [{ sentence: "칼로 열어요.", split: { source: "model", original_span: "원" }, safety_flag: true }],
    });
  });

  it("응답에 편집 칸이 없으면(예전 서버) 기본값으로 채운다", async () => {
    const t = await editorApi.getTask("t1");
    expect(t.steps[0]).toMatchObject({
      picture_state: "none", safety_flag: false, lint: [], group_break: false,
      split: { source: "", needs_review: false, original_span: "" }, safety: { flag: false, source: "", note: "" },
    });
    expect(t.version).toBeNull();
    const s = normalizeStep({ id: "x", sentence: "y", symbol_url: "u", safety_flag: true });
    expect(s.picture_state).toBe("auto_high");
    expect(s.safety.flag).toBe(true);
    const confirmed = await editorApi.confirmPictures("t1", ["s1"]);
    expect(confirmed[0].picture_state).toBe("confirmed");
  });
});
