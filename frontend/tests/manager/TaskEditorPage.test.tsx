import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "../../src/apiErrors";
import { candidatesFor, sixAutoHigh, step, task, T0 } from "./editorFixtures";
import { editorMock as m, renderAt, resetMocks, sendMock, sparkleCount, tasksMock } from "./editorHarness";
import type { EditorStep } from "../../src/manager/api/types";

// 2b-1 편집기(tasks §4.3·4.4): 그림 4상태, Enter → 확인(입력칸 Enter는 아님), 그림 없음의 두 단추, 그림 찾기 → 적용 → 확인함,
// [다음 ▶], 저장 표시 3상태, 문장 점검 칩, 키보드 순서 바꾸기, 저장하며 나누기 + [되돌리기], ✦ 개수, 조심 스위치, 지우기 창,
// 다른 창 충돌(409), 보내기 단추 잠금, 버전 안내. 서버는 manager/api/*를 통째로 목으로(유료 호출 없음).
vi.mock("../../src/manager/api/editor", async () => ({ editorApi: (await import("./editorHarness")).editorMock }));
vi.mock("../../src/manager/api/send", async () => ({ sendApi: (await import("./editorHarness")).sendMock }));
vi.mock("../../src/manager/api/tasks", async () => (await import("./editorHarness")).tasksMock);

const FOUR = () =>
  task([
    step("s1", 1, "앞치마를 입어요.", "confirmed"),
    step("s2", 2, "컵을 물에 넣어요.", "auto_high"),
    step("s3", 3, "컵을 수세미로 닦아요.", "choose"),
    step("s4", 4, "컵을 건조대에 엎어요.", "none"),
  ]);

function confirmed(s: EditorStep): EditorStep {
  return { ...s, picture_state: "confirmed", picture: s.picture ? { ...s.picture, source: "manual" } : null, task_updated_at: "2026-11-10T01:05:00" };
}

async function open(t = FOUR(), path = `/manager/tasks/${t.id}`) {
  m.getTask.mockResolvedValue(t);
  m.candidates.mockResolvedValue(candidatesFor(t));
  const user = userEvent.setup();
  await renderAt(path);
  await screen.findByTestId("step-detail");
  return { user, t };
}

const row = (n: number) => screen.getByTestId(`step-row-${n}`);
/** 목록 행의 고르기 단추(행의 첫 단추). */
const pick = (n: number) => within(row(n)).getAllByRole("button")[0];

vi.setConfig({ testTimeout: 15_000 });
const detail = () => screen.getByTestId("step-detail");

beforeEach(() => {
  resetMocks();
});

describe("그림 4상태", () => {
  it("목록 상태 줄: 확인함 · ✦ 자동 · 확인 필요 · 골라 주세요 · 그림 없음(색 + 글)", async () => {
    await open();
    expect(row(1)).toHaveTextContent("확인함");
    expect(row(2)).toHaveTextContent("✦ 자동 · 확인 필요");
    expect(row(3)).toHaveTextContent("골라 주세요");
    expect(row(4)).toHaveTextContent("그림 없음");
    // 넓은 화면은 처음에 첫 확인할 단계(2단계)를 연다.
    expect(detail()).toHaveAttribute("data-step-id", "s2");
    expect(screen.getByRole("heading", { name: /2단계 고치기/ })).toBeInTheDocument();
  });

  it("auto_high: 그림을 크게 + [이 그림이 맞아요] → 확인 API → 확인함", async () => {
    const { user } = await open();
    m.confirmPicture.mockImplementation(async (_t: string, sid: string) => confirmed(FOUR().steps.find((s) => s.id === sid)!));
    await user.click(within(detail()).getByRole("button", { name: "이 그림이 맞아요" }));
    expect(m.confirmPicture).toHaveBeenCalledWith("task-1", "s2");
    await waitFor(() => expect(row(2)).toHaveTextContent("확인함"));
  });

  it("choose: 지금 그림 자리는 비우고 후보 3장을 크게 — 하나를 고르면 적용 → 확인함", async () => {
    const { user } = await open();
    await user.click(pick(3));
    const grid = await within(detail()).findByTestId("choose-grid");
    expect(within(grid).getAllByRole("button")).toHaveLength(3);
    expect(within(detail()).queryByRole("button", { name: "이 그림이 맞아요" })).toBeNull();
    m.applyPicture.mockImplementation(async () => confirmed(FOUR().steps[2]));
    await user.click(within(grid).getByRole("button", { name: /후보 2/ }));
    expect(m.applyPicture).toHaveBeenCalledWith("task-1", "s3", {
      card_id: "s3-c2", url: "http://x/api/aac/images/cafe/s3-c2.webp", label: "후보2",
    });
    await waitFor(() => expect(row(3)).toHaveTextContent("확인함"));
  });

  it("none: [다른 그림 찾기]와 [현장 사진 올리기] 두 단추가 있고 확인 단추는 없다", async () => {
    const { user } = await open();
    await user.click(pick(4));
    expect(detail()).toHaveAttribute("data-state", "none");
    expect(within(detail()).getByRole("button", { name: "다른 그림 찾기" })).toBeInTheDocument();
    expect(within(detail()).getByRole("button", { name: "현장 사진 올리기" })).toBeInTheDocument();
    expect(within(detail()).queryByRole("button", { name: "이 그림이 맞아요" })).toBeNull();
  });

  it("none + 후보: 비슷한 후보 3장을 서버 순서 그대로 바로 펼치고, 한 번 누르면 붙어 확인함(그림 정확도 ②)", async () => {
    const t = FOUR();
    const cands = candidatesFor(t);
    // 서버가 정한 순서(직무를 만들 때 순서가 맨 앞)를 화면이 다시 섞지 않는다.
    cands.steps[3].candidates = [
      { card_id: "PACKAGING_015", url: "http://x/api/aac/images/packaging/PACKAGING_015.webp", label: "제품의 앞면을 맞춘다" },
      { card_id: "PACKAGING_028", url: "http://x/api/aac/images/packaging/PACKAGING_028.webp", label: "정상 제품을 포장 위치에 놓는다" },
      { card_id: "PACKAGING_030", url: "http://x/api/aac/images/packaging/PACKAGING_030.webp", label: "제품을 봉투 안에 넣는다" },
    ];
    m.getTask.mockResolvedValue(t);
    m.candidates.mockResolvedValue(cands);
    const user = userEvent.setup();
    await renderAt(`/manager/tasks/${t.id}`);
    await screen.findByTestId("step-detail");
    await user.click(pick(4));
    const group = await within(detail()).findByRole("group", { name: "비슷한 그림을 찾았어요. 맞는 그림을 눌러 붙여요" });
    const buttons = within(group).getAllByRole("button");
    expect(buttons.map((b) => b.getAttribute("data-candidate"))).toEqual(["PACKAGING_015", "PACKAGING_028", "PACKAGING_030"]);
    expect(buttons[0]).toHaveAccessibleName("후보 1 제품의 앞면을 맞춘다");
    // 빈 그림 칸 대신 후보를 보인다. 찾기·사진 단추는 그대로 있다.
    expect(within(detail()).queryByTestId("none-box")).toBeNull();
    expect(within(detail()).getByRole("button", { name: "다른 그림 찾기" })).toBeInTheDocument();
    m.applyPicture.mockImplementation(async () => confirmed({
      ...t.steps[3], symbol_url: cands.steps[3].candidates[0].url,
      picture: { ...cands.steps[3].candidates[0], source: "manual" },
    }));
    // 키보드로도: Tab으로 첫 후보에 초점을 두고 Enter.
    buttons[0].focus();
    await user.keyboard("{Enter}");
    expect(m.applyPicture).toHaveBeenCalledWith("task-1", "s4", cands.steps[3].candidates[0]);
    await waitFor(() => expect(row(4)).toHaveTextContent("확인함"));
  });

  it("none + 후보 없음·찾는 중: 빈 그림 칸만(후보 묶음 없음)", async () => {
    const t = FOUR();
    const cands = candidatesFor(t);
    cands.steps[3].candidates = [];
    m.getTask.mockResolvedValue(t);
    m.candidates.mockResolvedValue(cands);
    const user = userEvent.setup();
    await renderAt(`/manager/tasks/${t.id}`);
    await screen.findByTestId("step-detail");
    await user.click(pick(4));
    expect(within(detail()).getByTestId("none-box")).toBeInTheDocument();
    expect(within(detail()).queryByTestId("none-candidates")).toBeNull();
  });

  it("confirmed: 확인 단추 없이 바꾸기만(다른 후보 보기·다른 그림 찾기)", async () => {
    const { user } = await open();
    await user.click(pick(1));
    expect(within(detail()).queryByRole("button", { name: "이 그림이 맞아요" })).toBeNull();
    expect(within(detail()).getByText("다른 후보 보기")).toBeInTheDocument();
    expect(within(detail()).getByRole("button", { name: "다른 그림 찾기" })).toBeInTheDocument();
  });

  it("후보는 모든 단계를 한 번에 부르고(GET …/candidates), 실패해도 다시 부르지 않는다", async () => {
    m.candidates.mockRejectedValue(new Error("x"));
    const t = FOUR();
    m.getTask.mockResolvedValue(t);
    const user = userEvent.setup();
    await renderAt(`/manager/tasks/${t.id}`);
    await screen.findByTestId("step-detail");
    await user.click(pick(3));
    expect(await within(detail()).findByText(/후보를 불러오지 못했어요/)).toBeInTheDocument();
    expect(m.candidates).toHaveBeenCalledTimes(1);
    expect(m.stepCandidates).not.toHaveBeenCalled();
  });
});

describe("Enter로 확인", () => {
  it("상세 제목에 초점이 있을 때 Enter → 확인 API(입력칸 안의 Enter는 확인이 아니라 저장)", async () => {
    const { user } = await open();
    m.confirmPicture.mockImplementation(async () => confirmed(FOUR().steps[1]));
    const box = within(detail()).getByLabelText("문장");
    box.focus();
    await user.keyboard("{Enter}");
    expect(m.confirmPicture).not.toHaveBeenCalled();
    screen.getByRole("heading", { name: /2단계 고치기/ }).focus();
    await user.keyboard("{Enter}");
    expect(m.confirmPicture).toHaveBeenCalledTimes(1);
  });

  it("확인하면 초점은 [다음 ▶]로(남은 것이 있을 때) — body로 빠지지 않는다", async () => {
    const { user } = await open();
    m.confirmPicture.mockImplementation(async () => confirmed(FOUR().steps[1]));
    await user.click(within(detail()).getByRole("button", { name: "이 그림이 맞아요" }));
    await waitFor(() => expect(row(2)).toHaveTextContent("확인함"));
    await waitFor(() => expect(document.activeElement).toHaveAccessibleName(/다음 ▶/));
  });
});

describe("그림 찾기(PicturePicker)", () => {
  it("검색 → 결과 하나 고르기 → 적용(확인함) → 창이 닫힌다", async () => {
    const { user } = await open();
    await user.click(pick(4));
    await user.click(within(detail()).getByRole("button", { name: "다른 그림 찾기" }));
    const dlg = await screen.findByRole("dialog", { name: "4단계 그림 찾기" });
    const box = within(dlg).getByLabelText(/찾을 낱말/);
    await user.clear(box);
    await user.type(box, "건조대");
    m.searchPictures.mockResolvedValue({
      query: "건조대",
      matches: [{ asset_id: "A9", group_id: "g", job: "cafe", asset_type: "aac", label: "건조대", image_url: "http://x/api/aac/images/cafe/A9.webp", score: 0.9 }],
    });
    await user.click(within(dlg).getByRole("button", { name: "찾기" }));
    expect(m.searchPictures).toHaveBeenCalledWith("건조대");
    m.applyPicture.mockImplementation(async () => confirmed(step("s4", 4, "컵을 건조대에 엎어요.", "auto_high")));
    await user.click(await within(dlg).findByRole("button", { name: "건조대 고르기" }));
    expect(m.applyPicture).toHaveBeenCalledWith("task-1", "s4", { card_id: "A9", url: "http://x/api/aac/images/cafe/A9.webp", label: "건조대" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(row(4)).toHaveTextContent("확인함");
  });

  it("현장 사진 올리기: 안내 3줄·예시 2장·얼굴 안내 → 사진 고르기 → 올림", async () => {
    const { user } = await open();
    await user.click(pick(4));
    await user.click(within(detail()).getByRole("button", { name: "현장 사진 올리기" }));
    const dlg = await screen.findByRole("dialog", { name: "4단계 현장 사진 올리기" });
    for (const t of ["손과 물건이 크게 보이게 찍어요", "동작 하나만 찍어요", "뒤를 치워요"]) expect(dlg).toHaveTextContent(t);
    expect(dlg).toHaveTextContent("좋은 예 · 손과 물건이 크게");
    expect(dlg).toHaveTextContent("좋은 예 · 뒤가 깨끗해요");
    expect(dlg).toHaveTextContent("얼굴이 찍히지 않게 해요");
    m.uploadPhoto.mockImplementation(async () => ({ ...confirmed(FOUR().steps[3]), symbol_url: "http://x/api/media/p1?exp=1&sig=a", picture: { card_id: "p1", url: "http://x/api/media/p1", label: "", source: "photo" } }));
    const file = new File(["x"], "a.png", { type: "image/png" });
    await user.upload(within(dlg).getByTestId("photo-input"), file);
    expect(m.uploadPhoto).toHaveBeenCalledWith("task-1", "s4", file);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(within(detail()).getByRole("button", { name: "사진 빼기" })).toBeInTheDocument();
  });
});

describe("확인 대기열 · 보내기 단추", () => {
  it("'확인할 것 3개 남음' + [다음 ▶]로 다음 확인할 단계를 연다", async () => {
    const { user } = await open();
    expect(screen.getAllByText("확인할 것 3개 남음").length).toBeGreaterThan(0);
    await user.click(screen.getAllByRole("button", { name: /다음 ▶/ })[0]);
    expect(detail()).toHaveAttribute("data-step-id", "s3");
    await user.click(screen.getAllByRole("button", { name: /다음 ▶/ })[0]);
    expect(detail()).toHaveAttribute("data-step-id", "s4");
  });

  it("확인할 것이 남으면 [보내기]가 꺼져 있고 툴팁으로 이유를 알린다(누르면 열리지 않음)", async () => {
    const { user } = await open();
    const send = screen.getByTestId("editor-send");
    expect(send).toHaveAttribute("aria-disabled", "true");
    expect(send).toHaveAccessibleDescription("확인할 것 3개가 남았어요. 확인하면 보낼 수 있어요");
    await user.click(send);
    expect(sendMock.sendCheck).not.toHaveBeenCalled();
  });

  it("모두 확인한 직무는 [보내기]가 켜지고 시트를 연다", async () => {
    const t = task([step("s1", 1, "손을 씻어요.", "confirmed")]);
    sendMock.sendCheck.mockResolvedValue({ ok: true, blocking: [{ code: "no_picture", done: 1, total: 1, step_ids: [] }], warnings: [] });
    sendMock.recipients.mockResolvedValue({ last_batch_worker_ids: [], all_ever_worker_ids: [], workplace_last_batch_worker_ids: [], today_status: {} });
    const { user } = await open(t);
    await user.click(screen.getByTestId("editor-send"));
    expect(await screen.findByRole("dialog", { name: "보내기 전에 확인해요" })).toBeInTheDocument();
  });

  it("시트의 '✦ 자동으로 켠 조심 표시' 줄을 누르면 초점이 [보내기]가 아니라 그 단계의 조심 스위치로 간다(2회차 검증)", async () => {
    const t = task([step("s1", 1, "손을 씻어요.", "confirmed"), step("s2", 2, "칼을 닦아요.", "confirmed")]);
    sendMock.sendCheck.mockResolvedValue({
      ok: true,
      blocking: [{ code: "no_picture", done: 2, total: 2, step_ids: [] }],
      warnings: [{ code: "auto_caution", count: 1, step_ids: ["s2"] }],
    });
    sendMock.recipients.mockResolvedValue({ last_batch_worker_ids: [], all_ever_worker_ids: [], workplace_last_batch_worker_ids: [], today_status: {} });
    const { user } = await open(t);
    await user.click(screen.getByTestId("editor-send"));
    const sheet = await screen.findByRole("dialog", { name: "보내기 전에 확인해요" });
    await user.click(await within(sheet).findByRole("button", { name: /자동으로 켠 조심 표시가 1개 있어요 · 그 단계로 가기/ }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "보내기 전에 확인해요" })).toBeNull());
    expect(detail()).toHaveAttribute("data-step-id", "s2");
    await waitFor(() => expect(document.activeElement).toBe(within(detail()).getByRole("switch")));
    await new Promise((r) => setTimeout(r, 30));
    expect(document.activeElement).toBe(within(detail()).getByRole("switch"));
  });

  it("?review=1이면 첫 확인 단계, ?step=이면 그 단계를 연다(목록 [다시 보내기]·홈 딥링크)", async () => {
    await open(FOUR(), "/manager/tasks/task-1?step=s4");
    expect(detail()).toHaveAttribute("data-step-id", "s4");
  });
});

describe("문장: 자동 저장 · 칸 벗어나면 마무리 · 나누기 + 되돌리기", () => {
  it("고치고 600ms 멈추면 문장만 저장(defer_media, expected_updated_at) — 저장 표시 '저장하는 중…' → '저장됨 · 방금'", async () => {
    const { user } = await open();
    let resolve!: (s: EditorStep) => void;
    m.patchStep.mockImplementation(() => new Promise((r) => (resolve = r)));
    const box = within(detail()).getByLabelText("문장");
    await user.clear(box);
    await user.type(box, "컵을 물에 담가요.");
    expect(m.patchStep).not.toHaveBeenCalled();
    await waitFor(() => expect(m.patchStep).toHaveBeenCalledTimes(1), { timeout: 2000 });
    expect(m.patchStep).toHaveBeenCalledWith("task-1", "s2", { sentence: "컵을 물에 담가요.", defer_media: true, expected_updated_at: T0 });
    expect(screen.getByTestId("save-indicator")).toHaveTextContent("저장하는 중…");
    await act(async () => resolve({ ...FOUR().steps[1], sentence: "컵을 물에 담가요.", task_updated_at: "2026-11-10T01:09:00" }));
    await waitFor(() => expect(screen.getByTestId("save-indicator")).toHaveTextContent("저장됨 · 방금"));
    expect(m.rewriteStep).not.toHaveBeenCalled();
  });

  it("저장하지 못하면 '저장하지 못했어요 · 다시 시도' — [다시 시도]를 누르면(칸을 벗어나며) 다시 저장한다", async () => {
    const { user } = await open();
    m.patchStep.mockRejectedValueOnce(new ApiError(500, "저장하지 못했어요. 잠시 뒤 다시 해 주세요."));
    const box = within(detail()).getByLabelText("문장");
    await user.type(box, "!");
    await waitFor(() => expect(screen.getByTestId("save-indicator")).toHaveTextContent(/저장하지 못했어요.*다시 시도/), { timeout: 2000 });
    expect(screen.getByTestId("save-indicator")).toHaveAttribute("data-status", "error");
    m.rewriteStep.mockResolvedValue({ task: { ...FOUR(), steps: FOUR().steps.map((x) => (x.id === "s2" ? { ...x, sentence: "컵을 물에 넣어요.!" } : x)) }, split_step_ids: [], sentence: "컵을 물에 넣어요.!" });
    await user.click(within(screen.getByTestId("save-indicator")).getByRole("button", { name: "다시 시도" }));
    await waitFor(() => expect(m.rewriteStep).toHaveBeenCalledWith("task-1", "s2", "컵을 물에 넣어요.!", expect.any(String)));
    await waitFor(() => expect(screen.getByTestId("save-indicator")).toHaveAttribute("data-status", "saved"));
  });

  it("칸 밖에서 [다시 시도]를 누르면 실패한 저장을 그대로 다시 보낸다", async () => {
    const t = FOUR();
    const { user } = await open(t);
    m.patchStep.mockRejectedValueOnce(new ApiError(500, "저장하지 못했어요."));
    await user.click(within(detail()).getByRole("switch", { name: /조심 표시/ }));
    await waitFor(() => expect(screen.getByTestId("save-indicator")).toHaveAttribute("data-status", "error"));
    m.patchStep.mockResolvedValueOnce({ ...t.steps[1], safety_flag: true, safety: { flag: true, source: "manual", note: "" } });
    await user.click(within(screen.getByTestId("save-indicator")).getByRole("button", { name: "다시 시도" }));
    await waitFor(() => expect(m.patchStep).toHaveBeenCalledTimes(2));
    expect(m.patchStep.mock.calls[1]).toEqual(m.patchStep.mock.calls[0]);
    await waitFor(() => expect(screen.getByTestId("save-indicator")).toHaveAttribute("data-status", "saved"));
  });

  it("칸을 벗어나면 rewrite로 마무리하고, 동작이 둘이면 경고 없이 두 단계로 나눠 [되돌리기]를 보인다", async () => {
    const { user } = await open();
    const base = FOUR();
    const a = step("n1", 2, "컵을 물에 넣어요.", "auto_high");
    const b = step("n2", 3, "컵을 꺼내요.", "auto_high");
    m.rewriteStep.mockResolvedValue({
      task: { ...base, steps: [base.steps[0], a, b, ...base.steps.slice(2)].map((s, i) => ({ ...s, order: i + 1 })) },
      split_step_ids: ["n1", "n2"],
      sentence: "컵을 물에 넣고 꺼내요.",
    });
    const box = within(detail()).getByLabelText("문장");
    await user.clear(box);
    await user.type(box, "컵을 물에 넣고 꺼내요.");
    await user.tab();
    await waitFor(() => expect(m.rewriteStep).toHaveBeenCalledWith("task-1", "s2", "컵을 물에 넣고 꺼내요.", expect.any(String)));
    expect(await screen.findByText("두 단계로 나눴어요")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/동작이 2개|동작이 둘/);
    m.mergeSteps.mockResolvedValue(base);
    await user.click(screen.getByRole("button", { name: "되돌리기" }));
    expect(m.mergeSteps).toHaveBeenCalledWith("task-1", ["n1", "n2"], "컵을 물에 넣고 꺼내요.", "other");
    await waitFor(() => expect(screen.queryByText("두 단계로 나눴어요")).toBeNull());
  });

  it("같은 문장이면 칸을 지나가도 다시 저장하지 않는다(확인·후보 그대로)", async () => {
    const { user } = await open();
    within(detail()).getByLabelText("문장").focus();
    await user.tab();
    expect(m.rewriteStep).not.toHaveBeenCalled();
    expect(m.patchStep).not.toHaveBeenCalled();
  });

  it("자동 저장만 하고 칸을 벗어나면(같은 문장이어도) rewrite로 목소리·나누기를 마무리한다", async () => {
    const { user } = await open();
    m.patchStep.mockImplementation(async (_t: string, _s: string, body: { sentence: string }) => ({ ...FOUR().steps[1], sentence: body.sentence }));
    const box = within(detail()).getByLabelText("문장");
    await user.type(box, "!");
    await waitFor(() => expect(m.patchStep).toHaveBeenCalled(), { timeout: 2000 });
    m.rewriteStep.mockResolvedValue({ task: FOUR(), split_step_ids: [], sentence: "컵을 물에 넣어요.!" });
    await user.tab();
    await waitFor(() => expect(m.rewriteStep).toHaveBeenCalledWith("task-1", "s2", "컵을 물에 넣어요.!", expect.any(String)));
  });

  it("문장을 비우면 저장하지 않고 '문장이 비어 있어요'", async () => {
    const { user } = await open();
    const box = within(detail()).getByLabelText("문장");
    await user.clear(box);
    await user.tab();
    expect(within(detail()).getByRole("alert")).toHaveTextContent("문장이 비어 있어요");
    expect(m.rewriteStep).not.toHaveBeenCalled();
  });

  it("다른 창에서 먼저 고쳤으면(409) 오류 토스트 + [새로 불러오기]", async () => {
    const { user } = await open();
    m.patchStep.mockRejectedValue(new ApiError(409, "다른 창에서 먼저 고쳤어요. 새로 불러온 뒤 다시 고쳐 주세요."));
    await user.type(within(detail()).getByLabelText("문장"), "!");
    expect(await screen.findByText("다른 창에서 먼저 고쳤어요. 새로 불러온 뒤 다시 고쳐 주세요.", {}, { timeout: 2000 })).toBeInTheDocument();
    const before = m.getTask.mock.calls.length;
    await user.click(screen.getByRole("button", { name: "새로 불러오기" }));
    await waitFor(() => expect(m.getTask.mock.calls.length).toBe(before + 1));
  });
});

describe("문장 점검 칩", () => {
  it("20자가 넘어요 · 어려운 말: 적재 → 쌓기 · ~해요 체로 바꾸기 — 눌러서 바로 고친다('동작이 2개'는 없다)", async () => {
    const t = task([
      step("s1", 1, "상자를 선반에 적재하고 라벨을 붙이세요", "auto_high", {
        lint: [
          { code: "too_long", from: null, to: null },
          { code: "hard_word", from: "적재", to: "쌓기" },
          { code: "command_tone", from: null, to: null },
        ],
      }),
    ]);
    const { user } = await open(t);
    const lint = within(detail()).getByTestId("sentence-lint");
    expect(lint).toHaveTextContent("20자가 넘어요");
    expect(lint).toHaveTextContent("어려운 말: 적재 → 쌓기");
    expect(lint).toHaveTextContent("~해요 체로 바꾸기");
    m.rewriteStep.mockResolvedValue({ task: t, split_step_ids: [], sentence: "" });
    await user.click(within(lint).getByRole("button", { name: "어려운 말: 적재 → 쌓기" }));
    expect(m.rewriteStep).toHaveBeenLastCalledWith("task-1", "s1", "상자를 선반에 쌓기하고 라벨을 붙이세요", expect.any(String));
    expect(document.body.textContent).not.toMatch(/동작이 2개/);
  });
});

describe("순서 바꾸기", () => {
  it("키보드: 손잡이에서 Space로 들고 ↑ 한 번, Space로 놓으면 순서 저장(화면 읽기 알림 포함)", async () => {
    const { user } = await open();
    m.reorderSteps.mockImplementation(async (_t: string, ids: string[]) => ({ ...FOUR(), steps: ids.map((id, i) => ({ ...FOUR().steps.find((s) => s.id === id)!, order: i + 1 })) }));
    const handle = screen.getByRole("button", { name: "2단계 순서 바꾸기" });
    handle.focus();
    await user.keyboard(" ");
    expect(screen.getByTestId("reorder-live")).toHaveTextContent("2단계를 들었어요");
    await user.keyboard("{ArrowUp}");
    expect(screen.getByTestId("reorder-live")).toHaveTextContent("1번째 자리예요");
    await user.keyboard(" ");
    expect(m.reorderSteps).toHaveBeenCalledWith("task-1", ["s2", "s1", "s3", "s4"]);
    expect(screen.getByTestId("reorder-live")).toHaveTextContent("1번째 자리에 놓았어요");
  });

  it("Esc를 누르면 그대로 두고 저장하지 않는다", async () => {
    const { user } = await open();
    screen.getByRole("button", { name: "3단계 순서 바꾸기" }).focus();
    await user.keyboard(" {ArrowDown}{Escape}");
    expect(m.reorderSteps).not.toHaveBeenCalled();
    expect(screen.getByTestId("reorder-live")).toHaveTextContent("순서를 그대로 뒀어요");
  });

  it("[↑][↓] 단추는 없다 — 순서는 손잡이로만 바꾼다", async () => {
    await open();
    expect(screen.queryByRole("button", { name: /단계 위로$/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /단계 아래로$/ })).toBeNull();
    expect(screen.getByRole("button", { name: "3단계 순서 바꾸기" })).toBeInTheDocument();
  });
});

describe("✦ 표시와 조심 스위치", () => {
  it("✦는 확인하지 않은 자동 결과에만 — 그림을 확인하면 개수가 줄어든다", async () => {
    const t = sixAutoHigh();
    const { user } = await open(t);
    const before = sparkleCount();
    m.confirmPicture.mockImplementation(async (_t: string, sid: string) => confirmed(t.steps.find((s) => s.id === sid)!));
    await user.click(within(detail()).getByRole("button", { name: "이 그림이 맞아요" }));
    await waitFor(() => expect(row(1)).toHaveTextContent("확인함"));
    expect(sparkleCount()).toBeLessThan(before);
  });

  it("확인한 자동 그림(서버는 source='auto' 그대로)의 상세 설명에도 ✦가 없다(1회차 검증)", async () => {
    const t = sixAutoHigh();
    const { user } = await open(t);
    expect(within(detail()).getByText(/✦ 자동으로 고른 그림/)).toBeInTheDocument();
    m.confirmPicture.mockImplementation(async (_t: string, sid: string) => ({
      ...t.steps.find((s) => s.id === sid)!, picture_state: "confirmed" as const, task_updated_at: "2026-11-10T01:05:00",
    }));
    await user.click(within(detail()).getByRole("button", { name: "이 그림이 맞아요" }));
    await waitFor(() => expect(row(1)).toHaveTextContent("확인함"));
    const caption = detail().querySelector("figcaption");
    expect(caption).toHaveTextContent("확인한 그림");
    expect(caption?.textContent ?? "").not.toContain("✦");
  });

  it("자동으로 켠 조심 표시는 '✦ 자동 제안'(보라) — 스위치를 바꾸면 사업주가 정한 것(manual)이 되어 ✦가 사라진다", async () => {
    const t = sixAutoHigh();
    const { user } = await open(t);
    expect(within(detail()).getByText("✦ 자동 제안")).toBeInTheDocument();
    const sw = within(detail()).getByRole("switch", { name: /조심 표시/ });
    expect(sw).toHaveAttribute("aria-checked", "true");
    m.patchStep.mockImplementation(async () => ({ ...t.steps[0], safety_flag: true, safety: { flag: true, source: "manual", note: "" } }));
    await user.click(sw);
    expect(m.patchStep).toHaveBeenCalledWith("task-1", "s1", { safety_flag: false, expected_updated_at: T0 });
    await waitFor(() => expect(within(detail()).queryByText("✦ 자동 제안")).toBeNull());
  });

  it("화면에 'AI' 글자가 없다", async () => {
    await open(sixAutoHigh());
    expect(document.body.textContent).not.toMatch(/\bAI\b/);
  });
});

describe("단계 지우기 · 목소리 · 버전 안내", () => {
  it("[이 단계 지우기] → 위험 창 '2단계를 지울까요?' → [지우기]", async () => {
    const { user } = await open();
    await user.click(within(detail()).getByRole("button", { name: "이 단계 지우기" }));
    const dlg = await screen.findByRole("alertdialog", { name: "2단계를 지울까요?" });
    const t = FOUR();
    m.deleteStep.mockResolvedValue({ ...t, steps: t.steps.filter((s) => s.id !== "s2") });
    await user.click(within(dlg).getByRole("button", { name: "지우기" }));
    expect(m.deleteStep).toHaveBeenCalledWith("task-1", "s2");
    await waitFor(() => expect(screen.queryAllByTestId(/^step-row-/)).toHaveLength(3));
  });

  it("[목소리 듣기]: 음성이 없으면 그때 만든다(…/tts) — 못 만들면 이 기기 음성으로 읽는다", async () => {
    const { user } = await open();
    m.stepTts.mockResolvedValue({ tts_url: null });
    await user.click(within(detail()).getByTestId("voice-button"));
    expect(m.stepTts).toHaveBeenCalledWith("task-1", "s2");
    expect(await within(detail()).findByText("목소리를 만들지 못해 이 기기 음성으로 읽어요")).toBeInTheDocument();
  });

  it("보낸 직무: '이 직무를 받은 3명 중 1명이 지금 하고 있어요' · '다음에 보낼 때부터 바뀌어요'", async () => {
    await open(task(FOUR().steps, { status: "published", version: { current_no: 2, has_unsent_changes: true }, recipients_count: 3, in_progress_count: 1 }));
    const notice = screen.getByTestId("version-notice");
    expect(notice).toHaveTextContent("이 직무를 받은 3명 중 1명이 지금 하고 있어요");
    expect(notice).toHaveTextContent("다음에 보낼 때부터 바뀌어요");
  });

  it("보낸 직무: 하는 사람이 0명이고 고친 것이 없으면 받은 사람 수만 보이고 '바뀌어요'는 없다(2회차 검증)", async () => {
    await open(task(FOUR().steps, { status: "published", version: { current_no: 1, has_unsent_changes: false }, recipients_count: 2, in_progress_count: 0 }));
    expect(screen.getByTestId("version-notice")).toHaveTextContent(/^이 직무를 받은 사람이 2명 있어요$/);
  });

  it("제목은 그 자리에서 고친다(Enter 저장)", async () => {
    const { user } = await open();
    tasksMock.renameTask.mockResolvedValue({ id: "task-1", title: "상자 정리하기", status: "draft", steps: [], updated_at: "2026-11-10T02:00:00" });
    await user.click(screen.getByRole("button", { name: "제목 고치기 · 상자 정리" }));
    const box = screen.getByRole("textbox", { name: "직무 제목" });
    await user.clear(box);
    await user.type(box, "상자 정리하기{Enter}");
    expect(tasksMock.renameTask).toHaveBeenCalledWith("task-1", "상자 정리하기");
    expect(await screen.findByRole("heading", { level: 1, name: "상자 정리하기" })).toBeInTheDocument();
  });

  it("서명 URL이 만료돼 그림을 못 불러오면 직무를 한 번 다시 받는다", async () => {
    const t = task([step("s1", 1, "손을 씻어요.", "confirmed", { symbol_url: "http://x/api/media/p1?exp=1&sig=a" })]);
    await open(t);
    const calls = m.getTask.mock.calls.length;
    fireEvent.error(detail().querySelector("img")!);
    await waitFor(() => expect(m.getTask.mock.calls.length).toBe(calls + 1));
  });
});
