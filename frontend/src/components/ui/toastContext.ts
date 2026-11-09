// 토스트를 띄우는 훅(명세 5.0: 피드백은 토스트 하나로 통일). 부품은 Toast.tsx의 ToastProvider.
import { createContext, useContext, type ReactNode } from "react";

export type ToastTone = "success" | "error" | "info";

export interface ToastInput {
  tone?: ToastTone;
  message: ReactNode;
  /** [실행 취소]. 누르면 이 함수를 부르고 토스트를 닫는다. */
  onUndo?: () => void;
  /** 그 밖의 행동 하나('현황 보기' 등). */
  action?: { label: string; onClick: () => void };
  /** 저절로 닫히기까지(ms). 오류는 이 값과 상관없이 저절로 닫히지 않는다. */
  duration?: number;
}

export interface ToastApi {
  show: (t: ToastInput) => string;
  dismiss: (id: string) => void;
}

/** 성공·안내 토스트가 저절로 닫히는 시간. 오류는 닫지 않는다(명세 5.0, 8.2). */
export const TOAST_MS = 5_000;

export const ToastContext = createContext<ToastApi | null>(null);

const NOOP: ToastApi = { show: () => "", dismiss: () => {} };

/** ToastProvider 밖(옛 화면 단독 시험 등)에서는 아무것도 하지 않는다. */
export function useToast(): ToastApi {
  return useContext(ToastContext) ?? NOOP;
}
