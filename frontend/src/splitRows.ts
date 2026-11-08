// 입력 화면 "단계로 나누기" 결과 목록의 순수 상태 함수들(한 줄 = 한 동작 = 그림 1장).
// 화면(SplitPreviewList)과 분리해 두어 합치기·더 나누기·고치기·지우기를 단위 테스트로 확인한다.
import type { ConfirmedStep, SplitPreviewStep } from "./api";

export interface SplitRow {
  /** 화면 key·초점 이동용. 서버 id가 아니다. */
  key: string;
  text: string;
  /** 같은 원래 절에서 나온 줄끼리 같은 번호(합치기 상대를 찾는 데 쓴다). */
  group: number | null;
  /** 나눈 곳이 애매한 줄 — 노랗게 칠하고 [합치기]를 띄운다. */
  check: boolean;
  /** 이 줄이 나온 원래 절(사업주가 판단할 때 보도록 노란 줄에 보여 준다). */
  source: string | null;
  /** AI가 준 문장. 사업주가 고치지 않았을 때만 AI 검색어(symbolQuery)를 그대로 보낸다. */
  original: string;
  actionType: string;
  symbolQuery: string[] | null;
}

let seq = 0;
function nextKey(): string {
  seq += 1;
  return `row-${seq}`;
}

export function rowsFromPreview(steps: SplitPreviewStep[]): SplitRow[] {
  return steps.map((s) => ({
    key: nextKey(),
    text: s.sentence,
    group: s.split_group,
    check: s.split_check,
    source: s.source_text,
    original: s.sentence,
    actionType: s.action_type || "other",
    symbolQuery: s.symbol_query?.length ? s.symbol_query : null,
  }));
}

/** 사업주가 만든 줄(고친 문장·더 나누기·합치기). AI 검색어·동작 종류는 쓰지 않는다 — 서버가 문장에서 다시 뽑는다. */
function userRow(text: string, base: Pick<SplitRow, "group" | "source">): SplitRow {
  return {
    key: nextKey(), text, group: base.group, check: false, source: base.source,
    original: "", actionType: "other", symbolQuery: null,
  };
}

/**
 * [합치기] 상대. 노란 줄이고 같은 원래 절(split_group)에서 나온 이웃이 있을 때만 있다.
 * 다음 줄을 먼저 보고(나눈 앞 동작 → 뒤 동작), 없으면 앞 줄과 합친다.
 */
export function mergeTarget(rows: SplitRow[], i: number): number | null {
  const row = rows[i];
  if (!row || !row.check || row.group === null) return null;
  if (rows[i + 1]?.group === row.group) return i + 1;
  if (rows[i - 1]?.group === row.group) return i - 1;
  return null;
}

function joinText(a: string, b: string): string {
  const left = a.trim();
  const right = b.trim();
  if (!left) return right;
  if (!right) return left;
  return `${left} ${right}`;
}

/**
 * i번째 줄을 합치기 상대와 한 줄로 합친다. 합친 줄은 사업주가 정한 것이라 더는 노랗게 칠하지 않는다.
 * 같은 원래 절에서 나온 줄을 모두 합쳤으면 두 문장을 잇지 않고 그 원래 문장(source)으로 되돌린다 — 한 줄이 두
 * 문장("컵을 씻어요. 컵을 건조대에 올려요.")이 되어 그대로 근로자에게 읽히지 않게. 일부만 합쳤으면 이은 글을 두고
 * select로 알려, 화면이 글 전체를 선택해 사업주가 한 문장으로 다듬게 한다.
 */
export function mergeRows(
  rows: SplitRow[], i: number,
): { rows: SplitRow[]; focus: number; select?: boolean } {
  const j = mergeTarget(rows, i);
  if (j === null) return { rows, focus: i };
  const lo = Math.min(i, j);
  const row = rows[lo];
  const rest = rows.filter((r, k) => k !== lo && k !== lo + 1 && r.group === row.group);
  const whole = rest.length === 0 && !!row.source?.trim();
  const text = whole ? row.source!.trim() : joinText(row.text, rows[lo + 1].text);
  const merged = userRow(text, rest.length === 0 ? { group: null, source: null } : row);
  return { rows: [...rows.slice(0, lo), merged, ...rows.slice(lo + 2)], focus: lo, select: !whole };
}

/**
 * [더 나누기] — i번째 줄을 두 줄로 나눈다. at이 문장 중간(커서 위치)이면 그 자리에서 자르고,
 * 아니면 아래에 빈 줄을 하나 만들어 사업주가 두 번째 동작을 적게 한다. 초점은 새 둘째 줄로 간다.
 */
export function splitRow(rows: SplitRow[], i: number, at?: number | null): { rows: SplitRow[]; focus: number } {
  const row = rows[i];
  if (!row) return { rows, focus: i };
  const text = row.text;
  let first = text;
  let second = "";
  if (at != null && at > 0 && at < text.length) {
    first = text.slice(0, at).trim();
    second = text.slice(at).trim();
  }
  const a = first === row.text ? { ...row, check: false } : userRow(first, row);
  const b = userRow(second, row);
  return { rows: [...rows.slice(0, i), a, b, ...rows.slice(i + 1)], focus: i + 1 };
}

export function editRow(rows: SplitRow[], i: number, text: string): SplitRow[] {
  return rows.map((r, k) => (k === i ? { ...r, text } : r));
}

/** 줄을 지운다. 마지막 한 줄은 지우지 않는다(직무에는 단계가 하나 이상 있어야 한다). */
export function deleteRow(rows: SplitRow[], i: number): { rows: SplitRow[]; focus: number } {
  if (rows.length <= 1) return { rows, focus: 0 };
  const next = rows.filter((_, k) => k !== i);
  return { rows: next, focus: Math.min(i, next.length - 1) };
}

export function addRow(rows: SplitRow[]): { rows: SplitRow[]; focus: number } {
  return { rows: [...rows, userRow("", { group: null, source: null })], focus: rows.length };
}

/** 문장이 비어 있는 줄 번호(0부터). */
export function emptyRows(rows: SplitRow[]): number[] {
  return rows.flatMap((r, i) => (r.text.trim() ? [] : [i]));
}

/** 서버로 보낼 확인한 단계 목록. 고치지 않은 줄만 AI 검색어·동작 종류를 함께 보낸다. */
export function toConfirmed(rows: SplitRow[]): ConfirmedStep[] {
  return rows.map((r) => {
    const sentence = r.text.trim();
    const untouched = sentence === r.original.trim() && r.original !== "";
    return untouched
      ? { sentence, action_type: r.actionType, symbol_query: r.symbolQuery }
      : { sentence };
  });
}

// 확인한 단계 목록의 상한 — 서버(backend/schemas.py MAX_CONFIRMED_STEPS·MAX_STEP_SENTENCE·MAX_CONFIRMED_TOTAL)와 같은 값.
// 넘으면 서버가 422를 돌려주므로 [이대로 그림 고르기] 전에 막는다(2차 검증).
export const MAX_ROWS = 30;
export const MAX_ROW_CHARS = 500;
export const MAX_TOTAL_CHARS = 2500;

/** 상한을 넘었으면 사업주에게 보일 문장, 아니면 null. */
export function limitError(rows: SplitRow[]): string | null {
  if (rows.length > MAX_ROWS) {
    return `단계는 ${MAX_ROWS}줄까지 만들 수 있어요. 지금 ${rows.length}줄이에요. 줄을 합치거나 지워 주세요.`;
  }
  const long = rows.flatMap((r, i) => (r.text.trim().length > MAX_ROW_CHARS ? [i] : []));
  if (long.length) {
    return `${long.map((i) => `${i + 1}단계`).join(", ")}가 너무 길어요. 한 줄은 ${MAX_ROW_CHARS}자까지예요.`;
  }
  const total = rows.reduce((n, r) => n + r.text.trim().length, 0);
  if (total > MAX_TOTAL_CHARS) {
    return `단계 문장이 모두 ${total}자예요. ${MAX_TOTAL_CHARS}자까지 쓸 수 있어요. 줄을 줄이거나 지워 주세요.`;
  }
  return null;
}
