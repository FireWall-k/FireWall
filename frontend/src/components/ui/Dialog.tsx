// 확인 창(명세 5.0, 7.3). window.confirm 대신 쓴다.
// - 일반: 제목 + 설명 + [취소] [확인]
// - 위험(tone="danger"): 지워지는 것 목록(items)을 보이고, confirmName이 있으면 그 이름을 똑같이 적어야
//   [지우기]가 눌린다(근로자 삭제). 처음 초점은 [취소] — Enter를 잘못 눌러 지우지 않게.
// 초점은 창 안에서만 돌고, Esc나 바깥을 누르면 닫히고, 닫히면 연 버튼으로 돌아간다.
import { useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cn } from "../../cn";
import { ui as copy } from "../../manager/copy";
import Button from "./Button";
import IconButton from "./IconButton";
import { Field, Input } from "./Field";
import { useFocusTrap } from "./focus";

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  tone?: "default" | "danger";
  /** 위험 창: 함께 지워지는 것 목록. */
  items?: ReactNode[];
  /** 위험 창: 이 글자를 똑같이 적어야 확인 버튼이 눌린다. */
  confirmName?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** 없으면 [확인] 없이 [닫기]만 있는 알림 창. */
  onConfirm?: () => void;
  /** 확인을 처리하는 중(버튼 불러오는 중, 닫기 막음). */
  busy?: boolean;
  children?: ReactNode;
}

export default function Dialog(props: DialogProps) {
  if (!props.open) return null;
  return createPortal(<DialogPanel {...props} />, document.body);
}

function DialogPanel({
  onClose,
  title,
  description,
  tone = "default",
  items,
  confirmName,
  confirmLabel,
  cancelLabel,
  onConfirm,
  busy = false,
  children,
}: DialogProps) {
  const ref = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descId = useId();
  const [typed, setTyped] = useState("");
  const danger = tone === "danger";
  const close = () => {
    if (!busy) onClose();
  };
  useFocusTrap(ref, true, { onEscape: close, initialFocus: danger ? cancelRef : undefined });

  const nameOk = !confirmName || typed.trim() === confirmName.trim();

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center">
      <div aria-hidden="true" className="absolute inset-0 bg-ink-900/40" onClick={close} />
      <div
        ref={ref}
        role={danger ? "alertdialog" : "dialog"}
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        className="relative flex max-h-[calc(100vh-2rem)] w-full max-w-md animate-pop-in flex-col overflow-y-auto rounded-overlay bg-white p-6 shadow-overlay"
      >
        <div className="flex items-start gap-3">
          <h2 id={titleId} className={cn("min-w-0 flex-1 text-ui-lg font-bold", danger ? "text-danger-700" : "text-ink-900")}>
            {title}
          </h2>
          <IconButton aria-label={copy.close} icon={<X size={20} strokeWidth={2} aria-hidden="true" />} onClick={close} className="-mr-2 -mt-1" />
        </div>
        {description && (
          <p id={descId} className="mt-2 text-ui-base text-ink-700">
            {description}
          </p>
        )}
        {items && items.length > 0 && (
          <div className="mt-4 rounded-card border border-danger-700/20 bg-danger-50 p-3">
            <p className="text-ui-sm font-semibold text-danger-700">{copy.deletedItemsTitle}</p>
            <ul className="mt-1 list-disc pl-5 text-ui-base text-ink-900">
              {items.map((it, i) => (
                <li key={i}>{it}</li>
              ))}
            </ul>
          </div>
        )}
        {children && <div className="mt-4">{children}</div>}
        {confirmName && (
          <Field className="mt-4" label={copy.confirmNameLabel(confirmName)}>
            <Input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
          </Field>
        )}
        <div className="mt-6 flex flex-wrap justify-end gap-2">
          <Button ref={cancelRef} variant="secondary" onClick={close} disabled={busy}>
            {onConfirm ? (cancelLabel ?? copy.cancel) : copy.close}
          </Button>
          {onConfirm && (
            <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} disabled={!nameOk} loading={busy}>
              {confirmLabel ?? (danger ? copy.delete : copy.confirm)}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
