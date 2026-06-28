import React, { useEffect, useRef, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useApp } from "../store/AppStore";
import { symbolFor } from "../components/Symbols";
import { Volume2, Check, PartyPopper, ChevronLeft } from "lucide-react";

// 명세서 §6 KWCAG 체크리스트 구현:
// - 한 화면에 정보 1개 (그림 1 + 문장 1 + 완료/다시듣기 버튼만)
// - 터치 영역 최소 80px
// - 텍스트 대비비 4.5:1 이상, 핵심 버튼 7:1 지향
// - TTS 자동 1회 재생 + 다시 듣기 상시 노출
// - 시간 제한 없음, 자동 넘김 금지
// - 완료 시 시각+청각 긍정 피드백

export const WorkerCardPage: React.FC = () => {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const { getTask, tasks } = useApp();

  const task = taskId ? getTask(taskId) : tasks.find((t) => t.status === "published");
  const [stepIndex, setStepIndex] = useState(0);
  const [showCelebration, setShowCelebration] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [allDone, setAllDone] = useState(false);
  const hasAutoPlayedRef = useRef<number>(-1);

  const steps = task?.steps ?? [];
  const currentStep = steps[stepIndex];

  const speak = useCallback((text: string) => {
    if (!("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = "ko-KR";
    utter.rate = 0.95;
    utter.onstart = () => setIsSpeaking(true);
    utter.onend = () => setIsSpeaking(false);
    window.speechSynthesis.speak(utter);
  }, []);

  // 카드 진입 시 TTS 자동 1회 재생 (명세서 §6)
  useEffect(() => {
    if (!currentStep) return;
    if (hasAutoPlayedRef.current === stepIndex) return;
    hasAutoPlayedRef.current = stepIndex;
    const t = setTimeout(() => speak(currentStep.sentence), 350);
    return () => clearTimeout(t);
  }, [stepIndex, currentStep, speak]);

  useEffect(() => {
    return () => window.speechSynthesis?.cancel();
  }, []);

  if (!task) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-worker-bg">
        <p className="font-worker text-2xl text-worker-ink">오늘은 배정된 작업이 없어요.</p>
      </div>
    );
  }

  if (allDone) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-worker-bg px-8 text-center">
        <div className="flex h-28 w-28 items-center justify-center rounded-full bg-worker-accent text-white">
          <PartyPopper size={56} />
        </div>
        <h1 className="font-worker text-4xl font-extrabold text-worker-ink">오늘 일을 다 끝냈어요!</h1>
        <p className="font-worker text-xl text-worker-ink/70">정말 잘했어요. 수고하셨습니다.</p>
        <button
          onClick={() => navigate("/admin/tasks")}
          className="mt-4 rounded-2xl bg-worker-ink/10 px-6 py-3 font-worker text-base font-semibold text-worker-ink/70 hover:bg-worker-ink/20"
        >
          관리자 화면으로 돌아가기
        </button>
      </div>
    );
  }

  const handleComplete = () => {
    setShowCelebration(true);
    // 짧은 긍정 피드백 후 다음 단계로 (자동 넘김이 아니라, 완료 확인 누른 뒤 잠깐의 축하 표시)
    setTimeout(() => {
      setShowCelebration(false);
      if (stepIndex + 1 < steps.length) {
        setStepIndex((i) => i + 1);
      } else {
        setAllDone(true);
      }
    }, 900);
  };

  const SymbolIcon = currentStep ? symbolFor(currentStep.actionType) : symbolFor("other");
  const progress = `${stepIndex + 1} / ${steps.length}`;

  return (
    <div className="flex min-h-screen flex-col bg-worker-bg font-worker">
      {/* 상단: 진행 표시만, 부가 정보 없음 */}
      <div className="flex items-center justify-between px-6 py-4">
        <button
          onClick={() => navigate("/admin/tasks")}
          aria-label="관리자 화면으로 돌아가기"
          className="flex h-12 w-12 items-center justify-center rounded-full text-worker-ink/40 hover:bg-worker-ink/5"
        >
          <ChevronLeft size={26} />
        </button>
        <div className="flex gap-2">
          {steps.map((_, i) => (
            <div
              key={i}
              className={`h-2.5 rounded-full transition-all ${
                i === stepIndex
                  ? "w-8 bg-worker-accent"
                  : i < stepIndex
                  ? "w-2.5 bg-worker-accent/50"
                  : "w-2.5 bg-worker-ink/10"
              }`}
            />
          ))}
        </div>
        <span className="w-12 text-right text-sm font-medium text-worker-ink/40">{progress}</span>
      </div>

      {/* 메인: 그림 1개 + 문장 1개만 */}
      <div className="flex flex-1 flex-col items-center justify-center px-8">
        {showCelebration ? (
          <div className="flex flex-col items-center gap-5 animate-[fadeIn_0.2s_ease-out]">
            <div className="flex h-40 w-40 items-center justify-center rounded-full bg-worker-accent text-white">
              <Check size={84} strokeWidth={3} />
            </div>
            <p className="text-worker-sentence text-worker-accentDark">잘했어요!</p>
          </div>
        ) : (
          <>
            <div className="mb-10 flex h-64 w-64 items-center justify-center rounded-[2rem] bg-worker-card shadow-[0_8px_30px_rgba(0,0,0,0.08)]">
              <SymbolIcon className="h-44 w-44" />
            </div>
            <p className="max-w-xl text-center text-worker-sentence text-worker-ink">
              {currentStep?.sentence}
            </p>
          </>
        )}
      </div>

      {/* 하단: 완료 / 다시 듣기 버튼만 (각 80px 이상) */}
      {!showCelebration && (
        <div className="flex gap-4 px-6 pb-8">
          <button
            onClick={() => currentStep && speak(currentStep.sentence)}
            aria-label="문장 다시 듣기"
            className={`flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl bg-white text-worker-accent shadow-sm transition-transform active:scale-95 ${
              isSpeaking ? "ring-4 ring-worker-accent/30" : ""
            }`}
          >
            <Volume2 size={32} />
          </button>
          <button
            onClick={handleComplete}
            className="flex h-20 flex-1 items-center justify-center gap-3 rounded-2xl bg-worker-accent text-worker-button text-white shadow-sm transition-transform active:scale-[0.98] hover:bg-worker-accentDark"
          >
            <Check size={30} strokeWidth={3} />
            다 했어요
          </button>
        </div>
      )}
    </div>
  );
};
