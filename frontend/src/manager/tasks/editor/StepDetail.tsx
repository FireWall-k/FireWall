// 편집기 단계 상세(명세 5.5 '단계 상세', tasks §4.3 StepDetail).
// - 그림 4상태: 확인함(바꾸기만) / ✦ 자동 · 확인 필요([이 그림이 맞아요], Enter) / 골라 주세요(후보 3장 크게) /
//   그림 없음(비슷한 후보 3장을 바로 펼쳐 한 번 눌러 붙인다. 후보가 없으면 [다른 그림 찾기]·[현장 사진 올리기]).
//   후보 순서는 서버가 정한다(직무를 만들 때 순서가 맨 앞, 그림 정확도 ②).
// - 문장: 고치면 600ms 뒤 자동 저장(defer_media — 문장만), 칸을 벗어나면 rewrite로 마무리(목소리·나누기). 동작이 둘이면
//   서버가 경고 없이 두 단계로 나누고 여기서 [되돌리기]를 보인다('동작이 2개예요' 알림은 없다).
// - 문장 점검 칩, 원래 지시문 인용, [목소리 듣기], 조심 스위치('✦ 자동 제안'이면 보라 표시), [이 단계 지우기](Dialog는 부모).
// Enter: 입력칸·단추 밖(제목·빈 곳)에서 누르면 ✦ 자동 그림을 확인한다. 입력칸 안의 Enter는 저장(칸 벗어나기)이다.
import { forwardRef, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ChevronLeft, ImageOff, Quote, Search, Trash2, Upload, Volume2, X } from "lucide-react";
import { Badge, Button, Switch } from "../../../components/ui";
import { cn } from "../../../cn";
import type { EditorStep, PictureCandidate } from "../../api/types";
import { editor as copy, pictureStatus } from "../../copy";
import { fitHeight } from "../new/fitHeight";
import { SentenceLint } from "./EditorBits";
import { STATE_TONE, toHaeyo } from "./review";

/** 문장을 고치고 이만큼 멈추면 저장한다(명세 5.5). */
export const AUTOSAVE_MS = 600;

export interface CandidateState {
  status: "ok" | "failed";
  items: PictureCandidate[];
}

export interface StepDetailProps {
  step: EditorStep;
  index: number;
  total: number;
  /** undefined = 아직 찾는 중. */
  candidates: CandidateState | undefined;
  /** [이 그림이 맞아요] 요청을 기다리는 중. */
  confirming: boolean;
  /** 보내기가 이 단계 때문에 막혔다. */
  blocked: boolean;
  /** 다른 단계 문장을 저장(나누기 포함)하는 중 — 이 칸은 읽기 전용. */
  readOnly: boolean;
  /** 이 단계 문장을 마무리 저장하는 중. */
  rewriting: boolean;
  /** 저장하며 나눈 단계라 [되돌리기]를 보일 때. */
  onUndo?: () => void;
  onConfirm: () => void;
  onApplyCandidate: (c: PictureCandidate) => void;
  onOpenPicker: (mode: "search" | "photo") => void;
  onRemovePhoto: () => void;
  onAutosave: (text: string) => void;
  onCommit: (text: string) => void;
  onToggleCaution: (value: boolean) => void;
  onDelete: () => void;
  /** 목소리 주소(없으면 null → 이 기기 음성으로 읽는다). */
  onVoice: () => Promise<string | null>;
  /** 좁은 화면: 목록으로 돌아가기. */
  onBack?: () => void;
  onMediaError?: (url: string | null | undefined) => void;
}

const NON_ENTER_TARGETS = "input, textarea, select, button, a, summary, [role='switch'], [contenteditable='true']";

function clean(text: string): string {
  return text.replace(/\s*[\r\n]+\s*/g, " ").trim();
}

const StepDetail = forwardRef<HTMLHeadingElement, StepDetailProps>(function StepDetail(props, headingRef) {
  const {
    step, index, total, candidates, confirming, blocked, readOnly, rewriting, onUndo,
    onConfirm, onApplyCandidate, onOpenPicker, onRemovePhoto, onAutosave, onCommit, onToggleCaution, onDelete, onVoice, onBack,
    onMediaError,
  } = props;
  const n = index + 1;
  const state = step.picture_state;
  const [text, setText] = useState(step.sentence);
  const [emptyError, setEmptyError] = useState(false);
  const timer = useRef<number | null>(null);
  const area = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);
  useEffect(() => {
    if (area.current) fitHeight(area.current);
  });

  function change(v: string) {
    const next = v.replace(/\s*[\r\n]+\s*/g, " ");
    setText(next);
    if (timer.current) window.clearTimeout(timer.current);
    const trimmed = next.trim();
    setEmptyError(!trimmed);
    if (!trimmed) return;
    timer.current = window.setTimeout(() => {
      timer.current = null;
      onAutosave(trimmed);
    }, AUTOSAVE_MS);
  }

  function commit(v = text) {
    if (timer.current) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    const t = clean(v);
    if (!t) {
      setEmptyError(true);
      return;
    }
    onCommit(t);
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "Enter" || e.nativeEvent.isComposing || e.defaultPrevented) return;
    if (state !== "auto_high" || confirming) return;
    const target = e.target as HTMLElement;
    if (target.closest(NON_ENTER_TARGETS)) return;
    e.preventDefault();
    onConfirm();
  }

  const current = step.picture;
  const others = (candidates?.items ?? []).filter((c) => c.card_id !== current?.card_id).slice(0, 3);
  const quote = step.split.original_span.trim();
  const showQuote = !!quote && quote !== step.sentence.trim();
  const autoCaution = step.safety_flag && step.safety.source === "auto";

  return (
    <div
      data-testid="step-detail"
      data-step-id={step.id}
      data-state={state}
      onKeyDown={onKeyDown}
      className="flex min-w-0 flex-col gap-5 rounded-card border border-paper-200 bg-white p-4 shadow-ui-sm md:p-5"
    >
      {onBack && (
        <Button variant="ghost" size="sm" onClick={onBack} className="self-start" icon={<ChevronLeft size={16} strokeWidth={2} aria-hidden="true" />}>
          {copy.backToList}
        </Button>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <h2 ref={headingRef} tabIndex={-1} className="text-ui-lg font-bold text-ink-900 focus:outline-none focus-visible:outline-2">
          {copy.detailHeading(n)}
          <span className="sr-only">{` / ${copy.stepsCount(total)}`}</span>
        </h2>
        <Badge tone={STATE_TONE[state]} icon={state === "auto_high" ? false : undefined}>
          {pictureStatus[state]}
        </Badge>
      </div>

      {blocked && (
        <p role="alert" className="rounded-control bg-danger-50 p-3 text-ui-base font-semibold text-danger-700">
          {state === "none" ? copy.blockedPicture : copy.blockedConfirm}
        </p>
      )}

      {/* ── 그림 ── */}
      <section aria-label={copy.pictureHeading} className="flex flex-col gap-3">
        {state === "choose" ? (
          <ChooseGrid
            candidates={candidates}
            fallback={current}
            onPick={onApplyCandidate}
          />
        ) : state === "none" ? (
          <NoneCandidates stepId={step.id} candidates={candidates} onPick={onApplyCandidate} />
        ) : (
          <figure className="m-0 flex flex-col gap-2">
            <div
              className={cn(
                "flex aspect-square w-full max-w-[280px] items-center justify-center overflow-hidden rounded-card border bg-white",
                state === "auto_high" ? "border-2 border-auto-700/50" : "border-paper-200",
              )}
            >
              {step.symbol_url && (
                <img src={step.symbol_url} alt="" onError={() => onMediaError?.(step.symbol_url)} className="size-full object-contain" />
              )}
            </div>
            <figcaption className="text-ui-sm text-ink-700">
              {current
                ? state === "confirmed" && current.source === "auto"
                  ? copy.sourceConfirmedAuto
                  : copy.source[current.source]
                : null}
              {current?.label ? ` · ${current.label}` : null}
            </figcaption>
          </figure>
        )}

        {state === "auto_high" && (
          <Button
            variant="primary"
            data-confirm-step={step.id}
            onClick={onConfirm}
            loading={confirming}
            className="!min-h-11 self-start px-5 text-ui-md"
          >
            {copy.confirmPicture}
            <kbd aria-hidden="true" className="ml-1 rounded border border-white/40 px-1 text-ui-xs font-normal">
              ⏎
            </kbd>
          </Button>
        )}

        {(state === "auto_high" || state === "confirmed") && (
          <details className="group rounded-control border border-paper-200 bg-paper-50 px-3 py-2">
            <summary className="min-h-8 cursor-pointer text-ui-base font-semibold text-ink-900 coarse:min-h-control-coarse">
              {copy.otherCandidates}
            </summary>
            <div className="mt-2">
              <CandidateRow candidates={candidates} items={others} onPick={onApplyCandidate} />
            </div>
          </details>
        )}

        <div className="flex flex-wrap gap-2">
          <Button
            variant={state === "none" ? "primary" : "secondary"}
            icon={<Search size={16} strokeWidth={2} aria-hidden="true" />}
            onClick={() => onOpenPicker("search")}
          >
            {copy.findPicture}
          </Button>
          <Button variant="secondary" icon={<Upload size={16} strokeWidth={2} aria-hidden="true" />} onClick={() => onOpenPicker("photo")}>
            {copy.uploadPhoto}
          </Button>
          {current?.source === "photo" && (
            <Button variant="ghost" icon={<X size={16} strokeWidth={2} aria-hidden="true" />} onClick={onRemovePhoto}>
              {copy.removePhoto}
            </Button>
          )}
        </div>
      </section>

      {/* ── 문장 ── */}
      <section className="flex flex-col gap-2">
        <label htmlFor={`sentence-${step.id}`} className="text-ui-base font-semibold text-ink-900">
          {copy.sentenceLabel}
        </label>
        <p id={`sentence-hint-${step.id}`} className="text-ui-sm text-ink-700">
          {copy.sentenceHint}
        </p>
        <textarea
          ref={area}
          id={`sentence-${step.id}`}
          rows={1}
          value={text}
          maxLength={500}
          readOnly={readOnly}
          aria-busy={rewriting || undefined}
          aria-invalid={emptyError || undefined}
          aria-describedby={`sentence-hint-${step.id}`}
          onChange={(e) => change(e.target.value)}
          onKeyDown={(e) => {
            // 한 단계 = 한 문장. Enter는 줄바꿈 대신 저장(칸 벗어나기)이다. 초점은 이 상세의 제목으로 옮긴다 —
            // blur()만 하면 초점이 body로 빠져 다음 Tab이 문서 맨 앞으로 갔다(1회차 검증). 제목으로 옮기면 칸을
            // 벗어나므로 onBlur가 저장한다. 저장하며 나눠 상세가 새로 그려지면 편집기가 새 상세 제목으로 옮긴다.
            if (e.key === "Enter" && !e.nativeEvent.isComposing) {
              e.preventDefault();
              const heading = e.currentTarget.closest("[data-testid='step-detail']")?.querySelector<HTMLElement>("h2");
              if (heading) heading.focus();
              else e.currentTarget.blur();
            }
          }}
          onBlur={() => commit()}
          className={cn(
            "block min-h-11 w-full resize-none overflow-hidden rounded-control border bg-white px-3 py-2 text-ui-md text-ink-900",
            "read-only:bg-paper-100",
            emptyError ? "border-danger-700" : "border-line-strong",
          )}
        />
        {emptyError && (
          <p role="alert" className="text-ui-sm font-semibold text-danger-700">
            {copy.emptySentence}
          </p>
        )}
        {rewriting && (
          <p role="status" className="text-ui-sm font-semibold text-ink-700">
            {copy.rewriting}
          </p>
        )}
        {onUndo && (
          <div role="status" className="flex flex-wrap items-center gap-2 rounded-control border border-paper-200 bg-paper-50 p-2 text-ui-base text-ink-900">
            <span>{copy.splitNotice}</span>
            <Button size="sm" variant="secondary" onClick={onUndo}>
              {copy.undo}
            </Button>
          </div>
        )}
        <SentenceLint
          items={step.lint}
          onReplace={(from, to) => {
            const next = text.split(from).join(to);
            setText(next);
            commit(next);
          }}
          onTone={() => {
            const next = toHaeyo(text);
            setText(next);
            commit(next);
          }}
        />
        {showQuote && (
          <figure className="m-0 flex flex-col gap-1">
            <figcaption className="text-ui-sm font-semibold text-ink-700">{copy.originalQuote}</figcaption>
            <blockquote className="m-0 flex gap-2 border-l-4 border-moss-600 bg-paper-50 px-3 py-2 text-ui-base text-ink-900">
              <Quote size={14} strokeWidth={2} aria-hidden="true" className="mt-1 shrink-0 text-ink-500" />
              <span>{quote}</span>
            </blockquote>
          </figure>
        )}
        <VoiceButton text={step.sentence} onVoice={onVoice} />
      </section>

      {/* ── 조심 ── */}
      <section className={cn("rounded-control border p-3", autoCaution ? "border-auto-700/40 bg-auto-50" : "border-paper-200")}>
        <Switch
          checked={step.safety_flag}
          onChange={onToggleCaution}
          label={
            <span className="inline-flex flex-wrap items-center gap-2 font-semibold">
              {copy.cautionLabel}
              {autoCaution && (
                <Badge tone="auto" icon={false}>
                  {copy.cautionAuto}
                </Badge>
              )}
            </span>
          }
          hint={autoCaution ? copy.cautionAutoHint : copy.cautionHint}
        />
      </section>

      {/* ── 위험 구역 ── */}
      <section className="flex flex-col gap-2 border-t border-paper-200 pt-4">
        <h3 className="text-ui-sm font-semibold text-ink-700">{copy.dangerZone}</h3>
        <Button
          variant="secondary"
          onClick={onDelete}
          disabled={total <= 1}
          title={total <= 1 ? copy.lastStep : undefined}
          icon={<Trash2 size={16} strokeWidth={2} aria-hidden="true" />}
          className="self-start text-danger-700"
        >
          {copy.deleteStep}
        </Button>
      </section>
    </div>
  );
});

export default StepDetail;

function CandidateRow({
  candidates,
  items,
  onPick,
}: {
  candidates: CandidateState | undefined;
  items: PictureCandidate[];
  onPick: (c: PictureCandidate) => void;
}) {
  if (!candidates) return <p role="status" className="text-ui-sm text-ink-700">{copy.candidatesLoading}</p>;
  if (candidates.status === "failed") return <p className="text-ui-sm text-ink-700">{copy.candidatesFailed}</p>;
  if (!items.length) return <p className="text-ui-sm text-ink-700">{copy.noCandidates}</p>;
  return (
    <ul className="grid grid-cols-3 gap-2">
      {items.map((c, i) => (
        <li key={c.card_id}>
          <CandidateButton c={c} n={i + 1} onPick={onPick} size="sm" />
        </li>
      ))}
    </ul>
  );
}

/**
 * '그림 없음' 단계: 비슷한 후보가 있으면 3장을 바로 펼친다(예전 검토 화면처럼, 한 번 눌러 붙인다). 찾는 중이거나 후보가
 * 없으면 빈 그림 칸만 보인다. 후보 단추 이름은 '후보 n 그림 이름'이라 화면 읽기 프로그램도 무엇을 붙이는지 안다.
 */
function NoneCandidates({
  stepId,
  candidates,
  onPick,
}: {
  stepId: string;
  candidates: CandidateState | undefined;
  onPick: (c: PictureCandidate) => void;
}) {
  const items = (candidates?.items ?? []).slice(0, 3);
  if (!items.length) {
    return (
      <div className="flex flex-col gap-2">
        <div data-testid="none-box" className="flex aspect-square w-full max-w-[280px] flex-col items-center justify-center gap-2 rounded-card border-2 border-dashed border-danger-700/40 bg-danger-50 text-danger-700">
          <ImageOff size={32} strokeWidth={2} aria-hidden="true" />
          <span className="text-ui-base font-semibold">{pictureStatus.none}</span>
        </div>
        {!candidates ? (
          <p role="status" className="text-ui-sm text-ink-700">{copy.candidatesLoading}</p>
        ) : candidates.status === "failed" ? (
          <p className="text-ui-sm text-ink-700">{copy.candidatesFailed}</p>
        ) : null}
      </div>
    );
  }
  const headingId = `none-candidates-${stepId}`;
  return (
    <div className="flex flex-col gap-2" data-testid="none-candidates" role="group" aria-labelledby={headingId}>
      <p id={headingId} className="text-ui-md font-semibold text-ink-900">{copy.noneChooseHeading}</p>
      <p className="text-ui-sm text-ink-700">{copy.noneChooseHint}</p>
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {items.map((c, i) => (
          <li key={c.card_id}>
            <CandidateButton c={c} n={i + 1} onPick={onPick} size="lg" />
          </li>
        ))}
      </ul>
    </div>
  );
}

function ChooseGrid({
  candidates,
  fallback,
  onPick,
}: {
  candidates: CandidateState | undefined;
  fallback: EditorStep["picture"];
  onPick: (c: PictureCandidate) => void;
}) {
  const items = (candidates?.items ?? []).slice(0, 3);
  const useFallback = !!candidates && !items.length && !!fallback && fallback.source !== "photo";
  return (
    <div className="flex flex-col gap-2">
      <p className="text-ui-md font-semibold text-ink-900">{copy.chooseHeading}</p>
      {!candidates ? (
        <p role="status" className="text-ui-base text-ink-700">
          {copy.candidatesLoading}
        </p>
      ) : items.length ? (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3" data-testid="choose-grid">
          {items.map((c, i) => (
            <li key={c.card_id}>
              <CandidateButton c={c} n={i + 1} onPick={onPick} size="lg" />
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-ui-base text-ink-700">{candidates.status === "failed" ? copy.candidatesFailed : copy.noCandidates}</p>
      )}
      {useFallback && fallback && (
        <div className="flex items-center gap-3">
          <img src={fallback.url} alt="" className="size-20 rounded-control border border-paper-200 object-contain" />
          <Button variant="secondary" onClick={() => onPick({ card_id: fallback.card_id, url: fallback.url, label: fallback.label })}>
            {copy.useCurrent}
          </Button>
        </div>
      )}
    </div>
  );
}

function CandidateButton({ c, n, onPick, size }: { c: PictureCandidate; n: number; onPick: (c: PictureCandidate) => void; size: "sm" | "lg" }) {
  return (
    <button
      type="button"
      onClick={() => onPick(c)}
      data-candidate={c.card_id}
      className="flex w-full flex-col items-center gap-1 rounded-card border border-paper-200 bg-white p-2 text-ui-sm text-ink-900 hover:border-moss-600 hover:bg-paper-50"
    >
      <span className="self-start text-ui-xs font-bold tabular-nums text-ink-700">{copy.candidateNo(n)}</span>
      {/* 단추 이름이 '후보 1 그림 이름'으로 띄어 읽히게(세로 flex 안의 빈칸은 그려지지 않는다). */}
      {" "}
      <img src={c.url} alt="" className={cn("aspect-square w-full object-contain", size === "lg" ? "max-w-[140px]" : "max-w-[88px]")} />
      <span className="line-clamp-2 text-center">{c.label || copy.useCurrent}</span>
    </button>
  );
}

function VoiceButton({ text, onVoice }: { text: string; onVoice: () => Promise<string | null> }) {
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const [fallback, setFallback] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => () => {
    audio.current?.pause();
    try {
      window.speechSynthesis?.cancel();
    } catch {
      /* 무시 */
    }
  }, []);

  function speakHere() {
    setFallback(true);
    try {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "ko-KR";
      u.rate = 0.9;
      u.onend = () => setState("idle");
      window.speechSynthesis?.speak(u);
      setState("playing");
    } catch {
      setState("idle");
    }
  }

  async function toggle() {
    if (state === "playing") {
      audio.current?.pause();
      try {
        window.speechSynthesis?.cancel();
      } catch {
        /* 무시 */
      }
      setState("idle");
      return;
    }
    if (state === "loading") return;
    setState("loading");
    setFallback(false);
    let url: string | null;
    try {
      url = await onVoice();
    } catch {
      url = null;
    }
    if (!url) {
      speakHere();
      return;
    }
    try {
      const a = new Audio(url);
      audio.current = a;
      a.onended = () => setState("idle");
      await a.play();
      setState("playing");
    } catch {
      speakHere();
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <Button
        variant="secondary"
        onClick={() => void toggle()}
        loading={state === "loading"}
        icon={<Volume2 size={16} strokeWidth={2} aria-hidden="true" />}
        className="self-start"
        data-testid="voice-button"
      >
        {state === "playing" ? copy.voiceStop : copy.voice}
      </Button>
      {fallback && <p className="text-ui-sm text-ink-700">{copy.voiceFallback}</p>}
    </div>
  );
}
