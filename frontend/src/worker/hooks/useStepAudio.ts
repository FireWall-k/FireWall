// 단계 소리(명세 4.4·4.11, 7.1 SpeakButton + useStepAudio).
// - 단계에 들어가면 autoplay가 켜진 근로자(기본 켬, 창업자 결정 4)에게 1회 자동 재생한다.
// - 사용자가 누른 [듣기]만 다시 듣기(replayCount)로 센다 — 자동 재생이 '어려움 신호'를 부풀리지 않게.
// - 단계가 바뀌거나 화면을 떠나면 멈춘다.
// - 자동 재생이 막히면(새로고침 직후 등) blocked = true → [듣기]에 테두리 + '눌러서 들어요'.
// - 서버 음성 파일(0.9로 합성)이 없거나 못 읽으면 브라우저 음성으로 대신한다. 속도는 tts_rate.
import { useCallback, useEffect, useRef, useState } from "react";
import type { Step } from "../../api";

export interface StepAudio {
  playing: boolean;
  blocked: boolean;
  replayCount: number;
  /** [듣기]/[멈춤] 버튼. */
  toggle: () => void;
  stop: () => void;
}

interface Options {
  autoplay: boolean;
  /** 0.8 / 0.9 / 1.0. */
  rate: number;
  /** 서명 URL이 만료됐을 수 있다 → 새 URL 받기. */
  onMediaError?: (url: string | null | undefined) => void;
}

/** 서버 mp3는 0.9 속도로 합성돼 있다(contract §4.1). */
const SERVER_RATE = 0.9;

export function useStepAudio(step: Pick<Step, "id" | "sentence" | "tts_audio_url"> | null, opts: Options): StepAudio {
  const [playing, setPlaying] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [replay, setReplay] = useState<{ id: string | null; n: number }>({ id: null, n: 0 });
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const token = useRef(0);
  const optsRef = useRef(opts);
  useEffect(() => {
    optsRef.current = opts;
  });

  const stop = useCallback(() => {
    token.current += 1;
    try {
      audioRef.current?.pause();
    } catch {
      /* 무시 */
    }
    audioRef.current = null;
    try {
      window.speechSynthesis?.cancel();
    } catch {
      /* 무시 */
    }
    setPlaying(false);
  }, []);

  const speakFallback = useCallback((text: string, my: number) => {
    try {
      if (!("speechSynthesis" in window) || typeof SpeechSynthesisUtterance === "undefined") {
        setPlaying(false);
        return;
      }
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "ko-KR";
      u.rate = optsRef.current.rate;
      u.onend = () => {
        if (token.current === my) setPlaying(false);
      };
      u.onerror = () => {
        if (token.current === my) setPlaying(false);
      };
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(u);
      setPlaying(true);
    } catch {
      setPlaying(false);
    }
  }, []);

  const play = useCallback(
    (byUser: boolean) => {
      if (!step) return;
      stop();
      const my = token.current;
      const url = step.tts_audio_url;
      if (!url) {
        speakFallback(step.sentence, my);
        if (byUser) setBlocked(false);
        return;
      }
      let audio: HTMLAudioElement;
      try {
        audio = new Audio(url);
      } catch {
        speakFallback(step.sentence, my);
        return;
      }
      audioRef.current = audio;
      try {
        audio.playbackRate = optsRef.current.rate / SERVER_RATE;
      } catch {
        /* 무시 */
      }
      audio.onended = () => {
        if (token.current === my) setPlaying(false);
      };
      setPlaying(true);
      const p = audio.play();
      Promise.resolve(p)
        .then(() => {
          if (token.current === my) setBlocked(false);
        })
        .catch((err: unknown) => {
          if (token.current !== my) return;
          const name = err instanceof Error ? err.name : (err as { name?: string } | null)?.name;
          if (name === "NotAllowedError" && !byUser) {
            // 브라우저가 자동 재생을 막았다. 누르면 들을 수 있다고 알린다(깜빡이지 않음).
            setPlaying(false);
            setBlocked(true);
            return;
          }
          // 파일을 못 읽었다(서명 만료 등): 새 URL을 받아 두고 이번에는 브라우저 음성으로.
          optsRef.current.onMediaError?.(url);
          speakFallback(step.sentence, my);
        });
    },
    [step, stop, speakFallback],
  );

  const stepId = step?.id ?? null;

  // 단계 진입: 자동 1회. 떠날 때: 멈춤.
  useEffect(() => {
    if (!stepId) return;
    if (optsRef.current.autoplay) play(false);
    return () => stop();
    // 단계가 바뀔 때만(서명 URL만 바뀐 경우에는 다시 읽지 않는다).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepId]);

  const toggle = useCallback(() => {
    if (playing) {
      stop();
      return;
    }
    setReplay((r) => ({ id: stepId, n: (r.id === stepId ? r.n : 0) + 1 }));
    setBlocked(false);
    play(true);
  }, [playing, play, stop, stepId]);

  return {
    playing,
    blocked: blocked && !playing,
    replayCount: replay.id === stepId ? replay.n : 0,
    toggle,
    stop,
  };
}
