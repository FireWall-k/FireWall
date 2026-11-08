// 단계 화면(StepPlayer, 명세 4.4 — 근로자 화면의 중심). 한 화면 = 그림 1장 + 문장 1개(창업자 결정 9).
// 버튼은 늘 같은 자리: 위 띠 [나가기]·[도와주세요], 아래 막대 [이전]·[다 했어요]. [다 했어요]는 어떤 화면
// 크기·글자 크기에서도 화면 안에 있다(넘치면 가운데만 스크롤, 명세 4.0 넘침 규칙).
// - live: 일하는 중. [다 했어요] → 0.4초 '잘했어요' → 다음 단계. 자동 넘김 없음.
// - review: 했던 일 다시 보기. 도와주세요 없음, [이전][다음], 소리 자동 재생 끔.
// 배치: 세로 화면은 위에서 아래로(진행 점 → 그림 → 문장·듣기). 가로로 넓은 화면(wide)은 왼쪽 그림,
// 오른쪽에 점·문장·버튼 두 칸(휴대폰 가로 844×390, 태블릿 가로 1180×820).
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import type { A11yPrefs, Step } from "../api";
import { cn } from "../cn";
import { isSignedMediaUrl } from "../media";
import { IconDone, IconExit, IconNext, IconPrev, IconRetry, IconSpeak, IconStop } from "../ui/icons";
import { COPY } from "./copy";
import { HelpBanner, HelpButton } from "./Help";
import type { HelpController } from "./hooks/useHelp";
import { useStepAudio } from "./hooks/useStepAudio";
import { ProgressDots } from "./ProgressDots";
import { playCheckSound } from "./sound";
import { vibrate } from "./speech";
import { ConfirmScreen } from "./ui/ConfirmScreen";
import { PrimaryAction, SecondaryAction } from "./ui/WorkerButton";
import { BottomBar, OfflineMark, TopBar } from "./WorkerScreen";

/** '잘했어요' 체크를 보이는 시간. */
export const PRAISE_MS = 400;
/** 이 이상이면 '어려움 신호'(stuck)로 기록한다(대시보드 막힘 표시). */
export const STUCK_REPLAY_THRESHOLD = 3;
export const STUCK_DURATION_SEC = 120;
/** 서명 URL을 다시 받는 동안 기다리는 시간. 그래도 안 되면 '그림을 못 불러왔어요'. */
const PICTURE_REFRESH_WAIT_MS = 5_000;

/** 단계 시간 재기용 시계(단조). performance가 없는 환경만 Date.now로. */
function monotonicNow(): number {
  return typeof performance !== "undefined" && typeof performance.now === "function" ? performance.now() : Date.now();
}

export interface StepDoneInfo {
  step: Step;
  index: number;
  durationSec: number;
  replayCount: number;
  stuck: boolean;
}

export interface StepPlayerProps {
  mode: "live" | "review";
  title: string;
  steps: Step[];
  /** 지금 단계(0부터). */
  index: number;
  doneIds: ReadonlySet<string>;
  prefs: A11yPrefs;
  /** live에서만. */
  help?: HelpController;
  /** 도움 띠가 없을 때 보일 띠(오프라인·기록 보냄). */
  band?: ReactNode;
  /** 인터넷이 끊겼는지(도움 띠가 떠 있으면 위 띠 가운데 작은 표시로). */
  offline?: boolean;
  /** [다 했어요]를 누른 순간(칭찬 전에) 한 번. 기록은 여기서 남긴다 — 칭찬 중 화면이 사라져도 잃지 않게. */
  onRecord?: (info: StepDoneInfo) => void;
  /** 칭찬(0.4초)이 끝난 뒤 한 번. 다음 단계로 넘어간다. */
  onDone?: (info: StepDoneInfo) => void;
  onPrev: () => void;
  onNext?: () => void;
  onExit: () => void;
  onMediaError?: (url: string | null | undefined) => void;
}

// --- 화면 크기 ---
const TABLET_QUERY = "(min-width: 768px) and (min-height: 700px)";
// tailwind.config.js의 wide·land 변형과 같은 값이어야 한다.
const WIDE_QUERY = "(orientation: landscape) and (min-width: 560px)";
const LAND_QUERY = "(orientation: landscape) and (max-height: 620px)";

function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => {};
      const mq = window.matchMedia(query);
      mq.addEventListener?.("change", cb);
      return () => mq.removeEventListener?.("change", cb);
    },
    () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : false),
    () => false,
  );
}

/** 문장 기본 글자(px): 휴대폰 32 / 휴대폰 가로 28 / 태블릿 세로 44 / 태블릿 가로 40. 크게(+4). */
function baseSentencePx(tablet: boolean, wide: boolean, large: boolean): number {
  const base = tablet ? (wide ? 40 : 44) : wide ? 28 : 32;
  return base + (large ? 4 : 0);
}

const FIT_MAX = 2;
/** 문장 글자 바닥(명세 4.0·4.4-D: 32 → 28 → 24, 그다음은 가운데 스크롤). 가로 휴대폰은 28에서 시작해 24에서 멈춘다. */
const SENTENCE_MIN_PX = 24;

/**
 * 넘침 규칙 2번: 문장이 2줄을 넘거나 가운데가 넘치면 글자를 4px씩 두 번까지 줄인다(32 → 28 → 24).
 * 그림은 CSS가 먼저 최소 크기까지 줄인다(1번). 그래도 넘치면 가운데만 스크롤(3번).
 */
function useSentenceFit(stepId: string, basePx: number, layoutKey: string) {
  const h1Ref = useRef<HTMLHeadingElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const cellRef = useRef<HTMLDivElement | null>(null);
  const [vp, setVp] = useState(() => (typeof window === "undefined" ? "" : `${window.innerWidth}x${window.innerHeight}`));
  const key = `${stepId}|${basePx}|${vp}|${layoutKey}`;
  const [fit, setFit] = useState<{ key: string; level: number }>({ key, level: 0 });
  const level = fit.key === key ? fit.level : 0;

  useEffect(() => {
    const onResize = () => setVp(`${window.innerWidth}x${window.innerHeight}`);
    window.addEventListener("resize", onResize);
    document.fonts?.ready.then(onResize).catch(() => {});
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useLayoutEffect(() => {
    // 바닥(24px)에 닿으면 더 줄이지 않는다. 예전에는 가로 휴대폰(28)에서 두 번 줄여 20px이 됐다(1차 검증).
    if (level >= FIT_MAX || basePx - level * 4 <= SENTENCE_MIN_PX) return;
    const h1 = h1Ref.current;
    if (!h1) return;
    const lh = parseFloat(getComputedStyle(h1).lineHeight);
    const lines = lh > 0 ? Math.round(h1.getBoundingClientRect().height / lh) : 1;
    const over = (el: HTMLElement | null) => !!el && el.clientHeight > 0 && el.scrollHeight > el.clientHeight + 1;
    if (lines > 2 || over(scrollRef.current) || over(cellRef.current)) setFit({ key, level: level + 1 });
  }, [key, level, basePx]);

  return { h1Ref, scrollRef, cellRef, px: Math.max(SENTENCE_MIN_PX, basePx - level * 4), level };
}

/**
 * 가로 화면의 문장 칸은 따로 스크롤한다(글자 바닥 24px 아래로 줄이지 않으므로). 아래에 더 있으면 칸 아래쪽을
 * 흐리게 해서 "더 있다"를 보인다(1차 검증: 844×390 도움 띠가 있을 때 마지막 줄이 말없이 잘려 보였다).
 */
function useMoreBelow(ref: { current: HTMLElement | null }, key: string): boolean {
  const [more, setMore] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setMore(el.scrollHeight - el.scrollTop - el.clientHeight > 2);
    update();
    el.addEventListener("scroll", update, { passive: true });
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    ro?.observe(el);
    return () => {
      el.removeEventListener("scroll", update);
      ro?.disconnect();
    };
  }, [ref, key]);
  return more;
}

// --- 그림 ---
// TODO(2차): 위험 단계 '조심해요' 띠(명세 4.4-C·7.1). 단계에 위험 표시(safety_flags)가 아직 없다 — 백엔드 Step·근로자
// today 응답·사업주 편집 화면에 필드를 더한 뒤 그림 위에 40px 띠(COPY.step.caution)를 그린다.
function StepPicture({ step, onMediaError }: { step: Step; onMediaError?: (url: string | null | undefined) => void }) {
  const url = step.symbol_url;
  const [st, setSt] = useState<{ url: string | null; state: "loading" | "ok" | "failed"; nonce: number }>({
    url,
    state: "loading",
    nonce: 0,
  });
  const tried = useRef(new Set<string>());
  const current = st.url === url ? st : { url, state: "loading" as const, nonce: st.nonce };

  useEffect(() => {
    if (current.state !== "loading" || !url) return;
    // 다시 받은 서명 URL로도 안 오면 실패로 본다(같은 URL이 그대로 돌아오는 경우 포함).
    if (!tried.current.has(url)) return;
    const t = window.setTimeout(() => setSt({ url, state: "failed", nonce: current.nonce }), PICTURE_REFRESH_WAIT_MS);
    return () => window.clearTimeout(t);
  }, [url, current.state, current.nonce]);

  const onError = () => {
    if (url && isSignedMediaUrl(url) && !tried.current.has(url)) {
      tried.current.add(url);
      onMediaError?.(url);
      setSt({ url, state: "loading", nonce: current.nonce });
      return;
    }
    setSt({ url, state: "failed", nonce: current.nonce });
  };

  const failed = !url || current.state === "failed";
  return (
    <div
      data-testid="step-picture"
      data-state={failed ? "failed" : current.state}
      className="relative size-[100cqmin] overflow-hidden rounded-worker-pic border-2 border-worker-line-soft bg-white hc:border-black"
    >
      {url && !failed && (
        <img
          key={`${url}#${current.nonce}`}
          src={url}
          alt=""
          draggable={false}
          onLoad={() => setSt({ url, state: "ok", nonce: current.nonce })}
          onError={onError}
          className="size-full object-contain"
        />
      )}
      {!failed && current.state === "loading" && (
        <div aria-hidden="true" className="absolute inset-0 animate-pulse bg-worker-line-soft motion-reduce:animate-none" />
      )}
      {failed && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 p-4 text-center">
          <p className="text-worker font-semibold text-worker-ink-soft hc:text-black">{COPY.picture.failed}</p>
          {url && (
            <SecondaryAction icon={IconRetry} onPress={() => setSt({ url, state: "loading", nonce: current.nonce + 1 })}>
              {COPY.btn.retryPicture}
            </SecondaryAction>
          )}
        </div>
      )}
    </div>
  );
}

// --- 듣기 ---
function SpeakButton({ playing, blocked, onPress }: { playing: boolean; blocked: boolean; onPress: () => void }) {
  return (
    <button
      type="button"
      onClick={onPress}
      data-testid="speak-button"
      className={cn(
        "flex size-20 shrink-0 select-none flex-col items-center justify-center gap-0.5 rounded-worker-btn bg-worker-sound text-worker-caption font-bold text-worker-sound-ink",
        blocked ? "border-[3px] border-worker-sound-ink" : "border-2 border-transparent",
        "hc:border-black hc:bg-white hc:text-black",
      )}
    >
      {/* 이름이 '듣기'↔'멈춤'으로 바뀌므로 aria-pressed는 쓰지 않는다(3차 검증: 화면낭독기가 '멈춤, 눌림'으로 상태를
          두 번 읽었다, WAI-ARIA APG 토글 버튼). */}
      {playing ? <IconStop size={28} /> : <IconSpeak size={28} />}
      <span>{playing ? COPY.btn.stop : COPY.btn.listen}</span>
    </button>
  );
}

export function StepPlayer({
  mode,
  title,
  steps,
  index,
  doneIds,
  prefs,
  help,
  band,
  offline = false,
  onRecord,
  onDone,
  onPrev,
  onNext,
  onExit,
  onMediaError,
}: StepPlayerProps) {
  const step = steps[index];
  const live = mode === "live";
  const helpPhaseForFit = live ? (help?.phase ?? "idle") : "idle";
  // 띠가 나타나거나 바뀌면(도움·오프라인) 가운데 높이가 달라지므로 글자 크기를 다시 맞춘다.
  const layoutKey = `${helpPhaseForFit}|${band ? "band" : ""}`;
  const tablet = useMedia(TABLET_QUERY);
  const wide = useMedia(WIDE_QUERY);
  const land = useMedia(LAND_QUERY);
  const { h1Ref, scrollRef, cellRef, px: sentencePx, level: fitLevel } = useSentenceFit(step?.id ?? "", baseSentencePx(tablet, wide, prefs.font_size === "large"), layoutKey);
  const captionMore = useMoreBelow(cellRef, `${step?.id ?? ""}|${sentencePx}|${layoutKey}|${wide}`);
  // 세로 화면은 가운데 칸 전체가 스크롤한다. 넘치면 아래쪽을 흐리게 해 "더 있다"를 보인다(2차 검증: 작은 휴대폰에서
  // 도움·끊김 띠가 뜨면 문장과 [듣기]가 줄 가운데서 말없이 잘렸다).
  const scrollMore = useMoreBelow(scrollRef, `${step?.id ?? ""}|${sentencePx}|${layoutKey}|${wide}`);
  const audio = useStepAudio(step ?? null, {
    autoplay: live && prefs.autoplay_sound,
    rate: prefs.tts_rate,
    onMediaError,
  });
  const [praising, setPraising] = useState(false);
  const [confirmExit, setConfirmExit] = useState(false);
  const startedAt = useRef(0);
  const praiseTimer = useRef<number | null>(null);

  // 단계가 바뀌면: 시간 다시 재기 + 문장으로 초점(화면 읽기 프로그램이 새 문장을 읽는다).
  useEffect(() => {
    startedAt.current = monotonicNow();
    h1Ref.current?.focus({ preventScroll: true });
    scrollRef.current?.scrollTo?.({ top: 0 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step?.id]);

  useEffect(
    () => () => {
      if (praiseTimer.current) window.clearTimeout(praiseTimer.current);
    },
    [],
  );

  const handleDone = useCallback(() => {
    if (!step || praising || !onDone) return;
    // 단조 시계로 잰다: 단계 중에 기기 시계가 뒤로 가도(시각 맞춤) 음수가 되지 않는다(2차 검증).
    const durationSec = Math.max(0, (monotonicNow() - startedAt.current) / 1000);
    const replayCount = audio.replayCount;
    const info: StepDoneInfo = {
      step,
      index,
      durationSec,
      replayCount,
      stuck: replayCount >= STUCK_REPLAY_THRESHOLD || durationSec >= STUCK_DURATION_SEC,
    };
    audio.stop();
    onRecord?.(info);
    setPraising(true);
    playCheckSound(prefs.sfx);
    vibrate(30, prefs.vibration);
    praiseTimer.current = window.setTimeout(() => {
      praiseTimer.current = null;
      setPraising(false);
      onDone(info);
    }, PRAISE_MS);
  }, [step, praising, onDone, onRecord, index, audio, prefs.sfx, prefs.vibration]);

  if (!step) return null;

  const helpPhase = help?.phase ?? "idle";
  const helpBand = live && help && helpPhase !== "idle"
    ? <HelpBanner phase={helpPhase} onCancel={help.cancel} onRetry={help.request} />
    : null;
  const shownBand = helpBand ?? band ?? null;
  const offlineMark = !!helpBand && offline;
  // 가로 휴대폰(낮은 화면)에서 띠가 떠 있으면 진행 점과 [듣기]를 위 띠 가운데로 옮긴다(3차 검증: 844×390에서 띠가
  // 110px을 먹어 오른쪽 칸에 점·문장·[듣기]가 다 들어가지 못했고 [듣기]/[멈춤] 글자가 흐림에 가려졌다. 640×360에서는
  // 위 띠 82 + 도움 띠 110 + 아래 막대 106이라 문장 칸이 62px뿐이라 80px [듣기]가 들어갈 수 없다). 오른쪽 칸은 문장만.
  const dotsInTop = wide && land && !!shownBand;
  const dots = (
    <ProgressDots
      total={steps.length}
      current={index}
      done={(i) => doneIds.has(steps[i].id)}
      size={dotsInTop && steps.length > 6 ? "sm" : "md"}
    />
  );
  const speak = <SpeakButton playing={audio.playing} blocked={audio.blocked} onPress={audio.toggle} />;

  const exit = () => {
    if (live) {
      audio.stop();
      setConfirmExit(true);
    } else onExit();
  };

  return (
    <div
      data-testid="step-player"
      data-mode={mode}
      className={cn(
        "flex h-dvh flex-col overflow-hidden bg-worker-bg font-worker text-worker-ink hc:bg-white hc:text-black",
        "wide:grid wide:grid-cols-[minmax(0,1fr)_minmax(18rem,26.5rem)] wide:grid-rows-[auto_auto_auto_minmax(0,1fr)_auto] wide:gap-x-6 tablet:wide:gap-x-8",
      )}
    >
      <div className="wide:col-span-2 wide:row-start-1">
        <TopBar
          left={
            <SecondaryAction icon={IconExit} onPress={exit} className="!gap-2 !px-3">
              {COPY.btn.exit}
            </SecondaryAction>
          }
          center={
            dotsInTop ? (
              <div className="flex min-w-0 items-center gap-6 px-4" data-testid="top-dots">
                {offlineMark && <OfflineMark />}
                {dots}
                {speak}
              </div>
            ) : offlineMark ? (
              <OfflineMark />
            ) : undefined
          }
          right={live && help ? <HelpButton phase={helpPhase} onPress={help.request} /> : undefined}
        />
      </div>
      <div className="wide:col-span-2 wide:row-start-2">{shownBand}</div>

      {/* 가운데: 세로 화면에서는 이 칸만 스크롤한다. 가로로 넓은 화면에서는 칸을 풀어(contents) 격자에 바로 놓는다. */}
      <div
        ref={scrollRef}
        data-testid="step-scroll"
        data-more={scrollMore && !wide ? "true" : undefined}
        className={cn(
          "mx-auto flex min-h-0 w-full max-w-[1024px] flex-1 flex-col overflow-y-auto px-4 tablet:px-8 wide:contents",
          "data-[more=true]:[mask-image:linear-gradient(to_bottom,#000_calc(100%_-_2.5rem),transparent)]",
        )}
      >
        <div
          className={cn(
            "flex h-10 shrink-0 items-center small:h-8 tablet:h-12 wide:col-start-2 wide:row-start-3 wide:px-0 wide:pt-4",
            dotsInTop && "wide:hidden",
          )}
        >
          {!dotsInTop && dots}
          <p className="sr-only" aria-live="polite">{`${title}, ${COPY.step.srProgress(index + 1, steps.length)}`}</p>
        </div>

        <figure className="m-0 flex min-h-0 flex-1 flex-col wide:contents">
          {/* 그림 칸: 남는 높이를 다 갖고, 그 안에서 짧은 쪽에 맞춘 정사각형. 바닥은 240px(작은 기기 180px). */}
          <div
            key={`pic-${step.id}`}
            className={cn(
              "relative min-h-[240px] flex-1 [container-type:size]",
              // 띠(도움·끊김)가 떠 있으면 작은 휴대폰에서 그림 바닥을 180 → 96px로 낮춘다 — 문장과 [듣기]가 먼저다
              // (2차 검증). 그래도 넘치면 가운데 칸 아래를 흐리게 한다(data-more).
              shownBand ? "small:min-h-[96px]" : "small:min-h-[180px]",
              "wide:col-start-1 wide:row-span-3 wide:row-start-3 wide:my-4 wide:ml-4 wide:min-h-0 tablet:wide:ml-8",
              "animate-step-in motion-reduce:animate-none",
            )}
            data-testid="step-picture-cell"
          >
            <div className="absolute inset-0 flex items-center justify-center">
              <StepPicture step={step} onMediaError={onMediaError} />
            </div>
          </div>

          {/* 가로로 넓은 화면: 문장만 따로 스크롤하고 [듣기]는 문장 칸 오른쪽 위에 고정한다(3차 검증: 예전에는 [듣기]도
              함께 스크롤돼, 띠가 떠 칸이 낮아지면 [듣기]/[멈춤] 글자가 흐림에 가려졌다). */}
          <figcaption
            key={`text-${step.id}`}
            data-testid="step-caption-cell"
            className={cn(
              "flex shrink-0 flex-col gap-1 pb-2 pt-3",
              "wide:col-start-2 wide:row-start-4 wide:min-h-0 wide:pr-4 wide:pt-2 tablet:wide:pr-8",
              "animate-step-in motion-reduce:animate-none",
            )}
          >
            <div className="flex items-start gap-3 wide:min-h-0 wide:flex-1">
              <div
                ref={cellRef}
                data-more={captionMore ? "true" : undefined}
                data-testid="step-caption"
                className={cn(
                  "min-w-0 flex-1 wide:max-h-full wide:self-stretch wide:overflow-y-auto",
                  "wide:data-[more=true]:[mask-image:linear-gradient(to_bottom,#000_calc(100%_-_2rem),transparent)]",
                )}
              >
                <h1
                  ref={h1Ref}
                  tabIndex={-1}
                  data-testid="step-sentence"
                  data-fit={fitLevel}
                  style={{ fontSize: `${sentencePx / 16}rem` }}
                  className="font-bold leading-[1.35] outline-none focus-visible:outline-none"
                >
                  {step.sentence}
                </h1>
              </div>
              {!dotsInTop && speak}
            </div>
            {audio.blocked && (
              <p className="text-right text-worker-caption text-worker-sound-ink hc:text-black">{COPY.step.tapToListen}</p>
            )}
          </figcaption>
        </figure>
      </div>

      <div className="wide:col-start-2 wide:row-start-5 wide:pr-4 tablet:wide:pr-8">
        <BottomBar className="wide:px-0">
          <SecondaryAction
            icon={IconPrev}
            onPress={onPrev}
            disabled={index === 0 || praising}
            className="w-[104px] shrink-0 !gap-1 !px-2 tablet:min-h-[96px]"
          >
            {COPY.btn.prev}
          </SecondaryAction>
          {live ? (
            <PrimaryAction
              icon={praising ? undefined : IconDone}
              onPress={handleDone}
              className="min-w-0 flex-1 !px-3 tablet:min-h-[96px]"
              ariaLabel={praising ? COPY.step.praise : COPY.btn.done}
            >
              {praising ? (
                <span className="inline-flex items-center gap-2">
                  {COPY.step.praise}
                  <IconDone size={32} className="animate-check motion-reduce:animate-none" />
                </span>
              ) : (
                COPY.btn.done
              )}
            </PrimaryAction>
          ) : (
            <PrimaryAction
              icon={IconNext}
              onPress={() => onNext?.()}
              disabled={index >= steps.length - 1}
              className="min-w-0 flex-1 !px-3 tablet:min-h-[96px]"
            >
              {COPY.btn.next}
            </PrimaryAction>
          )}
        </BottomBar>
      </div>

      {confirmExit && (
        <ConfirmScreen
          kind="exit"
          speak={prefs.autoplay_sound}
          ttsRate={prefs.tts_rate}
          onStay={() => setConfirmExit(false)}
          onLeave={() => {
            setConfirmExit(false);
            onExit();
          }}
        />
      )}
    </div>
  );
}
