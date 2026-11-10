// 지금 열린 모달(Dialog·Sheet) 수. 모달이 열려 있는 동안 토스트 층은 모달 아래로 내려가고 inert가 된다
// (390 폭에서 토스트가 위험 창의 '함께 지워지는 것' 목록을 가리거나, 창이 열린 채 [실행 취소]가 눌리지 않게, 명세 5.0).
import { useEffect, useSyncExternalStore } from "react";

let open = 0;
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

/** 모달 판이 화면에 있는 동안 부른다(마운트 = 열림). */
export function useModalOpen() {
  useEffect(() => {
    open += 1;
    emit();
    return () => {
      open -= 1;
      emit();
    };
  }, []);
}

/** 모달이 하나라도 열려 있는지. */
export function useAnyModalOpen(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => open > 0,
    () => false,
  );
}
