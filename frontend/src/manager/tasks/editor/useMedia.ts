// 화면 폭 조건(편집기 390 배치용). matchMedia가 없는 곳(jsdom 시험)은 넓은 화면으로 본다.
import { useSyncExternalStore } from "react";

export function useMedia(query: string, fallback = true): boolean {
  return useSyncExternalStore(
    (cb) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => {};
      const mq = window.matchMedia(query);
      mq.addEventListener?.("change", cb);
      return () => mq.removeEventListener?.("change", cb);
    },
    () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(query).matches : fallback),
    () => fallback,
  );
}

/** 목록과 상세를 나란히 두는 폭(명세 5.5 반응형: 820은 두 칸, 390은 목록 → 상세 전체 화면). tailwind md와 같다. */
export const TWO_PANE_QUERY = "(min-width: 768px)";
