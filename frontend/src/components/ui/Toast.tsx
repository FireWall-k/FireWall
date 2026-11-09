// 토스트(명세 5.0, 7.3, 8.2): 오른쪽 아래(휴대폰은 아래 탭바 위), role=status, 150ms로 나타남.
// 성공·안내는 5초 뒤 저절로 닫히고(마우스·초점이 올라가 있으면 기다림), 오류는 저절로 닫히지 않는다.
// [실행 취소]가 있는 토스트는 누르면 되돌리고 닫힌다. 한 번에 3개까지 보인다.
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { CircleAlert, CircleCheck, Info, X } from "lucide-react";
import { cn } from "../../cn";
import { ui as copy } from "../../manager/copy";
import { TOAST_MS, ToastContext, type ToastApi, type ToastInput } from "./toastContext";

interface ToastEntry extends ToastInput {
  id: string;
}

const MAX_TOASTS = 3;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const seq = useRef(0);

  const dismiss = useCallback((id: string) => setToasts((cur) => cur.filter((t) => t.id !== id)), []);
  const show = useCallback((t: ToastInput) => {
    const id = `t${++seq.current}`;
    setToasts((cur) => [...cur, { ...t, id }].slice(-MAX_TOASTS));
    return id;
  }, []);
  const api = useMemo<ToastApi>(() => ({ show, dismiss }), [show, dismiss]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        className="pointer-events-none fixed bottom-20 right-4 z-[60] flex w-[calc(100%-2rem)] max-w-sm flex-col items-end gap-2 md:bottom-6 md:right-6"
      >
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDismiss }: { toast: ToastEntry; onDismiss: () => void }) {
  const tone = toast.tone ?? "success";
  const isError = tone === "error";
  const [paused, setPaused] = useState(false);
  const dismissRef = useRef(onDismiss);
  useEffect(() => {
    dismissRef.current = onDismiss;
  });

  useEffect(() => {
    if (isError || paused) return;
    const timer = window.setTimeout(() => dismissRef.current(), toast.duration ?? TOAST_MS);
    return () => window.clearTimeout(timer);
  }, [isError, paused, toast.duration]);

  const Icon = isError ? CircleAlert : tone === "info" ? Info : CircleCheck;
  return (
    <div
      role="status"
      aria-live={isError ? "assertive" : "polite"}
      data-tone={tone}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
      className={cn(
        "pointer-events-auto flex w-full animate-pop-in items-start gap-2 rounded-card border bg-white p-3 shadow-overlay transition-opacity duration-toast",
        isError ? "border-danger-700/30" : "border-paper-200",
      )}
    >
      <Icon
        size={20}
        strokeWidth={2}
        aria-hidden="true"
        className={cn("mt-0.5 shrink-0", isError ? "text-danger-700" : tone === "info" ? "text-info-700" : "text-ok-700")}
      />
      <div className="min-w-0 flex-1">
        <p className={cn("text-ui-base", isError ? "font-semibold text-danger-700" : "text-ink-900")}>{toast.message}</p>
        {(toast.onUndo || toast.action) && (
          <div className="mt-1 flex flex-wrap gap-3">
            {toast.onUndo && (
              <button
                type="button"
                onClick={() => {
                  toast.onUndo?.();
                  onDismiss();
                }}
                className="min-h-8 whitespace-nowrap text-ui-base font-semibold text-info-700 underline underline-offset-2 coarse:min-h-control-coarse"
              >
                {copy.undo}
              </button>
            )}
            {toast.action && (
              <button
                type="button"
                onClick={() => {
                  toast.action?.onClick();
                  onDismiss();
                }}
                className="min-h-8 whitespace-nowrap text-ui-base font-semibold text-info-700 underline underline-offset-2 coarse:min-h-control-coarse"
              >
                {toast.action.label}
              </button>
            )}
          </div>
        )}
      </div>
      <button
        type="button"
        aria-label={copy.close}
        onClick={onDismiss}
        className="-m-1 inline-flex size-8 shrink-0 items-center justify-center rounded-control text-ink-500 hover:bg-paper-100 hover:text-ink-900 coarse:size-control-coarse"
      >
        <X size={16} strokeWidth={2} aria-hidden="true" />
      </button>
    </div>
  );
}
