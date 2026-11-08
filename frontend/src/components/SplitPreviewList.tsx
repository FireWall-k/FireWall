import { useEffect, useRef, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { cn } from "../cn";
import {
  addRow, deleteRow, editRow, emptyRows, mergeRows, mergeTarget, splitRow, type SplitRow,
} from "../splitRows";

// 입력 화면에서 [단계로 나누기] 바로 아래에 펼치는 단계 목록(한 줄 = 한 동작 = 그림 1장).
// 나누기는 여기서 끝낸다 — 편집기에는 '동작이 2개예요' 알림이 없다. 애매하게 나눈 줄만 노랗게 칠하고
// [합치기]를 띄우며, 어느 줄이든 [더 나누기]·고치기·지우기를 할 수 있다. [이대로 그림 고르기]를 눌러야
// 초안이 만들어지고 그림을 고르러 간다.

// 사업주 화면 버튼은 44px 이상(min-h-11), 키보드 초점은 파란 테두리로 보인다.
const BTN = cn(
  "inline-flex min-h-11 items-center justify-center gap-1 rounded-lg px-3 text-sm font-semibold",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2",
  "disabled:cursor-not-allowed disabled:opacity-50",
);

interface Props {
  rows: SplitRow[];
  onChange: (rows: SplitRow[]) => void;
  onConfirm: () => void;
  confirming: boolean;
  /** 목록을 만든 뒤 직무 내용(원문)을 고쳤는지 — 고쳤으면 다시 나누라고 알려 준다. */
  stale: boolean;
}

export default function SplitPreviewList({ rows, onChange, onConfirm, confirming, stale }: Props) {
  const inputs = useRef<Map<string, HTMLInputElement>>(new Map());
  // 다음 렌더 뒤 초점을 줄 줄(합치기·나누기·지우기 뒤). 상태가 아니라 ref로 두고, 렌더가 끝나면 한 번 쓰고 비운다.
  const pendingFocus = useRef<{ key: string; caret?: number } | null>(null);
  const [emptyError, setEmptyError] = useState<string | null>(null);

  useEffect(() => {
    const want = pendingFocus.current;
    if (!want) return;
    pendingFocus.current = null;
    const el = inputs.current.get(want.key);
    if (el) {
      el.focus();
      if (want.caret !== undefined) el.setSelectionRange(want.caret, want.caret);
    }
  });

  const setFocusKey = (want: { key: string; caret?: number }) => {
    pendingFocus.current = want;
  };

  const apply = (next: { rows: SplitRow[]; focus: number }, caret?: number) => {
    onChange(next.rows);
    const target = next.rows[next.focus];
    if (target) setFocusKey({ key: target.key, caret });
    setEmptyError(null);
  };

  const checkCount = rows.filter((r) => r.check).length;

  function handleConfirm() {
    const empty = emptyRows(rows);
    if (empty.length) {
      setEmptyError(`${empty.map((i) => `${i + 1}단계`).join(", ")}가 비어 있어요. 문장을 적거나 그 줄을 지워 주세요.`);
      inputs.current.get(rows[empty[0]].key)?.focus();
      return;
    }
    setEmptyError(null);
    onConfirm();
  }

  return (
    <section aria-labelledby="split-preview-title" className="mt-4 rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="split-preview-title" className="break-keep text-lg font-bold text-slate-900">
          이렇게 나눴어요 <span className="text-sm font-normal text-slate-600">({rows.length}단계)</span>
        </h2>
        <p className="break-keep text-sm text-slate-600">한 줄에 동작 하나, 그림 한 장</p>
      </div>
      {checkCount > 0 && (
        <p className="mt-2 break-keep rounded-lg bg-amber-50 p-2 text-sm text-amber-900">
          노란 줄 {checkCount}개는 나눈 곳이 애매해요. 맞으면 그대로 두고, 아니면 [합치기]나 [더 나누기]를 눌러 주세요.
        </p>
      )}
      {stale && (
        <p role="status" className="mt-2 break-keep rounded-lg bg-slate-100 p-2 text-sm text-slate-700">
          직무 내용을 고쳤어요. 새로 나누려면 [단계로 나누기]를 다시 눌러 주세요.
        </p>
      )}

      <ol className="mt-3 space-y-2">
        {rows.map((row, i) => {
          const n = i + 1;
          const target = mergeTarget(rows, i);
          return (
            <li
              key={row.key}
              data-testid={`split-row-${n}`}
              data-check={row.check ? "true" : "false"}
              className={cn(
                "rounded-lg border p-2",
                row.check ? "border-amber-400 bg-amber-50" : "border-slate-200 bg-white",
              )}
            >
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <span
                    aria-hidden="true"
                    className="flex size-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-sm font-bold text-slate-700"
                  >
                    {n}
                  </span>
                  <input
                    ref={(el) => {
                      if (el) inputs.current.set(row.key, el);
                      else inputs.current.delete(row.key);
                    }}
                    value={row.text}
                    onChange={(e) => onChange(editRow(rows, i, e.target.value))}
                    aria-label={`${n}단계 문장`}
                    aria-invalid={!row.text.trim() || undefined}
                    placeholder="이 단계에서 할 일을 적어 주세요"
                    className={cn(
                      "min-h-11 w-full min-w-0 break-keep rounded-lg border bg-white px-3 text-base text-slate-900",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600",
                      row.text.trim() ? "border-slate-300" : "border-red-500",
                    )}
                  />
                </div>
                <div className="flex shrink-0 flex-wrap gap-2 pl-10 sm:pl-0">
                  {target !== null && (
                    <button
                      type="button"
                      onClick={() => apply(mergeRows(rows, i))}
                      aria-label={`${n}단계와 ${target + 1}단계 합치기`}
                      className={cn(BTN, "border border-amber-500 bg-white text-amber-900 hover:bg-amber-100")}
                    >
                      합치기
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => apply(splitRow(rows, i, inputs.current.get(row.key)?.selectionStart), 0)}
                    aria-label={`${n}단계 더 나누기`}
                    title="커서를 둔 곳에서 두 줄로 나눠요. 커서가 없으면 아래에 빈 줄을 만들어요."
                    className={cn(BTN, "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50")}
                  >
                    더 나누기
                  </button>
                  <button
                    type="button"
                    onClick={() => apply(deleteRow(rows, i))}
                    disabled={rows.length <= 1}
                    aria-label={`${n}단계 지우기`}
                    title={rows.length <= 1 ? "마지막 한 줄은 지울 수 없어요" : "이 줄 지우기"}
                    className={cn(BTN, "min-w-11 border border-slate-300 bg-white px-2 text-slate-500 hover:bg-red-50 hover:text-red-700")}
                  >
                    <Trash2 size={18} aria-hidden="true" />
                  </button>
                </div>
              </div>
              {row.check && (
                <p className="mt-1 break-keep pl-10 text-sm text-amber-900">
                  나눈 곳 확인{row.source ? ` · 원래 문장: “${row.source}”` : ""}
                </p>
              )}
            </li>
          );
        })}
      </ol>

      <button
        type="button"
        onClick={() => apply(addRow(rows))}
        className={cn(BTN, "mt-2 border border-dashed border-slate-300 bg-white text-slate-700 hover:bg-slate-50")}
      >
        <Plus size={16} aria-hidden="true" /> 한 줄 추가
      </button>

      {emptyError && (
        <p role="alert" className="mt-3 break-keep text-sm font-semibold text-red-700">{emptyError}</p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={handleConfirm}
          disabled={confirming}
          className={cn(BTN, "bg-blue-700 px-5 text-base text-white hover:bg-blue-800")}
        >
          {confirming ? "그림을 고르고 있어요…" : "이대로 그림 고르기 ›"}
        </button>
        <p className="break-keep text-sm text-slate-600">누르면 초안으로 저장하고 단계마다 그림을 붙여요.</p>
      </div>
    </section>
  );
}
