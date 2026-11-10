// 입력 화면에서 [단계로 나누기] 바로 아래에 펼치는 단계 목록(한 줄 = 한 동작 = 그림 1장, 명세 5.4).
// 나누기는 여기서 끝낸다 — 편집기에는 '동작이 2개예요' 알림이 없다(명세 3.4-A 2번). 애매하게 나눈 줄만 노랗게 칠하고
// [합치기]를 띄우며, 어느 줄이든 [더 나누기]·고치기·지우기를 할 수 있다. [이대로 그림 고르기]를 눌러야
// 초안이 만들어지고 그림을 고르러 간다. (2b-1) 옛 components/SplitPreviewList를 옮겨 사업주 토큰으로 바꿨다.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button, buttonClasses } from "../../../components/ui";
import { cn } from "../../../cn";
import { splitList as copy } from "../../copy";
import {
  addRow, deleteRow, editRow, emptyRows, limitError, MAX_ROW_CHARS, MAX_ROWS, mergeRows, mergeTarget, splitRow,
  type SplitRow,
} from "./splitRows";
import { fitHeight } from "./fitHeight";


interface Props {
  rows: SplitRow[];
  onChange: (rows: SplitRow[]) => void;
  onConfirm: () => void;
  confirming: boolean;
  /** 목록을 만든 뒤 직무 내용(원문)을 고쳤는지 — 고쳤으면 다시 나누라고 알려 준다. */
  stale: boolean;
  /** [이대로 그림 고르기]가 실패한 이유. 버튼 바로 아래에 보여 준다(긴 목록을 내려 본 390 화면에서도 보이게). */
  confirmError?: string | null;
}

export default function SplitPreviewList({ rows, onChange, onConfirm, confirming, stale, confirmError }: Props) {
  const inputs = useRef<Map<string, HTMLTextAreaElement>>(new Map());
  const confirmAlert = useRef<HTMLParagraphElement | null>(null);
  // 다음 렌더 뒤 초점을 줄 줄(합치기·나누기·지우기 뒤). 렌더가 끝나면 한 번 쓰고 비운다.
  // select: 글 전체를 선택한다(일부만 합친 줄 — 한 문장으로 다듬게).
  const pendingFocus = useRef<{ key: string; caret?: number; select?: boolean } | null>(null);
  const [emptyError, setEmptyError] = useState<string | null>(null);

  useEffect(() => {
    const want = pendingFocus.current;
    if (!want) return;
    pendingFocus.current = null;
    const el = inputs.current.get(want.key);
    if (el) {
      el.focus();
      if (want.select) el.select();
      else if (want.caret !== undefined) el.setSelectionRange(want.caret, want.caret);
    }
  });

  useEffect(() => {
    if (confirmError) confirmAlert.current?.scrollIntoView?.({ block: "nearest" });
  }, [confirmError]);

  useLayoutEffect(() => {
    inputs.current.forEach(fitHeight);
  });
  useEffect(() => {
    const onResize = () => inputs.current.forEach(fitHeight);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const apply = (next: { rows: SplitRow[]; focus: number; select?: boolean }, caret?: number) => {
    onChange(next.rows);
    const target = next.rows[next.focus];
    if (target) pendingFocus.current = { key: target.key, caret, select: next.select };
    setEmptyError(null);
  };

  const checkCount = rows.filter((r) => r.check).length;

  function handleConfirm() {
    const empty = emptyRows(rows);
    if (empty.length) {
      setEmptyError(copy.emptyRows(empty.map((i) => `${i + 1}단계`).join(", ")));
      inputs.current.get(rows[empty[0]].key)?.focus();
      return;
    }
    const over = limitError(rows);
    if (over) {
      setEmptyError(over);
      return;
    }
    setEmptyError(null);
    onConfirm();
  }

  const full = rows.length >= MAX_ROWS;
  const small = cn(buttonClasses("secondary", "md"), "!min-h-11");

  return (
    <section aria-labelledby="split-preview-title" className="mt-6 rounded-card border border-paper-200 bg-white p-4 shadow-ui-sm md:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="split-preview-title" tabIndex={-1} className="text-ui-lg font-bold text-ink-900 focus:outline-none">
          {copy.title} <span className="text-ui-base font-normal text-ink-700">{copy.count(rows.length)}</span>
        </h2>
        <p className="text-ui-sm text-ink-700">{copy.rule}</p>
      </div>
      {checkCount > 0 && (
        <p className="mt-2 rounded-control border border-warn-line/40 bg-warn-50 p-2 text-ui-base text-warn-700">
          {copy.checkNotice(checkCount)}
        </p>
      )}
      {stale && (
        <p role="status" className="mt-2 rounded-control bg-paper-100 p-2 text-ui-base text-ink-700">
          {copy.stale}
        </p>
      )}

      <ol className="mt-3 flex flex-col gap-2">
        {rows.map((row, i) => {
          const n = i + 1;
          const target = mergeTarget(rows, i);
          return (
            <li
              key={row.key}
              data-testid={`split-row-${n}`}
              data-check={row.check ? "true" : "false"}
              className={cn("rounded-card border p-2", row.check ? "border-warn-line bg-warn-50" : "border-paper-200 bg-white")}
            >
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <span
                    aria-hidden="true"
                    className="flex size-8 shrink-0 items-center justify-center rounded-full bg-paper-100 text-ui-base font-bold tabular-nums text-ink-700"
                  >
                    {n}
                  </span>
                  <textarea
                    rows={1}
                    ref={(el) => {
                      if (el) inputs.current.set(row.key, el);
                      else inputs.current.delete(row.key);
                    }}
                    value={row.text}
                    onChange={(e) => onChange(editRow(rows, i, e.target.value.replace(/\s*[\r\n]+\s*/g, " ")))}
                    onKeyDown={(e) => {
                      // Enter는 줄바꿈을 넣지 않는다(한 줄 = 한 동작). 나누려면 [더 나누기]를 쓴다.
                      if (e.key === "Enter" && !e.nativeEvent.isComposing) e.preventDefault();
                    }}
                    aria-label={copy.rowLabel(n)}
                    aria-invalid={!row.text.trim() || undefined}
                    maxLength={MAX_ROW_CHARS}
                    placeholder={copy.rowPlaceholder}
                    className={cn(
                      "block min-h-11 w-full min-w-0 resize-none overflow-hidden rounded-control border bg-white px-3 py-2 text-ui-md text-ink-900",
                      "placeholder:text-ink-500",
                      row.text.trim() ? "border-line-strong" : "border-danger-700",
                    )}
                  />
                </div>
                <div className="flex shrink-0 flex-wrap gap-2 pl-10 sm:pl-0">
                  {target !== null && (
                    <button
                      type="button"
                      onClick={() => apply(mergeRows(rows, i))}
                      aria-label={copy.mergeLabel(n, target + 1)}
                      className={cn(small, "border-warn-line text-warn-700 hover:bg-warn-50")}
                    >
                      {copy.merge}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => apply(splitRow(rows, i, inputs.current.get(row.key)?.selectionStart), 0)}
                    disabled={full}
                    aria-label={copy.splitMoreLabel(n)}
                    title={full ? copy.full(MAX_ROWS) : copy.splitMoreHint}
                    className={small}
                  >
                    {copy.splitMore}
                  </button>
                  <button
                    type="button"
                    onClick={() => apply(deleteRow(rows, i))}
                    disabled={rows.length <= 1}
                    aria-label={copy.deleteLabel(n)}
                    title={rows.length <= 1 ? copy.lastRow : undefined}
                    className={cn(small, "min-w-11 px-2 text-ink-700 hover:bg-danger-50 hover:text-danger-700")}
                  >
                    <Trash2 size={18} strokeWidth={2} aria-hidden="true" />
                  </button>
                </div>
              </div>
              {row.check && (
                <p className="mt-1 pl-10 text-ui-base text-warn-700">
                  {row.group === null ? copy.noGroupHint : copy.groupHint(row.source ?? "")}
                </p>
              )}
            </li>
          );
        })}
      </ol>

      <button
        type="button"
        onClick={() => apply(addRow(rows))}
        disabled={full}
        title={full ? copy.full(MAX_ROWS) : undefined}
        className={cn(small, "mt-2 border-dashed")}
      >
        <Plus size={16} strokeWidth={2} aria-hidden="true" /> {copy.addRow}
      </button>

      {emptyError && (
        <p role="alert" className="mt-3 text-ui-base font-semibold text-danger-700">
          {emptyError}
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button variant="primary" onClick={handleConfirm} loading={confirming} className="!min-h-11 px-5 text-ui-md">
          {copy.confirm}
        </Button>
        <p className="text-ui-sm text-ink-700">{copy.confirmHint}</p>
      </div>
      {confirmError && !confirming && (
        <p ref={confirmAlert} role="alert" className="mt-3 rounded-control bg-danger-50 p-3 text-ui-base font-semibold text-danger-700">
          {confirmError}
        </p>
      )}
    </section>
  );
}
