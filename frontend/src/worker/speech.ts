// 근로자 화면 소리·진동 도우미(명세 4.11). 서버 음성 파일 재생(useStepAudio)은 WORKER 쪽 훅이 맡고,
// 여기는 브라우저 음성(파일이 없을 때·상태 화면 제목 읽기)과 진동만 둔다.
// 지원하지 않는 기기(iOS Safari 진동, 음성 없는 브라우저)에서는 조용히 아무것도 하지 않는다 —
// 소리·진동으로만 전하는 정보는 두지 않으므로 빠져도 화면은 그대로 쓸 수 있다.

/** 브라우저 음성으로 한국어 문장을 읽는다. rate는 근로자 설정 tts_rate(0.8 / 0.9 / 1.0, 기본 0.9). */
export function speakText(text: string, opts: { rate?: number } = {}): void {
  try {
    if (typeof window === "undefined" || !("speechSynthesis" in window) || !window.speechSynthesis) return;
    if (typeof SpeechSynthesisUtterance === "undefined") return;
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "ko-KR";
    u.rate = opts.rate ?? 0.9;
    // 앞에 읽던 문장을 끊고 새 문장을 읽는다(겹쳐 읽으면 알아듣기 어렵다).
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  } catch {
    /* 음성을 못 쓰는 기기: 무시 */
  }
}

/** 읽던 소리를 멈춘다(화면이 바뀔 때). */
export function stopSpeaking(): void {
  try {
    window.speechSynthesis?.cancel();
  } catch {
    /* 무시 */
  }
}

/** 짧게 진동한다. 키패드 10ms, 단계 완료 30ms. enabled = 근로자 설정 vibration(기본 끔). */
export function vibrate(ms: number, enabled: boolean): void {
  if (!enabled) return;
  try {
    if (typeof navigator !== "undefined" && typeof navigator.vibrate === "function") navigator.vibrate(ms);
  } catch {
    /* 무시 */
  }
}
