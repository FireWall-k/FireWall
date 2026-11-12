// 편집기 머리·상세의 작은 부품(명세 7.4): SaveIndicator, ReviewQueueBar, SentenceLint, VersionNotice.
import { CircleAlert, CircleCheck, LoaderCircle, Users } from "lucide-react";
import { Badge, Button } from "../../../components/ui";
import { cn } from "../../../cn";
import type { LintItem } from "../../api/types";
import { editor as editorCopy, reviewQueue, saveState, versionNotice } from "../../copy";

// --- SaveIndicator: '저장됨 · 방금' / '저장하는 중…' / '저장하지 못했어요 · 다시 시도' ---

export type SaveStatus = "saved" | "saving" | "error";

export function SaveIndicator({ status, when, onRetry }: { status: SaveStatus; when: string; onRetry?: () => void }) {
  return (
    <span data-testid="save-indicator" data-status={status} className="inline-flex items-center gap-1.5 whitespace-nowrap text-ui-sm">
      <span role="status" className={cn("inline-flex items-center gap-1.5", status === "error" ? "font-semibold text-danger-700" : "text-ink-700")}>
        {status === "saving" ? (
          <LoaderCircle size={14} strokeWidth={2} aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
        ) : status === "error" ? (
          <CircleAlert size={14} strokeWidth={2} aria-hidden="true" />
        ) : (
          <CircleCheck size={14} strokeWidth={2} aria-hidden="true" className="text-ok-700" />
        )}
        {status === "saving" ? saveState.saving : status === "error" ? saveState.failed : saveState.saved(when)}
      </span>
      {status === "error" && onRetry && (
        <>
          <span aria-hidden="true" className="text-danger-700">
            ·
          </span>
          <button
            type="button"
            onClick={onRetry}
            className="min-h-8 font-semibold text-info-700 underline underline-offset-2 coarse:min-h-control-coarse"
          >
            {saveState.retry}
          </button>
        </>
      )}
    </span>
  );
}

// --- ReviewQueueBar: '확인할 것 3개 남음 ▓▓░ [다음 ▶]' (숫자는 남은 개수만, 퍼센트 없음) ---

export function ReviewQueueBar({
  remaining,
  total,
  onNext,
  compact = false,
  nextRef,
}: {
  remaining: number;
  total: number;
  onNext: () => void;
  compact?: boolean;
  nextRef?: (el: HTMLButtonElement | null) => void;
}) {
  const done = Math.max(0, total - remaining);
  return (
    <div data-testid="review-queue" data-remaining={remaining} className="flex min-w-0 items-center gap-2">
      {remaining > 0 ? (
        <>
          <span className="whitespace-nowrap text-ui-base font-semibold text-ink-900">{reviewQueue.remaining(remaining)}</span>
          {!compact && total > 0 && (
            <span aria-hidden="true" className="flex h-2 w-20 overflow-hidden rounded-full bg-paper-200">
              <span className="h-full rounded-full bg-moss-600" style={{ width: `${(done / total) * 100}%` }} />
            </span>
          )}
          <Button ref={nextRef} size="sm" variant="secondary" onClick={onNext} aria-label={`${reviewQueue.next} ${reviewQueue.nextLabel}`}>
            {reviewQueue.next}
          </Button>
        </>
      ) : (
        <span className="inline-flex items-center gap-1 whitespace-nowrap text-ui-base font-semibold text-ok-700">
          <CircleCheck size={16} strokeWidth={2} aria-hidden="true" />
          {reviewQueue.allDone}
        </span>
      )}
    </div>
  );
}

// --- SentenceLint: 문장 점검 칩. 어려운 말·'~하세요' 체는 눌러서 바로 고친다(동작 수 경고는 없다, 명세 5.5) ---

export function SentenceLint({
  items,
  onReplace,
  onTone,
}: {
  items: LintItem[];
  onReplace: (from: string, to: string) => void;
  onTone: () => void;
}) {
  if (!items.length) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-ui-sm font-semibold text-ink-700">{editorCopy.lintHeading}</p>
      <ul className="flex flex-wrap gap-2" data-testid="sentence-lint">
        {items.map((l, i) => (
          <li key={`${l.code}-${i}`}>
            {l.code === "too_long" ? (
              <Badge tone="warning">{editorCopy.lint.too_long}</Badge>
            ) : l.code === "hard_word" && l.from && l.to ? (
              <button
                type="button"
                onClick={() => onReplace(l.from as string, l.to as string)}
                className="inline-flex min-h-8 items-center gap-1 rounded-full border border-warn-line/40 bg-warn-50 px-2.5 text-ui-sm font-semibold text-warn-700 hover:bg-white coarse:min-h-control-coarse"
              >
                {editorCopy.lint.hard_word(l.from, l.to)}
              </button>
            ) : l.code === "command_tone" ? (
              <button
                type="button"
                onClick={onTone}
                className="inline-flex min-h-8 items-center gap-1 rounded-full border border-warn-line/40 bg-warn-50 px-2.5 text-ui-sm font-semibold text-warn-700 hover:bg-white coarse:min-h-control-coarse"
              >
                {editorCopy.lint.command_tone}
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

// --- VersionNotice: 보낸 직무를 고칠 때 머리 아래(contract §3.7) ---

// '다음에 보낼 때부터 바뀌어요'는 보낸 뒤 고친 것이 있을 때(changed)만 붙인다(2회차 검증).
export function VersionNotice({ recipients, working, changed }: { recipients: number; working: number; changed: boolean }) {
  if (recipients <= 0) return null;
  return (
    <p
      data-testid="version-notice"
      className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-control border border-info-700/20 bg-white px-3 py-2 text-ui-base text-ink-900"
    >
      <Users size={16} strokeWidth={2} aria-hidden="true" className="shrink-0 text-info-700" />
      <span>{versionNotice.working(recipients, working)}</span>
      {changed && (
        <>
          <span aria-hidden="true" className="text-ink-500">
            ·
          </span>
          <span className="text-ink-700">{versionNotice.nextTime}</span>
        </>
      )}
    </p>
  );
}
