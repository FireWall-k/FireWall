// 실제 백엔드 통합 시험(e2e-real)에서 찾아 고친 두 문제의 단위 시험.
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { speechGuardMs, useStepAudio } from "../../src/worker/hooks/useStepAudio";
import { preloadPictures, preloadedUrls } from "../../src/worker/preload";

const speak = window.speechSynthesis.speak as ReturnType<typeof vi.fn>;
const step = { id: "s1", sentence: "컵을 씻어요", tts_audio_url: null };

describe("브라우저 음성이 끝 신호를 주지 않을 때", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    speak.mockReset();
  });
  afterEach(() => vi.useRealTimers());

  it("넉넉한 시간이 지나면 [멈춤]을 푼다", () => {
    const { result } = renderHook(() => useStepAudio(step, { autoplay: true, rate: 0.9 }));
    expect(speak).toHaveBeenCalledTimes(1);
    expect(result.current.playing).toBe(true);
    act(() => vi.advanceTimersByTime(speechGuardMs(step.sentence, 0.9) + 10));
    expect(result.current.playing).toBe(false);
  });

  it("자동 읽기를 브라우저가 막으면 '눌러서 들어요' 상태가 된다", () => {
    const { result } = renderHook(() => useStepAudio(step, { autoplay: true, rate: 0.9 }));
    const u = speak.mock.calls[0][0] as { onerror: (e: unknown) => void };
    act(() => u.onerror({ error: "not-allowed" }));
    expect(result.current.playing).toBe(false);
    expect(result.current.blocked).toBe(true);
  });

  it("시간은 글자 수와 속도를 따른다", () => {
    expect(speechGuardMs("가나다", 1)).toBe(4_200);
    expect(speechGuardMs("가나다", 0.8)).toBeGreaterThan(speechGuardMs("가나다", 1));
  });
});

describe("그림 미리 받기", () => {
  it("주소마다 한 번만 받고, 그림 없는 단계는 건너뛴다", () => {
    const before = preloadedUrls().length;
    preloadPictures([{ symbol_url: "http://x/a.webp" }, { symbol_url: null }, { symbol_url: "http://x/a.webp" }]);
    preloadPictures([{ symbol_url: "http://x/b.webp" }]);
    expect(preloadedUrls().slice(before)).toEqual(["http://x/a.webp", "http://x/b.webp"]);
  });
});
