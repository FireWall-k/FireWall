// 그림 한눈에 보기(명세 5.5, tasks §4.3 PictureOverview). 모든 단계를 200px 카드 격자로(390은 2열 150).
// - 틀린 그림을 누르면 그 단계로 간다.
// - 체크박스는 '✦ 자동 · 확인 필요'(auto_high) 단계에만. '골라 주세요'·'그림 없음'은 일괄 확인에서 뺀다.
// - [보이는 자동 그림 모두 맞아요]는 체크된 그림이 모두 실제로 그려진(decode된) 뒤에만 켜진다 — 보지 않은 그림을
//   확인하지 않게. 그림은 바로(eager) 불러온다.
// - 확인할 것이 0개가 되면 '모두 확인했어요 · [보내기]'.
// - 그림을 못 불러오면 그 칸은 '그림을 못 불러왔어요 · [다시 불러오기]'로 바꾸고 일괄 확인에서 뺀다 — 체크를 직접
//   풀어야만 켜지던 문제(1회차 검증). 서명 URL 만료일 수 있어 onMediaError로 직무를 다시 받는다.
// - 칸 단추 이름은 보이는 글 그대로(번호·문장·상태 배지, 번호 뒤 sr-only '단계 보기') — aria-label로 덮지 않는다(axe).
import { forwardRef, useLayoutEffect, useRef, useState } from "react";
import { ArrowLeft, CircleCheck, ImageOff, RotateCw, Send } from "lucide-react";
import { Badge, Button, Checkbox } from "../../../components/ui";
import { cn } from "../../../cn";
import type { EditorStep } from "../../api/types";
import { editor as editorCopy, overview as copy, pictureStatus } from "../../copy";
import { STATE_TONE, needsReview } from "./review";

export interface PictureOverviewProps {
  steps: EditorStep[];
  onBack: () => void;
  onOpenStep: (id: string) => void;
  /** 체크한 auto_high 단계를 한 번에 확인. 실패하면 부모가 알린다. */
  onConfirmAll: (ids: string[]) => Promise<void>;
  onSend: () => void;
  /** 그림을 못 불러왔을 때 — 서명 URL이 만료됐을 수 있어 직무를 다시 받아 URL만 바꾼다. */
  onMediaError?: (url: string | null | undefined) => void;
}

const PictureOverview = forwardRef<HTMLHeadingElement, PictureOverviewProps>(function PictureOverview(
  { steps, onBack, onOpenStep, onConfirmAll, onSend, onMediaError },
  headingRef,
) {
  // 체크를 푼 단계만 기억한다(새로 생긴 자동 그림은 체크된 채로 시작).
  const [unchecked, setUnchecked] = useState<Set<string>>(new Set());
  // 그려진 그림(단계 id|주소). 주소가 바뀌면 다시 기다린다.
  const [decoded, setDecoded] = useState<Set<string>>(new Set());
  // 못 불러온 그림(단계 id|주소). 주소가 바뀌거나 [다시 불러오기]를 누르면 다시 시도한다.
  const [broken, setBroken] = useState<Set<string>>(new Set());
  const [attempt, setAttempt] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const sendRef = useRef<HTMLButtonElement | null>(null);
  const confirmRef = useRef<HTMLButtonElement | null>(null);

  const autoSteps = steps.filter((s) => s.picture_state === "auto_high");
  const keyOf = (s: EditorStep) => `${s.id}|${s.symbol_url ?? ""}`;
  const brokenAuto = autoSteps.filter((s) => broken.has(keyOf(s)));
  const checked = autoSteps.filter((s) => !unchecked.has(s.id) && !broken.has(keyOf(s)));
  const allDecoded = checked.every((s) => decoded.has(keyOf(s)));
  const remaining = steps.filter(needsReview).length;
  const leftOther = steps.filter((s) => s.picture_state === "choose" || s.picture_state === "none").length;
  const canConfirm = checked.length > 0 && allDecoded && !busy;

  // 누른 단추가 사라지면(모두 확인) 초점이 body로 빠지지 않게 [보내기]로, 아니면 제목으로.
  useLayoutEffect(() => {
    const a = document.activeElement as HTMLElement | null;
    const lost = !a || a === document.body || !a.isConnected;
    if (!lost) return;
    if (remaining === 0 && sendRef.current) sendRef.current.focus();
  });

  function markBroken(s: EditorStep) {
    const key = keyOf(s);
    setBroken((cur) => (cur.has(key) ? cur : new Set(cur).add(key)));
    onMediaError?.(s.symbol_url);
  }

  function retry(s: EditorStep) {
    const key = keyOf(s);
    setBroken((cur) => {
      const next = new Set(cur);
      next.delete(key);
      return next;
    });
    setAttempt((cur) => ({ ...cur, [s.id]: (cur[s.id] ?? 0) + 1 }));
  }

  function markDecoded(key: string) {
    setDecoded((cur) => (cur.has(key) ? cur : new Set(cur).add(key)));
  }

  async function confirmAll() {
    if (!canConfirm) return;
    setBusy(true);
    try {
      await onConfirmAll(checked.map((s) => s.id));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="overview-title" data-testid="picture-overview" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="sm" onClick={onBack} icon={<ArrowLeft size={16} strokeWidth={2} aria-hidden="true" />}>
          {copy.back}
        </Button>
        <h2 id="overview-title" ref={headingRef} tabIndex={-1} className="text-ui-lg font-bold text-ink-900 focus:outline-none">
          {copy.title}
        </h2>
      </div>
      <p className="text-ui-base text-ink-700">{copy.hint}</p>

      <div className="flex flex-wrap items-center gap-3 rounded-card border border-paper-200 bg-white p-3">
        {remaining === 0 ? (
          <p role="status" className="flex flex-wrap items-center gap-2 text-ui-md font-semibold text-ok-700">
            <CircleCheck size={18} strokeWidth={2} aria-hidden="true" />
            {copy.allDone}
            <span aria-hidden="true">·</span>
            <Button ref={sendRef} variant="primary" onClick={onSend} icon={<Send size={16} strokeWidth={2} aria-hidden="true" />}>
              {editorCopy.send}
            </Button>
          </p>
        ) : (
          <>
            {autoSteps.length > 0 && (
              <Button
                ref={confirmRef}
                variant="primary"
                onClick={() => void confirmAll()}
                loading={busy}
                aria-disabled={!canConfirm || undefined}
                aria-describedby={!allDecoded ? "overview-waiting" : undefined}
                data-testid="confirm-all"
                className="!min-h-11 px-5 text-ui-md"
              >
                {copy.confirmAll}
              </Button>
            )}
            {autoSteps.length > 0 && !allDecoded && (
              <span id="overview-waiting" role="status" className="text-ui-sm text-ink-700">
                {copy.waiting}
              </span>
            )}
            {brokenAuto.length > 0 && (
              <span role="status" className="text-ui-sm font-semibold text-warn-700" data-testid="overview-broken-note">
                {copy.brokenExcluded(brokenAuto.length)}
              </span>
            )}
            {leftOther > 0 && <span className="text-ui-sm font-semibold text-warn-700">{copy.left(leftOther)}</span>}
          </>
        )}
      </div>

      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fill,minmax(200px,1fr))]">
        {steps.map((s, i) => {
          const n = i + 1;
          const isAuto = s.picture_state === "auto_high";
          const isBroken = broken.has(keyOf(s));
          return (
            <li
              key={s.id}
              data-testid={`overview-card-${n}`}
              data-state={s.picture_state}
              data-broken={isBroken || undefined}
              className={cn(
                "flex flex-col overflow-hidden rounded-card border bg-white",
                isAuto ? "border-auto-700/40" : "border-paper-200",
              )}
            >
              <button
                type="button"
                onClick={() => onOpenStep(s.id)}
                className="flex flex-col gap-2 p-2 text-left hover:bg-paper-50"
              >
                <span className="flex aspect-square w-full items-center justify-center overflow-hidden rounded-control border border-paper-200 bg-white">
                  {s.symbol_url && s.picture_state !== "none" && isBroken ? (
                    <span className="flex flex-col items-center gap-1 px-2 text-center text-ui-sm font-semibold text-warn-700">
                      <ImageOff size={24} strokeWidth={2} aria-hidden="true" />
                      {copy.broken}
                    </span>
                  ) : s.symbol_url && s.picture_state !== "none" ? (
                    <img
                      key={attempt[s.id] ?? 0}
                      src={s.symbol_url}
                      alt=""
                      loading="eager"
                      decoding="async"
                      data-step-picture={s.id}
                      onLoad={(e) => {
                        const img = e.currentTarget;
                        const key = keyOf(s);
                        if (typeof img.decode === "function") img.decode().then(() => markDecoded(key), () => {});
                        else markDecoded(key);
                      }}
                      onError={() => markBroken(s)}
                      className="size-full object-contain"
                    />
                  ) : (
                    <span className="text-ui-sm font-semibold text-danger-700">{pictureStatus.none}</span>
                  )}
                </span>
                <span className="flex items-start gap-1.5">
                  <span className="shrink-0 text-ui-base font-bold tabular-nums text-ink-700">
                    {n}
                    <span className="sr-only">{copy.openWord}</span>
                  </span>
                  <span className="line-clamp-2 text-ui-base text-ink-900">{s.sentence}</span>
                </span>
                <Badge tone={STATE_TONE[s.picture_state]} icon={isAuto ? false : undefined} className="self-start">
                  {pictureStatus[s.picture_state]}
                </Badge>
              </button>
              {isBroken && (
                <div className="border-t border-paper-200 px-2 py-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => retry(s)}
                    aria-label={copy.reloadPicture(n)}
                    icon={<RotateCw size={14} strokeWidth={2} aria-hidden="true" />}
                  >
                    {copy.reloadShort}
                  </Button>
                </div>
              )}
              {isAuto && !isBroken && (
                <Checkbox
                  className="border-t border-paper-200 px-2 py-2"
                  label={copy.check(n)}
                  checked={!unchecked.has(s.id)}
                  onChange={(v) =>
                    setUnchecked((cur) => {
                      const next = new Set(cur);
                      if (v) next.delete(s.id);
                      else next.add(s.id);
                      return next;
                    })
                  }
                />
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
});

export default PictureOverview;
