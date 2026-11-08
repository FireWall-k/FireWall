// 완료 체크음(150ms, 명세 4.11)과 소리 잠금 풀기. 실패음·경고음은 쓰지 않는다(놀라지 않게).
// 브라우저는 사용자가 한 번 눌러야 소리를 내게 해 준다 — [시작하기] 누름에서 unlockAudio()를 불러 푼다.
// 지원하지 않는 기기에서는 조용히 넘어간다(소리로만 전하는 정보는 없다).

type AudioCtor = typeof AudioContext;

let ctx: AudioContext | null = null;

function context(): AudioContext | null {
  try {
    if (ctx) return ctx;
    const w = window as unknown as { AudioContext?: AudioCtor; webkitAudioContext?: AudioCtor };
    const Ctor: AudioCtor | undefined = w.AudioContext ?? w.webkitAudioContext;
    if (!Ctor) return null;
    ctx = new Ctor();
    return ctx;
  } catch {
    return null;
  }
}

// 0.1초 무음 WAV. 사용자 누름 안에서 한 번 재생해 두면 이후 자동 재생이 허용되는 브라우저가 많다.
const SILENT_WAV =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";

/** [시작하기]처럼 사용자가 누른 순간에 부른다. */
export function unlockAudio(): void {
  try {
    void context()?.resume();
  } catch {
    /* 무시 */
  }
  try {
    const a = new Audio(SILENT_WAV);
    a.volume = 0;
    void a.play()?.catch(() => {});
  } catch {
    /* 무시 */
  }
  try {
    window.speechSynthesis?.resume?.();
  } catch {
    /* 무시 */
  }
}

/** '잘했어요' 체크음: 짧고 부드러운 두 음(150ms). */
export function playCheckSound(enabled: boolean): void {
  if (!enabled) return;
  const c = context();
  if (!c) return;
  try {
    const now = c.currentTime;
    const gain = c.createGain();
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.15, now + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.15);
    gain.connect(c.destination);
    const osc = c.createOscillator();
    osc.type = "sine";
    osc.frequency.setValueAtTime(660, now);
    osc.frequency.setValueAtTime(880, now + 0.07);
    osc.connect(gain);
    osc.start(now);
    osc.stop(now + 0.16);
  } catch {
    /* 무시 */
  }
}
