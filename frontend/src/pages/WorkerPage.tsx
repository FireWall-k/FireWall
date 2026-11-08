import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { api, AuthError, type HistoryCard, type Step, type TodayCard } from "../api";
import { WorkerActionChip } from "../actions";
import { mergeStepMedia, useMediaRefresh } from "../media";
import { cn } from "../cn";

// 자동 '막힘' 감지 임계값. 이 신호가 대시보드 stuck_steps로 전달된다.
const STUCK_REPLAY_THRESHOLD = 3; // 다시듣기 3회 이상
const STUCK_DURATION_SEC = 120; // 한 단계 2분 초과

function playBrowserTts(text: string) {
  if (!("speechSynthesis" in window)) return;
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "ko-KR";
  u.rate = 0.9;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(u);
}

export default function WorkerPage() {
  const [cards, setCards] = useState<TodayCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // "오늘 할 일"은 완료하면 목록에서 빠진다 — 다시 볼 수 있도록 "지난 일" 탭을 둔다.
  const [mode, setMode] = useState<"today" | "history">("today");

  useEffect(() => {
    api.today()
      .then((c) => setCards(c))
      .catch((e) => setError(e instanceof AuthError ? "다시 로그인해 주세요." : (e instanceof Error ? e.message : "불러오지 못했습니다.")));
  }, []);

  // 사진·음성 서명 URL이 만료되면(화면을 오래 켜 둔 경우) 오늘 카드를 다시 받아 URL만 바꿔 끼운다.
  const onMediaError = useMediaRefresh(async () => {
    const fresh = await api.today();
    setCards((cur) => (cur ? mergeStepMedia(cur, fresh) : cur));
  });

  if (error)
    return <div role="alert" className="rounded-lg bg-red-50 p-4 text-red-800">{error}</div>;
  if (!cards) return <p className="text-slate-500">불러오는 중…</p>;

  // 위쪽 탭(오늘 할 일 / 지난 일 보기)은 없앴다. 휴대폰에서 그 줄(96px)이 그림 자리를 먹어 "완료"가 첫 화면
  // 밖으로 밀렸다. "지난 일 보기"는 오늘 할 일 화면 맨 아래로, 돌아오기는 지난 일 화면 맨 위로 옮겼다.
  // wide:!max-w-5xl — wide 변형의 CSS가 md: 보다 앞에 나와 md:max-w-2xl에 덮이므로 !important로 이긴다.
  return (
    <div className="mx-auto w-full max-w-md md:max-w-2xl wide:!max-w-5xl">
      {mode === "today" ? (
        <>
          <TodayView cards={cards} onMediaError={onMediaError} />
          <button onClick={() => setMode("history")}
            className="mx-auto mt-6 block min-h-touch w-full rounded-2xl border-2 border-slate-200 bg-white text-worker font-semibold text-slate-700 wide:max-w-2xl">
            지난 일 보기
          </button>
        </>
      ) : (
        <HistoryView onToday={() => setMode("today")} />
      )}
    </div>
  );
}

// ---------- 단계 화면 공통 ----------

// 단계 화면이 휴대폰 한 화면(머리글 아래 남은 높이)을 꼭 채우게 하고, 넘치면 글씨를 한 단계씩 줄인다.
//
// 1) 채우기: 그림 칸이 flex-1이라 남는 높이를 그림이 다 가져간다. 머리글 높이는 이름 길이·글꼴에 따라
//    달라질 수 있어 상수로 빼지 않고 실제 위치를 잰다. 아래 여백 0.75rem은 근로자 Shell의 py-3(App.tsx)과 같다.
// 2) 맞추기: 그림이 바닥(min-h)까지 줄었는데도 "완료"가 화면 아래로 넘치면(작은 휴대폰 360×740·375×667,
//    긴 문장, 글자 크기를 키운 휴대폰) 한 단계씩 줄인다.
//      0: 문장 32px(text-worker-lg) · 동작 꼬리표 · 그림 바닥 min(10rem, 20dvh)
//      1: 문장 24px(text-worker)
//      2: 동작 꼬리표를 접고 카드 안 여백을 줄인다
//      3: 그림 바닥을 min(8rem, 15dvh)로 낮춘다
//      4: 그래도 넘치면(100자가 넘는 문장을 작은 화면·큰 글자로 볼 때) 한 화면에 넣기를 포기하고 스크롤한다.
//         이때는 그림을 작게 둘 까닭이 없으므로 1단계 모양(큰 그림 바닥·꼬리표)으로 되돌린다. 단계가 바뀌면 맨 위로 돌아간다.
//    문장은 근로자 글씨 크기(text-worker, 24px) 아래로 내리지 않는다(Phase 0.4 큰 글씨) — 남는 자리는 꼬리표와
//    그림이 양보한다. 터치 영역(80px)도 줄이지 않는다. 단계가 바뀌거나 화면 크기가 바뀌면 처음 단계부터 다시 잰다.
//    useLayoutEffect 안에서 고치므로 줄이는 과정이 화면에 깜빡이지 않는다.
const FIT_MAX = 4;
type FitLevel = 0 | 1 | 2 | 3 | 4;

function useStepScreenFit(stepKey: string) {
  // 콜백 ref로 받는다: 직무 완료 화면 → 다음 직무처럼 단계 화면이 다시 그려지면 새 요소에서 다시 잰다.
  const [el, setEl] = useState<HTMLDivElement | null>(null);
  const [top, setTop] = useState<number | null>(null);
  const [tick, setTick] = useState(0);
  const [fit, setFit] = useState<{ key: string; level: FitLevel }>({ key: "", level: 0 });
  const key = `${stepKey}#${tick}`;
  const level: FitLevel = fit.key === key ? fit.level : 0;

  useLayoutEffect(() => {
    if (!el) return;
    const measure = () => {
      setTop(Math.max(0, Math.round(el.getBoundingClientRect().top + window.scrollY)));
      setTick((t) => t + 1);
    };
    measure();
    window.addEventListener("resize", measure);
    // 웹폰트가 늦게 들어오면 머리글·문장 높이가 바뀔 수 있다.
    document.fonts?.ready.then(measure).catch(() => {});
    return () => window.removeEventListener("resize", measure);
  }, [el]);

  // 그린 결과를 재서 한 단계 줄이는 것이라 렌더 중에는 알 수 없다(레이아웃 측정 → 다시 그리기). 단계는
  // 최대 FIT_MAX번만 올라가므로 되풀이가 끝없이 이어지지 않는다.
  useLayoutEffect(() => {
    if (!el || level >= FIT_MAX) return;
    const shrinkIfCrowded = () => {
      // ① 단계 화면 전체(그림·문장·버튼)의 아래 끝이 첫 화면 밖이면 줄인다. 0.5px은 반올림 여유.
      const bottom = el.getBoundingClientRect().bottom + window.scrollY;
      const overflowing = bottom > window.innerHeight + 0.5;
      // ② 다 들어와도 그림이 10rem(160px)보다 작으면 문장을 32px → 24px로 줄이고, 그래도 작으면 꼬리표를 접어
      //    그림 자리를 늘린다 — 작은 휴대폰(375×667)에서 32px 문장이 두 줄을 먹고 그림이 133px로 줄던 것. 그림이
      //    꼬리표보다 중요하다. 3단계는 그림 바닥을 낮추는 단계라 그림을 키우지 못하므로 넘칠 때만 쓴다.
      const pic = el.querySelector("[data-testid='step-picture']")?.getBoundingClientRect();
      const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
      // 크기가 0이면 아직 배치되지 않은 것(숨김·레이아웃 없는 환경)이라 판단하지 않는다.
      const side = pic ? Math.min(pic.width, pic.height) : 0;
      const pictureSmall = side > 0 && side < 10 * rem - 0.5 && level < 2;
      if (overflowing || pictureSmall) setFit({ key, level: (level + 1) as FitLevel });
    };
    shrinkIfCrowded();
  }, [el, key, level]);

  const style: CSSProperties | undefined =
    top == null ? undefined : { minHeight: `calc(100dvh - ${top}px - 0.75rem)` };
  return [setEl, style, level] as const;
}

// 진행 표시는 하나만 둔다: 이 일의 이름 + "1 / 4" + 칸 막대. 예전에는 "오늘 할 일 2개 중 1번째"가 같이 떠서
// 숫자가 두 벌이었다 — 몇 번째 일인지는 일과 일 사이 화면(직무 완료 화면)에서 목록으로 보여 준다.
function StepProgress({ title, current, total }: { title: string; current: number; total: number }) {
  return (
    <div data-testid="step-progress" className="mb-2 wide:col-span-2">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-balance text-xl font-bold text-slate-800">{title}</h2>
        <span className="shrink-0 text-xl font-bold text-slate-700">{current} / {total}</span>
      </div>
      <div role="progressbar" aria-label={`${title} 진행`} aria-valuemin={1} aria-valuemax={total}
        aria-valuenow={current} aria-valuetext={`${total}단계 중 ${current}단계`}
        className="mt-1.5 flex gap-1">
        {Array.from({ length: total }, (_, i) => (
          <span key={i} className={cn("h-2.5 flex-1 rounded-full", i < current ? "bg-green-600" : "bg-slate-200")} />
        ))}
      </div>
    </div>
  );
}

// 단계 카드: 그림 한 장 + 동작 꼬리표 + 문장. 그림이 화면의 주인공이다.
// 그림 칸은 남은 높이를 다 가져가고(flex-1), 그 안에서 칸의 가로·세로 중 짧은 쪽에 맞춘 정사각형으로 그린다
// (100cqmin). 그래서 휴대폰에서는 가로를 거의 다 쓰고, 문장이 길면 잘리지 않고 작아진다. 바닥은
// min(160px, 화면 높이의 20%) — 그보다 작으면 그림을 알아보기 어렵고, 작은 휴대폰(667px)에서는 160px을
// 고집하면 "완료"가 화면 밖으로 밀린다. 그래도 넘치면(맞추기 2·3단계) 문장 글씨 대신 그림 바닥을 낮춘다.
const PICTURE_FLOOR: Record<FitLevel, string> = {
  0: "min-h-[min(10rem,20dvh)]",
  1: "min-h-[min(10rem,20dvh)]",
  2: "min-h-[min(10rem,20dvh)]",
  3: "min-h-[min(8rem,15dvh)]",
  4: "min-h-[min(10rem,20dvh)]", // 스크롤하기로 한 단계 — 그림을 다시 키운다
};
// 2·3단계(꼭 맞춰 넣는 단계)에서만 꼬리표를 접고 카드 안 여백을 줄인다.
const tight = (level: FitLevel) => level === 2 || level === 3;

function StepCard({ step, level, onMediaError, children }: {
  step: Step;
  level: FitLevel;
  onMediaError: (url: string | null | undefined) => void;
  children?: ReactNode;
}) {
  return (
    <div className={cn("flex min-h-0 flex-1 flex-col rounded-2xl border border-slate-200 bg-white text-center",
      tight(level) ? "p-2" : "p-3")}>
      <div className={cn("relative max-h-[100cqw] flex-1", PICTURE_FLOOR[level])}>
        <div data-testid="step-picture" className="absolute inset-0 flex items-center justify-center [container-type:size]">
          {step.symbol_url ? (
            <img src={step.symbol_url} alt={step.sentence}
              onError={() => onMediaError(step.symbol_url)}
              className="size-[100cqmin] rounded-xl border border-slate-200 object-contain" />
          ) : (
            // 대체 박스·보조 글씨는 slate-600(대비 7.6:1)으로 둔다. 예전 slate-400은 2.6:1이라 저시력 근로자가 읽기 어렵고 axe가 serious로 잡았다(Phase 0.4 e2e).
            <div className="flex size-[100cqmin] items-center justify-center rounded-xl border-2 border-dashed border-slate-300 text-worker text-slate-600">
              그림 없음
            </div>
          )}
        </div>
      </div>
      {!tight(level) && (
        <div className="mt-2 flex justify-center empty:hidden">
          <WorkerActionChip sentence={step.sentence} className={level === 0 ? "text-worker" : "text-lg"} />
        </div>
      )}
      <p data-testid="step-sentence" data-fit={level}
        className={cn("text-pretty font-bold leading-snug text-slate-900", tight(level) ? "mt-1" : "mt-2",
          level === 0 ? "text-worker-lg" : "text-worker")}>
        {step.sentence}
      </p>
      {children}
    </div>
  );
}

// 단계 화면 배치. 휴대폰·세로 태블릿은 위에서 아래로(진행 → 그림·문장 → 버튼), 가로로 넓은 화면
// (wide: 가로 방향·폭 768px 이상)은 왼쪽에 그림·문장, 오른쪽에 버튼을 둬 그림이 화면 높이를 다 쓰게 한다.
function StepScreen({ title, current, total, step, onMediaError, note, children }: {
  title: string;
  current: number;
  total: number;
  step: Step;
  onMediaError: (url: string | null | undefined) => void;
  note?: ReactNode;
  children: ReactNode;
}) {
  const [fillEl, fillStyle, fitLevel] = useStepScreenFit(step.id);
  // 넘쳐서 스크롤해 "완료"를 누른 경우, 다음 단계는 제목·진행 막대부터 보이게 맨 위에서 시작한다.
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [step.id]);
  return (
    <div ref={fillEl} style={fillStyle}
      className="flex flex-col [container-type:inline-size] wide:grid wide:grid-cols-[minmax(0,1fr)_minmax(16rem,22rem)] wide:grid-rows-[auto_minmax(0,1fr)] wide:gap-x-4">
      <StepProgress title={title} current={current} total={total} />
      <StepCard step={step} level={fitLevel} onMediaError={onMediaError}>{note}</StepCard>
      <div className="flex flex-col [container-type:inline-size] wide:justify-end">{children}</div>
    </div>
  );
}

// ---------- 오늘 할 일 ----------

function TodayView({ cards, onMediaError }: {
  cards: TodayCard[];
  onMediaError: (url: string | null | undefined) => void;
}) {
  const [cardIdx, setCardIdx] = useState(0); // 오늘 받은 여러 직무 중 현재 보는 직무
  const [stepIdx, setStepIdx] = useState(0);
  const [replayCount, setReplayCount] = useState(0);
  const [needHelp, setNeedHelp] = useState(false);
  const stepStartRef = useRef<number>(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [jobDone, setJobDone] = useState(false); // 현재 직무 완료(다음 직무 대기)
  const [allDone, setAllDone] = useState(false); // 오늘 받은 모든 직무 완료

  useEffect(() => {
    stepStartRef.current = Date.now();
  }, []);

  const card = cards[cardIdx] ?? null;
  const step = card?.steps[stepIdx] ?? null;
  const total = card?.steps.length ?? 0;

  // 직무 완료·전체 완료 화면은 맨 위에서 시작한다(스크롤해 "완료"를 누른 채로 넘어오면 축하 문구가 화면 밖이다).
  useEffect(() => {
    if (jobDone || allDone) window.scrollTo({ top: 0 });
  }, [jobDone, allDone]);

  // 실제 음성 재생만 담당(다시듣기 카운트와 분리 → 자동재생이 stuck 신호를 오염시키지 않음).
  function playStep() {
    if (!step) return;
    if (step.tts_audio_url) {
      window.speechSynthesis?.cancel();
      audioRef.current?.pause();
      const url = step.tts_audio_url;
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.play().catch(() => {
        playBrowserTts(step.sentence);
        // 서명 URL이 만료됐을 수 있다. 다음 재생은 새로 받은 URL로 한다.
        onMediaError(url);
      });
      return;
    }
    playBrowserTts(step.sentence);
  }

  // '다시 듣기' 버튼: 사용자가 직접 누른 재생이므로 replayCount를 올린다.
  function playTts() {
    setReplayCount((n) => n + 1);
    playStep();
  }

  // 단계가 바뀌면(첫 진입 포함) 다시듣기를 누르지 않아도 1회 자동 재생한다.
  useEffect(() => {
    if (!step) return;
    playStep();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step?.id]);

  // 도움 요청은 누른 즉시 '막힘'으로 서버에 기록해 사업주 대시보드에 바로 보이게 한다.
  // 완료 버튼을 눌러야만 반영되면, 근로자가 그 단계에 머무는 동안은 대시보드가 아무 일도
  // 없는 것처럼 보인다 — 도움이 필요한 순간과 사업주가 아는 순간 사이에 지연이 생긴다.
  // 단계는 넘기지 않는다(완료는 여전히 "완료" 버튼으로만 한다).
  async function reportHelpNow() {
    if (!card || !step || needHelp) return; // 이미 요청한 단계에서 다시 눌러도 중복 보고하지 않는다.
    setNeedHelp(true);
    const duration = (Date.now() - stepStartRef.current) / 1000;
    try {
      await api.logStep({
        assignment_id: card.assignment_id,
        step_id: step.id,
        duration_sec: Math.round(duration * 10) / 10,
        replay_count: replayCount,
        stuck: true,
      });
    } catch {
      // 오프라인이어도 화면 표시(요청했어요)는 유지한다. 완료 시 다시 한번 보고된다.
    }
  }

  async function completeStep() {
    if (!card || !step) return;
    const duration = (Date.now() - stepStartRef.current) / 1000;
    // 실제 stuck 신호: 본인 도움요청 OR 다시듣기 과다 OR 소요시간 초과
    const stuck =
      needHelp ||
      replayCount >= STUCK_REPLAY_THRESHOLD ||
      duration >= STUCK_DURATION_SEC;
    try {
      await api.logStep({
        assignment_id: card.assignment_id,
        step_id: step.id,
        duration_sec: Math.round(duration * 10) / 10,
        replay_count: replayCount,
        stuck,
      });
    } catch {
      // 오프라인이어도 진행은 막지 않는다(향후 로컬 큐 동기화).
    }
    audioRef.current?.pause();
    window.speechSynthesis?.cancel();
    if (stepIdx + 1 >= total) {
      // 이 직무의 마지막 단계 완료 → 다음 직무가 있으면 대기 화면, 없으면 전체 완료
      if (cardIdx + 1 >= cards.length) {
        setAllDone(true);
      } else {
        setJobDone(true);
      }
    } else {
      setStepIdx((i) => i + 1);
      setReplayCount(0);
      setNeedHelp(false);
      stepStartRef.current = Date.now();
    }
  }

  const nextIdx = cardIdx + 1; // 직무 완료 화면 목록에서 "다음" 표시

  function startNextJob() {
    setCardIdx((i) => i + 1);
    setStepIdx(0);
    setReplayCount(0);
    setNeedHelp(false);
    setJobDone(false);
    stepStartRef.current = Date.now();
  }

  if (!card)
    return (
      <div className="mx-auto rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-600 wide:max-w-2xl">
        오늘 받은 일이 아직 없어요. 사업주가 일을 보내면 여기에 나타납니다.
      </div>
    );

  // 직무 사이 화면: 누를 것("다음 일 시작하기")을 축하 문구 바로 아래, 목록보다 위에 둔다. 목록을 버튼 위에
  // 두면 오늘 할 일이 4~5개이거나 글자를 키운 작은 휴대폰에서 버튼이 첫 화면 밖으로 밀렸다(3차 검증).
  if (jobDone)
    return (
      <div className="mx-auto rounded-2xl border-2 border-green-600 bg-green-50 px-4 py-5 text-center wide:max-w-2xl">
        <p className="text-balance text-worker-lg font-bold text-green-800">
          <span aria-hidden="true">👏 </span>"{card.task_title}" 일을 마쳤어요!
        </p>
        <button onClick={startNextJob}
          className="mt-4 min-h-touch w-full text-balance rounded-2xl bg-green-700 px-3 text-worker-lg font-bold leading-tight text-white">
          다음 일 시작하기 →
        </button>
        {/* 오늘 받은 일 중 몇 번째인지는 단계 화면이 아니라 여기(일과 일 사이)에서 목록으로 보여 준다. */}
        <p className="mt-5 text-worker text-green-700">오늘 할 일 {cards.length}개 중 {cardIdx + 1}개를 마쳤어요.</p>
        <ol aria-label="오늘 할 일" className="mx-auto mt-2 max-w-sm space-y-1 text-left">
          {cards.map((c, i) => (
            <li key={c.assignment_id}
              className={cn("flex items-baseline gap-3 rounded-xl px-3 py-1 text-worker leading-snug",
                i <= cardIdx ? "text-green-800" : i === nextIdx ? "bg-white font-bold text-slate-900" : "text-slate-700")}>
              <span aria-hidden="true" className="w-5 shrink-0 text-center">{i <= cardIdx ? "✓" : i === nextIdx ? "→" : "·"}</span>
              <span className="text-pretty">{c.task_title}</span>
            </li>
          ))}
        </ol>
      </div>
    );

  if (allDone)
    return (
      <div className="mx-auto rounded-2xl border-2 border-green-600 bg-green-50 p-10 text-center wide:max-w-2xl">
        <div className="text-6xl">🎉</div>
        <p className="mt-4 text-balance text-worker-lg font-bold text-green-800">오늘 일을 모두 마쳤어요!</p>
        <p className="mt-2 text-worker text-green-700">정말 잘했어요.</p>
        <p className="mt-4 text-base text-green-700">아래 "지난 일 보기"에서 다시 볼 수 있어요.</p>
      </div>
    );

  if (!step) return null;

  return (
    <StepScreen title={card.task_title} current={stepIdx + 1} total={total} step={step} onMediaError={onMediaError}>
      {/* 도움 요청: 누르는 즉시 이 단계가 '막힘'으로 기록되어 사업주 대시보드에 바로 표시된다.
          단계는 넘기지 않는다 — 다음 단계로 가려면 "완료"를 따로 눌러야 한다.
          다시 듣기와 한 줄에 둬서 "완료"가 휴대폰 첫 화면 안에 들어오게 한다. 반쪽 버튼에 글자가 다 안 들어가면
          낱말 경계에서 두 줄이 된다("🔊 다시 / 듣기"). 한 줄에 하나씩 쌓으면 버튼 한 개(80px + 간격)만큼 그림
          자리를 잃어, 작은 휴대폰·큰 글자에서 "완료"가 화면 밖으로 밀렸다 — 그래서 칸이 아주 좁을 때(16rem 미만:
          "필요해요" 한 낱말도 반쪽에 안 들어가는 폭)만 쌓는다. rem 기준이라 글자 크기를 키우면 그만큼 일찍 쌓인다. */}
      <div className="mt-3 grid grid-cols-1 gap-3 [@container(min-width:16rem)]:grid-cols-2">
        <button onClick={playTts}
          className="inline-flex min-h-touch items-center justify-center gap-x-2 rounded-2xl border-2 border-blue-200 bg-blue-50 px-1 text-worker font-semibold leading-tight text-blue-800">
          🔊 다시 듣기
        </button>
        <button onClick={reportHelpNow} aria-pressed={needHelp}
          className={cn("min-h-touch rounded-2xl border-2 px-1 text-worker font-semibold leading-tight",
            needHelp
              ? "border-amber-500 bg-amber-100 text-amber-900"
              : "border-amber-300 bg-amber-50 text-amber-800")}>
          {/* 누른 뒤 글자는 짧게 둔다("도움을 요청했어요"는 반쪽 버튼에서 낱말이 쪼개졌다). 좁은 반쪽 버튼에서
              "요청했어요" 한 낱말이 안 들어가면 "요청했어 / 요"가 아니라 말의 마디인 "요청 / 했어요"에서 넘긴다(<wbr>).
              그림 글자(🙋)는 첫 낱말과 붙여 둔다 — 혼자 한 줄을 차지하면 버튼이 세 줄(117px)로 커져 "완료"를 밀어낸다. */}
          {needHelp
            ? <><span className="whitespace-nowrap">🙋 요청</span><wbr />했어요</>
            : <><span className="whitespace-nowrap">🙋 도움이</span> 필요해요</>}
        </button>
      </div>

      <button onClick={completeStep}
        className="mt-3 min-h-touch w-full rounded-2xl bg-green-700 text-worker-lg font-bold text-white">
        ✓ 완료
      </button>
    </StepScreen>
  );
}

// ---------- 지난 일 보기(읽기 전용 복습) ----------

function HistoryView({ onToday }: { onToday: () => void }) {
  const [items, setItems] = useState<HistoryCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 고른 카드를 객체가 아니라 id로 기억한다. 서명 URL을 다시 받아 items를 바꿔 끼우면 상세 화면도 새 URL을 본다.
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    api.history()
      .then(setItems)
      .catch((e) => setError(e instanceof Error ? e.message : "불러오지 못했습니다."));
  }, []);

  const onMediaError = useMediaRefresh(async () => {
    const fresh = await api.history();
    setItems((cur) => (cur ? mergeStepMedia(cur, fresh) : cur));
  });

  const selected = items?.find((c) => c.assignment_id === selectedId) ?? null;
  // 상세 화면에는 "← 목록으로" 하나만 둔다(되돌아가기 버튼이 두 줄이면 그림 자리를 또 먹는다).
  if (selected)
    return <HistoryDetail card={selected} onBack={() => setSelectedId(null)} onMediaError={onMediaError} />;

  const backToToday = (
    <button onClick={onToday}
      className="mb-3 min-h-touch w-full rounded-2xl border-2 border-slate-200 bg-white text-worker font-semibold text-slate-700">
      ← 오늘 할 일로
    </button>
  );

  // 목록 화면은 가로로 넓은 화면(wide)에서도 단계 화면처럼 넓히지 않는다 — 한 줄이 너무 길어진다.
  const narrow = (children: ReactNode) => <div className="mx-auto space-y-3 wide:max-w-2xl">{children}</div>;

  if (error) return narrow(<>{backToToday}<div role="alert" className="rounded-lg bg-red-50 p-4 text-red-800">{error}</div></>);
  if (!items) return narrow(<>{backToToday}<p className="text-slate-500">불러오는 중…</p></>);

  if (items.length === 0)
    return narrow(
      <>
        {backToToday}
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-600">
          아직 받은 일이 없어요.
        </div>
      </>,
    );

  return narrow(
    <>
      {backToToday}
      {items.map((c) => {
        const doneCount = c.steps.filter((s) => s.completed).length;
        return (
          <button key={c.assignment_id} onClick={() => setSelectedId(c.assignment_id)}
            className="flex min-h-touch w-full items-center justify-between rounded-2xl border border-slate-200 bg-white px-5 py-4 text-left">
            <div>
              <p className="text-worker font-bold text-slate-900">{c.task_title}</p>
              <p className="mt-1 text-sm text-slate-500">{c.assigned_date}</p>
            </div>
            <div className="text-right">
              <span className={cn("rounded-full px-3 py-1 text-sm font-bold",
                c.status === "done" ? "bg-green-100 text-green-800" : "bg-amber-100 text-amber-800")}>
                {c.status === "done" ? "완료" : "진행 중"}
              </span>
              <p className="mt-1 text-xs text-slate-600">{doneCount} / {c.steps.length}단계</p>
            </div>
          </button>
        );
      })}
    </>,
  );
}

function HistoryDetail({ card, onBack, onMediaError }: {
  card: HistoryCard;
  onBack: () => void;
  onMediaError: (url: string | null | undefined) => void;
}) {
  const [stepIdx, setStepIdx] = useState(0);
  const step = card.steps[stepIdx];
  const total = card.steps.length;

  useEffect(() => {
    if (!step) return;
    if (step.tts_audio_url) {
      const url = step.tts_audio_url;
      const audio = new Audio(url);
      audio.play().catch(() => {
        playBrowserTts(step.sentence);
        onMediaError(url);
      });
      return;
    }
    playBrowserTts(step.sentence);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step?.id]);

  if (!step) return null;

  return (
    <div>
      <button onClick={onBack}
        className="mb-3 inline-flex min-h-touch items-center gap-1 text-worker font-semibold text-slate-600">
        ← 목록으로
      </button>

      <StepScreen title={card.task_title} current={stepIdx + 1} total={total} step={step} onMediaError={onMediaError}
        note={step.completed && <p className="mt-2 text-sm font-semibold text-green-700">✓ 완료했어요</p>}>
        <button onClick={() => {
          const url = step.tts_audio_url;
          if (url) new Audio(url).play().catch(() => {
            playBrowserTts(step.sentence);
            onMediaError(url);
          });
          else playBrowserTts(step.sentence);
        }}
          className="mt-3 inline-flex min-h-touch items-center justify-center gap-2 rounded-2xl border-2 border-blue-200 bg-blue-50 px-6 text-worker font-semibold text-blue-800">
          🔊 다시 듣기
        </button>

        <div className="mt-3 flex gap-2">
          <button onClick={() => setStepIdx((i) => Math.max(0, i - 1))} disabled={stepIdx === 0}
            className="min-h-touch flex-1 rounded-2xl border-2 border-slate-200 text-worker font-semibold text-slate-700 disabled:opacity-40">
            ← 이전
          </button>
          <button onClick={() => setStepIdx((i) => Math.min(total - 1, i + 1))} disabled={stepIdx >= total - 1}
            className="min-h-touch flex-1 rounded-2xl bg-green-700 text-worker font-bold text-white disabled:opacity-40">
            다음 →
          </button>
        </div>
      </StepScreen>
    </div>
  );
}
