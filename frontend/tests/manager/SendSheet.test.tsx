import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Worker } from "../../src/api";
import type { Recipients, SendCheck } from "../../src/manager/api/types";
import SendSheet from "../../src/manager/tasks/editor/SendSheet";
import { precheck } from "../../src/manager/tasks/editor/sendRules";
import { editorMock, resetMocks, sendMock } from "./editorHarness";

// 보내기 시트(contract §3.6·3.7, tasks §4.4): 접속 코드 0건, 미리 체크 규칙 3가지, 다 한 사람 체크 해제,
// total=0 줄 숨김, 오늘 상태 문구, '✦ 자동으로 켠 조심 표시' 경고 줄(막지 않음)이 그 단계로 감, 하는 중 덧줄.
vi.mock("../../src/manager/api/editor", async () => ({ editorApi: (await import("./editorHarness")).editorMock }));
vi.mock("../../src/manager/api/send", async () => ({ sendApi: (await import("./editorHarness")).sendMock }));

const W = (id: string, name: string, code: string): Worker => ({
  id, display_name: name, access_code: code, access_code_hint: code.slice(-2), access_code_length: code.length,
});
const WORKERS = [W("w1", "김민지", "4821"), W("w2", "이서준", "7390"), W("w3", "박하늘", "1156")];

const OK_CHECK: SendCheck = {
  ok: true,
  blocking: [
    { code: "no_picture", done: 6, total: 6, step_ids: [] },
    { code: "unconfirmed_auto", done: 6, total: 6, step_ids: [] },
    { code: "unreviewed_split", done: 0, total: 0, step_ids: [] },
  ],
  warnings: [
    { code: "too_long", count: 0, step_ids: [] },
    { code: "command_tone", count: 0, step_ids: [] },
    { code: "auto_caution", count: 1, step_ids: ["s1"] },
  ],
};

function rec(over: Partial<Recipients> = {}): Recipients {
  return {
    last_batch_worker_ids: [],
    all_ever_worker_ids: [],
    workplace_last_batch_worker_ids: [],
    today_status: { w1: "none", w2: "none", w3: "none" },
    ...over,
  };
}

async function open(r: Recipients, check: SendCheck = OK_CHECK, workers = WORKERS, over: Partial<Parameters<typeof SendSheet>[0]> = {}) {
  sendMock.sendCheck.mockResolvedValue(check);
  sendMock.recipients.mockResolvedValue(r);
  editorMock.listWorkers.mockResolvedValue(workers);
  const props = {
    open: true, onClose: vi.fn(), taskId: "task-1", hasUnsentChanges: false, versionNo: null as number | null,
    onGoToStep: vi.fn(), onSent: vi.fn(), ...over,
  };
  const user = userEvent.setup();
  render(<SendSheet {...props} />);
  const sheet = await screen.findByRole("dialog", { name: "보내기 전에 확인해요" });
  await within(sheet).findByTestId("send-checklist");
  return { user, sheet, props };
}

const box = (name: string) => screen.getByRole("checkbox", { name: new RegExp(`${name} 님`) });

beforeEach(() => resetMocks());

describe("미리 체크 규칙(contract §3.6)", () => {
  it("1) 이 직무를 지난번 받은 사람 → '지난번 받은 사람을 골라 두었어요'", async () => {
    await open(rec({ last_batch_worker_ids: ["w2"], workplace_last_batch_worker_ids: ["w1"] }));
    expect(box("이서준")).toBeChecked();
    expect(box("김민지")).not.toBeChecked();
    expect(screen.getByText("지난번 받은 사람을 골라 두었어요")).toBeInTheDocument();
  });

  it("2) 없으면 사업장에서 가장 최근에 보낸 묶음의 받는 사람", async () => {
    await open(rec({ workplace_last_batch_worker_ids: ["w1", "w3"] }));
    expect(box("김민지")).toBeChecked();
    expect(box("박하늘")).toBeChecked();
    expect(box("이서준")).not.toBeChecked();
  });

  it("3) 근로자가 1명이면 그 사람(규칙 문구는 보이지 않음)", async () => {
    await open(rec({ today_status: { w1: "none" } }), OK_CHECK, [WORKERS[0]]);
    expect(box("김민지")).toBeChecked();
    expect(screen.queryByText("지난번 받은 사람을 골라 두었어요")).toBeNull();
    expect(screen.getByRole("button", { name: "1명에게 보내기" })).toBeEnabled();
  });

  it("오늘 이미 다 한 사람은 미리 체크하지 않는다", () => {
    const r = rec({ last_batch_worker_ids: ["w1", "w2"], today_status: { w1: "done", w2: "in_progress", w3: "none" } });
    expect([...precheck(r, WORKERS).ids]).toEqual(["w2"]);
  });
});

describe("시트 내용", () => {
  it("DOM에 접속 코드가 하나도 없다(이름과 오늘 상태만)", async () => {
    const { sheet } = await open(rec({ last_batch_worker_ids: ["w1"] }));
    for (const w of WORKERS) expect(sheet.innerHTML).not.toContain(w.access_code!);
    expect(document.body.innerHTML).not.toMatch(/4821|7390|1156/);
  });

  it("오늘 상태 문구: 다 함 · 하는 중 · 시작 전", async () => {
    await open(rec({ today_status: { w1: "done", w2: "in_progress", w3: "not_started" } }));
    expect(box("김민지")).toHaveAccessibleDescription("오늘 이미 다 했어요 · 한 번 더 보내요");
    expect(box("이서준")).toHaveAccessibleDescription("지금 하는 중이라 다음부터 바뀌어요");
    expect(box("박하늘")).toHaveAccessibleDescription("아직 시작 전이에요");
  });

  it("하는 중인 사람을 고르면 '{이름} 님은 지금 하는 중이라 다음에 보낼 때부터 바뀌어요'", async () => {
    await open(rec({ last_batch_worker_ids: ["w2"], today_status: { w1: "none", w2: "in_progress", w3: "none" } }));
    expect(screen.getByText("이서준 님은 지금 하는 중이라 다음에 보낼 때부터 바뀌어요")).toBeInTheDocument();
  });

  it("점검표: total=0 줄은 숨기고, 통과한 줄은 '모든 단계에 그림이 있어요 6/6'처럼 보인다", async () => {
    const { sheet } = await open(rec());
    const list = within(sheet).getByTestId("send-checklist");
    expect(list).toHaveTextContent("모든 단계에 그림이 있어요 6/6");
    expect(list).toHaveTextContent("자동으로 고른 그림을 확인했어요 6/6");
    expect(list).not.toHaveTextContent("자동으로 나눈 문장을 확인했어요");
    expect(list).not.toHaveTextContent("긴 문장이");
  });

  it("'✦ 자동으로 켠 조심 표시가 1개 있어요' 경고 줄은 보내기를 막지 않고, 누르면 그 단계로 간다", async () => {
    const { user, props } = await open(rec({ last_batch_worker_ids: ["w1"] }));
    const warn = screen.getByRole("button", { name: "✦ 자동으로 켠 조심 표시가 1개 있어요 · 그 단계로 가기" });
    expect(screen.getByRole("button", { name: "1명에게 보내기" })).toBeEnabled();
    await user.click(warn);
    expect(props.onGoToStep).toHaveBeenCalledWith("s1");
  });

  it("막힌 줄(그림 확인 2/4)은 빨갛게, 누르면 그 단계로 — [보내기]는 꺼진다", async () => {
    const check: SendCheck = {
      ok: false,
      blocking: [
        { code: "no_picture", done: 4, total: 4, step_ids: [] },
        { code: "unconfirmed_auto", done: 2, total: 4, step_ids: ["s3", "s5"] },
      ],
      warnings: [],
    };
    const { user, props } = await open(rec({ last_batch_worker_ids: ["w1"] }), check);
    await user.click(screen.getByRole("button", { name: "자동으로 고른 그림을 확인했어요 2/4 · 그 단계로 가기" }));
    expect(props.onGoToStep).toHaveBeenCalledWith("s3");
    expect(screen.getByRole("button", { name: "1명에게 보내기" })).toBeDisabled();
  });

  it("고친 내용이 있으면 '고친 내용도 함께 보내요 · 3번째 버전'", async () => {
    await open(rec(), OK_CHECK, WORKERS, { hasUnsentChanges: true, versionNo: 2 });
    expect(screen.getByText("고친 내용도 함께 보내요 · 3번째 버전")).toBeInTheDocument();
  });

  it("언제: 오늘(기본)·내일·날짜 — 내일을 고르면 day=tomorrow로 보낸다", async () => {
    const { user, props } = await open(rec({ last_batch_worker_ids: ["w1"] }));
    expect(screen.getByRole("radio", { name: "오늘" })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: "내일" }));
    const result = { version_no: 1, version_created: true, day: "2026-11-11", results: [{ worker_id: "w1", display_name: "김민지", outcome: "created" }] };
    sendMock.send.mockResolvedValue(result);
    await user.click(screen.getByRole("button", { name: "1명에게 보내기" }));
    expect(sendMock.send).toHaveBeenCalledWith("task-1", ["w1"], "tomorrow");
    await waitFor(() => expect(props.onSent).toHaveBeenCalledWith(result));
  });

  it("실패하면 시트 안에 오류를 남긴다(닫지 않음)", async () => {
    const { user, props } = await open(rec({ last_batch_worker_ids: ["w1"] }));
    sendMock.send.mockRejectedValue(new Error("x"));
    await user.click(screen.getByRole("button", { name: "1명에게 보내기" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(props.onSent).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "보내기 전에 확인해요" })).toBeInTheDocument();
  });

  it("[모두 선택]으로 셋 다 고른다", async () => {
    const { user } = await open(rec());
    await user.click(screen.getByRole("button", { name: "모두 선택" }));
    expect(screen.getByRole("button", { name: "3명에게 보내기" })).toBeEnabled();
  });
});
