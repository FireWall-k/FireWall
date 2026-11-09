// 오른쪽 서랍(명세 5.6, 7.3): 폭 480(좁은 화면은 꽉 채움), 모서리 14, 200ms로 나타남, 초점 가두기.
// 보내기 시트(2b-1)와 근로자 타임라인 서랍(2c)이 쓴다.
import { useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { ui as copy } from "../../manager/copy";
import IconButton from "./IconButton";
import { useFocusTrap } from "./focus";

export interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  /** 아래에 붙는 버튼 줄. */
  footer?: ReactNode;
  children: ReactNode;
}

export default function Sheet(props: SheetProps) {
  if (!props.open) return null;
  return createPortal(<SheetPanel {...props} />, document.body);
}

function SheetPanel({ onClose, title, description, footer, children }: SheetProps) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descId = useId();
  useFocusTrap(ref, true, { onEscape: onClose });
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div aria-hidden="true" className="absolute inset-0 bg-ink-900/30" onClick={onClose} />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        data-testid="sheet"
        className="relative flex h-full w-full max-w-sheet animate-sheet-in flex-col bg-white shadow-overlay sm:rounded-l-overlay"
      >
        <div className="flex items-start gap-3 border-b border-paper-200 px-6 py-4">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-ui-lg font-bold text-ink-900">
              {title}
            </h2>
            {description && (
              <p id={descId} className="mt-1 text-ui-sm text-ink-500">
                {description}
              </p>
            )}
          </div>
          <IconButton aria-label={copy.close} icon={<X size={20} strokeWidth={2} aria-hidden="true" />} onClick={onClose} className="-mr-2" />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-paper-200 px-6 py-4">{footer}</div>}
      </div>
    </div>
  );
}
