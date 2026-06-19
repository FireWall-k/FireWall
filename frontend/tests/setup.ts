import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// jsdom에 없는 브라우저 API 스텁(워커 화면 음성 재생 경로 안전화)
class FakeAudio {
  play() { return Promise.resolve(); }
  pause() {}
}
// @ts-expect-error - 테스트 환경 스텁
global.Audio = FakeAudio;
// @ts-expect-error - 테스트 환경 스텁
window.speechSynthesis = { speak: vi.fn(), cancel: vi.fn() };
// @ts-expect-error - 테스트 환경 스텁
global.SpeechSynthesisUtterance = class { lang = ""; rate = 1; constructor(public text: string) {} };
