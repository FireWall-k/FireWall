import { useEffect, useMemo, useRef, useState } from "react";
import { api, AuthError, type HistoryCard, type TodayCard } from "../api";
import { ActionChip } from "../actions";

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

  if (error)
    return <div role="alert" className="rounded-lg bg-red-50 p-4 text-red-800">{error}</div>;
  if (!cards) return <p className="text-slate-500">불러오는 중…</p>;

  return (
    <div className="mx-auto max-w-md">
      <div className="mb-4 flex gap-2">
        <button onClick={() => setMode("today")}
          className={"min-h-touch flex-1 rounded-xl text-worker font-bold " +
            (mode === "today" ? "bg-green-700 text-white" : "bg-slate-100 text-slate-600")}>
          오늘 할 일
        </button>
        <button onClick={() => setMode("history")}
          className={"min-h-touch flex-1 rounded-xl text-worker font-bold " +
            (mode === "history" ? "bg-green-700 text-white" : "bg-slate-100 text-slate-600")}>
          지난 일 보기
        </button>
      </div>

      {mode === "today" ? <TodayView cards={cards} /> : <HistoryView />}
    </div>
  );
}

// ---------- 오늘 할 일 ----------

function TodayView({ cards }: { cards: TodayCard[] }) {
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

  const progressLabel = useMemo(
    () => (total ? `${stepIdx + 1} / ${total}` : ""),
    [stepIdx, total]
  );

  // 실제 음성 재생만 담당(다시듣기 카운트와 분리 → 자동재생이 stuck 신호를 오염시키지 않음).
  function playStep() {
    if (!step) return;
    if (step.tts_audio_url) {
      window.speechSynthesis?.cancel();
      audioRef.current?.pause();
      const audio = new Audio(step.tts_audio_url);
      audioRef.current = audio;
      audio.play().catch(() => playBrowserTts(step.sentence));
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
      <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-600">
        오늘 받은 일이 아직 없어요. 사업주가 일을 보내면 여기에 나타납니다.
      </div>
    );

  if (jobDone)
    return (
      <div className="rounded-2xl border-2 border-green-600 bg-green-50 p-10 text-center">
        <div className="text-6xl">👏</div>
        <p className="mt-4 text-worker-lg font-bold text-green-800">"{card.task_title}" 일을 마쳤어요!</p>
        <p className="mt-2 text-worker text-green-700">다음 일이 {cards.length - cardIdx - 1}개 남았어요.</p>
        <button onClick={startNextJob}
          className="mt-6 min-h-touch w-full rounded-2xl bg-green-700 text-worker-lg font-bold text-white">
          다음 일 시작하기 →
        </button>
      </div>
    );

  if (allDone)
    return (
      <div className="rounded-2xl border-2 border-green-600 bg-green-50 p-10 text-center">
        <div className="text-6xl">🎉</div>
        <p className="mt-4 text-worker-lg font-bold text-green-800">오늘 일을 모두 마쳤어요!</p>
        <p className="mt-2 text-worker text-green-700">정말 잘했어요.</p>
        <p className="mt-4 text-base text-green-700">"지난 일 보기"에서 다시 볼 수 있어요.</p>
      </div>
    );

  return (
    <div>
      <div className="mb-3">
        {cards.length > 1 && (
          <p className="mb-2 text-center text-base font-bold text-green-700">
            오늘 할 일 {cards.length}개 중 {cardIdx + 1}번째
          </p>
        )}
        <div className="flex items-center justify-between">
          <span className="text-base font-medium text-slate-500">{card.task_title}</span>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-base font-bold text-slate-700">
            {progressLabel}
          </span>
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-6 text-center">
        {step?.symbol_url ? (
          <img src={step.symbol_url} alt={step.sentence}
            className="mx-auto h-48 w-48 rounded-xl border border-slate-200 object-contain" />
        ) : (
          <div className="mx-auto flex h-48 w-48 items-center justify-center rounded-xl border-2 border-dashed border-slate-300 text-slate-400">
            그림 없음
          </div>
        )}
        {step && (
          <div className="mt-5 flex justify-center">
            <ActionChip action={step.action_type} className="text-worker" />
          </div>
        )}
        <p className="mt-4 text-worker-lg font-bold leading-snug text-slate-900">{step?.sentence}</p>

        <button onClick={playTts}
          className="mt-6 inline-flex min-h-touch items-center justify-center gap-2 rounded-xl border-2 border-blue-200 bg-blue-50 px-6 text-worker font-semibold text-blue-800">
          🔊 다시 듣기
        </button>
        <p className="mt-2 text-xs text-slate-400">
          {step?.tts_audio_url ? "Google TTS API 음성" : "브라우저 음성 fallback"}
        </p>
      </div>

      {/* 도움 요청: 누르면 이 단계가 '막힘'으로 기록되어 사업주 대시보드에 표시된다 */}
      <button onClick={() => setNeedHelp(true)} aria-pressed={needHelp}
        className={"mt-4 min-h-touch w-full rounded-2xl border-2 text-worker font-semibold " +
          (needHelp
            ? "border-amber-500 bg-amber-100 text-amber-900"
            : "border-amber-300 bg-amber-50 text-amber-800")}>
        {needHelp ? "🙋 도움을 요청했어요" : "🙋 도움이 필요해요"}
      </button>

      <button onClick={completeStep}
        className="mt-3 min-h-touch w-full rounded-2xl bg-green-700 text-worker-lg font-bold text-white">
        ✓ 완료
      </button>
    </div>
  );
}

// ---------- 지난 일 보기(읽기 전용 복습) ----------

function HistoryView() {
  const [items, setItems] = useState<HistoryCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<HistoryCard | null>(null);

  useEffect(() => {
    api.history()
      .then(setItems)
      .catch((e) => setError(e instanceof Error ? e.message : "불러오지 못했습니다."));
  }, []);

  if (error) return <div role="alert" className="rounded-lg bg-red-50 p-4 text-red-800">{error}</div>;
  if (!items) return <p className="text-slate-500">불러오는 중…</p>;

  if (selected) return <HistoryDetail card={selected} onBack={() => setSelected(null)} />;

  if (items.length === 0)
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-600">
        아직 받은 일이 없어요.
      </div>
    );

  return (
    <div className="space-y-3">
      {items.map((c) => {
        const doneCount = c.steps.filter((s) => s.completed).length;
        return (
          <button key={c.assignment_id} onClick={() => setSelected(c)}
            className="flex min-h-touch w-full items-center justify-between rounded-2xl border border-slate-200 bg-white px-5 py-4 text-left">
            <div>
              <p className="text-worker font-bold text-slate-900">{c.task_title}</p>
              <p className="mt-1 text-sm text-slate-500">{c.assigned_date}</p>
            </div>
            <div className="text-right">
              <span className={"rounded-full px-3 py-1 text-sm font-bold " +
                (c.status === "done" ? "bg-green-100 text-green-800" : "bg-amber-100 text-amber-800")}>
                {c.status === "done" ? "완료" : "진행 중"}
              </span>
              <p className="mt-1 text-xs text-slate-400">{doneCount} / {c.steps.length}단계</p>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function HistoryDetail({ card, onBack }: { card: HistoryCard; onBack: () => void }) {
  const [stepIdx, setStepIdx] = useState(0);
  const step = card.steps[stepIdx];
  const total = card.steps.length;

  useEffect(() => {
    if (!step) return;
    if (step.tts_audio_url) {
      const audio = new Audio(step.tts_audio_url);
      audio.play().catch(() => playBrowserTts(step.sentence));
      return;
    }
    playBrowserTts(step.sentence);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step?.id]);

  return (
    <div>
      <button onClick={onBack}
        className="mb-3 inline-flex min-h-touch items-center gap-1 text-worker font-semibold text-slate-600">
        ← 목록으로
      </button>

      <div className="mb-3 flex items-center justify-between">
        <span className="text-base font-medium text-slate-500">{card.task_title}</span>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-base font-bold text-slate-700">
          {stepIdx + 1} / {total}
        </span>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-6 text-center">
        {step?.symbol_url ? (
          <img src={step.symbol_url} alt={step.sentence}
            className="mx-auto h-48 w-48 rounded-xl border border-slate-200 object-contain" />
        ) : (
          <div className="mx-auto flex h-48 w-48 items-center justify-center rounded-xl border-2 border-dashed border-slate-300 text-slate-400">
            그림 없음
          </div>
        )}
        {step && (
          <div className="mt-5 flex justify-center">
            <ActionChip action={step.action_type} className="text-worker" />
          </div>
        )}
        <p className="mt-4 text-worker-lg font-bold leading-snug text-slate-900">{step?.sentence}</p>
        {step?.completed && (
          <p className="mt-2 text-sm font-semibold text-green-700">✓ 완료했어요</p>
        )}

        <button onClick={() => {
          if (!step) return;
          if (step.tts_audio_url) new Audio(step.tts_audio_url).play().catch(() => playBrowserTts(step.sentence));
          else playBrowserTts(step.sentence);
        }}
          className="mt-6 inline-flex min-h-touch items-center justify-center gap-2 rounded-xl border-2 border-blue-200 bg-blue-50 px-6 text-worker font-semibold text-blue-800">
          🔊 다시 듣기
        </button>
      </div>

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
    </div>
  );
}
