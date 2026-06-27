import { useEffect, useMemo, useRef, useState } from "react";
import { api, AuthError, type TodayCard } from "../api";
import { ActionChip } from "../actions";

// 자동 '막힘' 감지 임계값. 이 신호가 대시보드 stuck_steps로 전달된다.
const STUCK_REPLAY_THRESHOLD = 3; // 다시듣기 3회 이상
const STUCK_DURATION_SEC = 120; // 한 단계 2분 초과

export default function WorkerPage() {
  const [cards, setCards] = useState<TodayCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    api.today()
      .then((c) => setCards(c))
      .catch((e) => setError(e instanceof AuthError ? "다시 로그인해 주세요." : (e instanceof Error ? e.message : "불러오지 못했습니다.")));
  }, []);

  const card = cards?.[cardIdx] ?? null;
  const step = card?.steps[stepIdx] ?? null;
  const total = card?.steps.length ?? 0;

  const progressLabel = useMemo(
    () => (total ? `${stepIdx + 1} / ${total}` : ""),
    [stepIdx, total]
  );

  function playBrowserTts(text: string) {
    if (!("speechSynthesis" in window)) return;
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "ko-KR";
    u.rate = 0.9;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  }

  function playTts() {
    if (!step) return;
    setReplayCount((n) => n + 1);
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
      if (cardIdx + 1 >= (cards?.length ?? 0)) {
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

  if (error)
    return <div role="alert" className="rounded-lg bg-red-50 p-4 text-red-800">{error}</div>;
  if (!cards) return <p className="text-slate-500">불러오는 중…</p>;
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
        <p className="mt-2 text-worker text-green-700">다음 일이 {(cards?.length ?? 0) - cardIdx - 1}개 남았어요.</p>
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
      </div>
    );

  return (
    <div className="mx-auto max-w-md">
      <div className="mb-3">
        {(cards?.length ?? 0) > 1 && (
          <p className="mb-2 text-center text-base font-bold text-green-700">
            오늘 할 일 {cards?.length}개 중 {cardIdx + 1}번째
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
