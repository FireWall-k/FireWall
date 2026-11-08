// 단계 그림 미리 받기(통합 시험에서 찾은 문제). 그림은 단계에 들어갈 때 처음 받아서, 일하는 중에 인터넷이
// 끊기면 아직 안 본 단계가 '그림을 못 불러왔어요'가 됐다 — 기록은 대기열이 지켜 주는데 그림이 없어 일을
// 따라 할 수 없다. 오늘 할 일을 받으면 끝나지 않은 일의 그림을 모두 미리 받아 둔다.
// 같은 문서 안에서 한 번 받은 그림은 브라우저가 주소별로 기억해 다시 쓴다(HTML '쓸 수 있는 그림 목록').
// Image 객체를 들고 있어야 메모리에서 밀려나지 않으므로 주소별로 붙잡아 둔다(오래된 것부터 버림).
import type { Step } from "../api";

const MAX_KEPT = 200;
const kept = new Map<string, HTMLImageElement>();

export function preloadPictures(steps: Pick<Step, "symbol_url">[]): void {
  if (typeof Image === "undefined") return;
  for (const s of steps) {
    const url = s.symbol_url;
    if (!url || kept.has(url)) continue;
    const img = new Image();
    img.decoding = "async";
    img.src = url;
    kept.set(url, img);
    if (kept.size > MAX_KEPT) kept.delete(kept.keys().next().value as string);
  }
}

/** 테스트용: 붙잡아 둔 주소 목록. */
export function preloadedUrls(): string[] {
  return [...kept.keys()];
}
