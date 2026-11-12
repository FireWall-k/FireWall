// 토스트(명세 5.0, 7.3, 8.2): 오른쪽 아래(휴대폰은 아래 탭바 위), role=status, 150ms로 나타남.
// 성공·안내는 5초 뒤 저절로 닫히고(마우스·초점이 올라가 있으면 기다림), 오류는 저절로 닫히지 않는다.
// 휴대폰에서 화면 아래에 고정 줄이 더 있으면(편집기) 그 화면이 --toast-bottom을 올려 토스트가 그 줄을 덮지 않게 한다.
// [실행 취소]가 있는 토스트는 누르면 되돌리고 닫힌다. 한 번에 3개까지 보인다.
// [닫기](X)로 닫을 때 초점이 토스트 안에 있었으면 다른 토스트의 단추 → 띄우기 직전 자리 → 본문(#main) 순으로
// 옮긴다(초점이 body로 사라지지 않게, WCAG 2.4.3). 모달(Dialog·Sheet)이 열려 있는 동안 토스트 층은 모달 아래(z-40)로
// 내려가고 inert가 된다 — 위험 창의 목록을 가리거나 창이 열린 채 [실행 취소]가 눌리지 않게.
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { CircleAlert, CircleCheck, Info, X } from "lucide-react";
import { cn } from "../../cn";
import { ui as copy } from "../../manager/copy";
import { useAnyModalOpen } from "./modalLayer";
import { TOAST_MS, ToastContext, type ToastApi, type ToastInput } from "./toastContext";

interface ToastEntry extends ToastInput {
  id: string;
  /** 띄우기 직전 초점이 있던 곳(닫은 뒤 초점을 돌려줄 후보). */
  returnTo: HTMLElement | null;
}

function canFocus(el: HTMLElement | null): el is HTMLElement {
  return !!el && el.isConnected && el !== document.body && !el.matches(":disabled") && !el.closest("[inert]");
}

const MAX_TOASTS = 3;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const seq = useRef(0);
  const layerRef = useRef<HTMLDivElement>(null);
  const modalOpen = useAnyModalOpen();

  const dismiss = useCallback((id: string) => setToasts((cur) => cur.filter((t) => t.id !== id)), []);
  const show = useCallback((t: ToastInput) => {
    const id = `t${++seq.current}`;
    const a = document.activeElement;
    const returnTo = a instanceof HTMLElement && a !== document.body && !layerRef.current?.contains(a) ? a : null;
    setToasts((cur) => [...cur, { ...t, id, returnTo }].slice(-MAX_TOASTS));
    return id;
  }, []);
  const api = useMemo<ToastApi>(() => ({ show, dismiss }), [show, dismiss]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        ref={layerRef}
        data-toast-layer=""
        inert={modalOpen}
        className={cn(
          "pointer-events-none fixed bottom-[var(--toast-bottom,5rem)] right-4 flex w-[calc(100%-2rem)] max-w-sm flex-col items-end gap-2 md:bottom-6 md:right-6",
          modalOpen ? "z-40" : "z-[60]",
        )}
      >
        {toasts.map((t) => (
          <ToastItem
            key={t.id}
            toast={t}
            onDismiss={() => dismiss(t.id)}
            onClose={(el) => {
              // 초점이 이 토스트 안에 있었으면, 지우기 전에 남는 곳으로 옮긴다.
              if (el.contains(document.activeElement)) {
                const other = Array.from(layerRef.current?.querySelectorAll<HTMLElement>("button") ?? []).find(
                  (b) => !el.contains(b),
                );
                const target = other ?? (canFocus(t.returnTo) ? t.returnTo : document.getElementById("main"));
                target?.focus();
              }
              dismiss(t.id);
            }}
          />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({
  toast,
  onDismiss,
  onClose,
}: {
  toast: ToastEntry;
  onDismiss: () => void;
  /** [닫기](X): 초점을 옮긴 뒤 닫는다. */
  onClose: (el: HTMLElement) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
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
      ref={ref}
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
        onClick={() => (ref.current ? onClose(ref.current) : onDismiss())}
        className="-m-1 inline-flex size-8 shrink-0 items-center justify-center rounded-control text-ink-500 hover:bg-paper-100 hover:text-ink-900 coarse:size-control-coarse"
      >
        <X size={16} strokeWidth={2} aria-hidden="true" />
      </button>
    </div>
  );
}
