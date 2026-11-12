import { describe, expect, it } from "vitest";
import type { SplitPreviewStep } from "../../src/api";
import {
  addRow, deleteRow, editRow, emptyRows, mergeRows, mergeTarget, rowsFromPreview, splitRow, toConfirmed,
} from "../../src/manager/tasks/new/splitRows";

const SOURCE = "컵 씻어서 건조대에 올려 놔";

function step(order: number, sentence: string, extra: Partial<SplitPreviewStep> = {}): SplitPreviewStep {
  return {
    order, sentence, action_type: "other", symbol_query: [], split_group: null, split_check: false,
    source_text: null, ...extra,
  };
}

const PREVIEW = [
  step(1, "앞치마를 입어요.", { action_type: "wear", symbol_query: ["앞치마"] }),
  step(2, "컵을 씻어요.", { split_group: 1, split_check: true, source_text: SOURCE, symbol_query: ["컵"] }),
  step(3, "컵을 건조대에 올려요.", { split_group: 1, split_check: true, source_text: SOURCE }),
];

describe("splitRows — 입력 화면 나눈 줄", () => {
  it("미리보기를 줄로 바꾼다(노란 줄·원래 문장·검색어 유지)", () => {
    const rows = rowsFromPreview(PREVIEW);
    expect(rows.map((r) => r.text)).toEqual(["앞치마를 입어요.", "컵을 씻어요.", "컵을 건조대에 올려요."]);
    expect(rows.map((r) => r.check)).toEqual([false, true, true]);
    expect(rows[1].source).toBe(SOURCE);
    expect(new Set(rows.map((r) => r.key)).size).toBe(3);
  });

  it("합치기 상대는 같은 원래 절의 이웃이고, 확실한 줄에는 없다", () => {
    const rows = rowsFromPreview(PREVIEW);
    expect(mergeTarget(rows, 0)).toBeNull();
    expect(mergeTarget(rows, 1)).toBe(2);
    expect(mergeTarget(rows, 2)).toBe(1);
    // 다른 절이면 노란 줄이라도 합치지 않는다
    const other = rowsFromPreview([step(1, "a", { split_group: 1, split_check: true }),
                                   step(2, "b", { split_group: 2, split_check: true })]);
    expect(mergeTarget(other, 0)).toBeNull();
  });

  it("한 원래 문장에서 나온 줄을 모두 합치면 그 원래 문장 한 줄이 되고 노란 표시가 사라진다", () => {
    const rows = rowsFromPreview(PREVIEW);
    const out = mergeRows(rows, 2);
    // 두 문장을 잇지 않는다("컵을 씻어요. 컵을 건조대에 올려요."가 한 단계로 읽히지 않게)
    expect(out.rows.map((r) => r.text)).toEqual(["앞치마를 입어요.", SOURCE]);
    expect(out.rows[1].check).toBe(false);
    expect(out.rows[1].group).toBeNull();
    expect(out.focus).toBe(1);
    expect(out.select).toBe(false);
    // 합친 줄은 사업주가 만든 문장 — AI 검색어를 보내지 않는다
    expect(toConfirmed(out.rows)[1]).toEqual({ sentence: SOURCE });
  });

  it("일부만 합치면 두 문장을 잇고 글 전체를 선택하라고 알린다(다듬게)", () => {
    const three = "컵을 씻고 행주로 닦아 건조대에 올려요";
    const rows = rowsFromPreview([
      step(1, "컵을 씻어요.", { split_group: 1, split_check: true, source_text: three }),
      step(2, "컵을 행주로 닦아요.", { split_group: 1, split_check: true, source_text: three }),
      step(3, "컵을 건조대에 올려요.", { split_group: 1, split_check: true, source_text: three }),
    ]);
    const out = mergeRows(rows, 0);
    expect(out.rows.map((r) => r.text)).toEqual(["컵을 씻어요. 컵을 행주로 닦아요.", "컵을 건조대에 올려요."]);
    expect(out.select).toBe(true);
    expect(out.rows[0].group).toBe(1);
  });

  it("원래 문장이 없으면 두 문장을 잇는다", () => {
    const rows = rowsFromPreview([step(1, "a 해요.", { split_group: 1, split_check: true }),
                                  step(2, "b 해요.", { split_group: 1, split_check: true })]);
    const out = mergeRows(rows, 0);
    expect(out.rows.map((r) => r.text)).toEqual(["a 해요. b 해요."]);
    expect(out.select).toBe(true);
  });

  it("더 나누기: 커서 자리에서 자르고, 커서가 없으면 아래에 빈 줄을 만든다", () => {
    const rows = rowsFromPreview([step(1, "송장을 붙이고 바코드를 찍어요")]);
    const cut = splitRow(rows, 0, "송장을 붙이고".length);
    expect(cut.rows.map((r) => r.text)).toEqual(["송장을 붙이고", "바코드를 찍어요"]);
    expect(cut.focus).toBe(1);
    const blank = splitRow(rows, 0, null);
    expect(blank.rows.map((r) => r.text)).toEqual(["송장을 붙이고 바코드를 찍어요", ""]);
    expect(emptyRows(blank.rows)).toEqual([1]);
    // 커서가 맨 끝이어도 빈 줄
    expect(splitRow(rows, 0, rows[0].text.length).rows[1].text).toBe("");
  });

  it("고치기·지우기·줄 추가, 마지막 한 줄은 지우지 않는다", () => {
    let rows = rowsFromPreview(PREVIEW);
    rows = editRow(rows, 0, "앞치마를 입으세요.");
    expect(rows[0].text).toBe("앞치마를 입으세요.");
    const del = deleteRow(rows, 2);
    expect(del.rows).toHaveLength(2);
    expect(del.focus).toBe(1);
    const one = rowsFromPreview([step(1, "a")]);
    expect(deleteRow(one, 0).rows).toHaveLength(1);
    const added = addRow(one);
    expect(added.rows.map((r) => r.text)).toEqual(["a", ""]);
    expect(added.focus).toBe(1);
  });

  it("확인 목록: 고치지 않은 줄만 동작 종류를, AI 줄은 고쳐도 그림 검색어를 보낸다", () => {
    let rows = rowsFromPreview(PREVIEW);
    rows = editRow(rows, 1, "컵을 깨끗이 씻어요.");
    rows = editRow(rows, 2, "컵을 건조대에 엎어요.");
    expect(toConfirmed(rows)).toEqual([
      { sentence: "앞치마를 입어요.", action_type: "wear", symbol_query: ["앞치마"] },
      // (그림 정확도 ③) 문장만 고친 AI 줄은 AI 그림 검색어를 그대로 보낸다. 동작 종류는 서버가 다시 매긴다.
      { sentence: "컵을 깨끗이 씻어요.", symbol_query: ["컵"] },
      // AI 검색어가 없던 줄은 고쳐도 문장만 간다.
      { sentence: "컵을 건조대에 엎어요." },
    ]);
  });

  it("더 나눈 줄은 AI 검색어를 보내지 않는다(사업주가 만든 줄)", () => {
    const out = splitRow(rowsFromPreview(PREVIEW), 1, 3);
    expect(toConfirmed(out.rows).slice(1, 3)).toEqual([{ sentence: "컵을" }, { sentence: "씻어요." }]);
  });
});

describe("2차 검증 — 상한과 오류 문장", () => {
  it("줄 수·한 줄 글자 수·합계 상한을 넘으면 한국어로 알려 준다", async () => {
    const { limitError, MAX_ROWS } = await import("../../src/manager/tasks/new/splitRows");
    const rows = (n: number, text = "컵을 씻어요.") => rowsFromPreview(
      Array.from({ length: n }, (_, i) => step(i + 1, text)));
    expect(limitError(rows(MAX_ROWS))).toBeNull();
    expect(limitError(rows(MAX_ROWS + 1))).toMatch(/30줄까지/);
    expect(limitError(rows(1, "가".repeat(501)))).toMatch(/1단계가 너무 길어요/);
    expect(limitError(rows(6, "가".repeat(450)))).toMatch(/2500자까지/);
  });

  it("오류 응답 detail이 문자열이 아니면 '[object Object]' 대신 한국어 문장을 쓴다", async () => {
    const { errorDetail } = await import("../../src/api");
    expect(errorDetail({ detail: [{ loc: ["body"], msg: "x" }] }, 422)).toBe("입력한 내용을 다시 확인해 주세요.");
    expect(errorDetail({ detail: "단계는 30줄까지" }, 422)).toBe("단계는 30줄까지");
    expect(errorDetail({}, 500)).toBe("요청 실패 (500)");
  });
});
