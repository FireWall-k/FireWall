// 편집기 미리보기 자리(명세 5.5 반응형, tasks §5). 이 파일은 자리(서랍·아래 시트)만 만든다 — 휴대폰 미리보기 내용은
// 미리보기 작업(PhonePreview)이 children으로 채운다.
// - 1280 이상(layout="side"): 목록 · 상세 오른쪽 세 번째 칸. 처음엔 접혀 있고 머리의 [미리보기] 토글로 연다.
// - 768~1279(layout="sheet"): 목록 · 상세 두 칸은 그대로, 미리보기는 화면 아래 시트로 연다.
// - 768 미만(layout="full"): 전체 화면.
// 닫혀 있어도 자리(data-testid="preview-drawer")는 늘 그려 두고 hidden으로 숨긴다 — 채우는 쪽이 자리를 찾을 수 있게.
import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { IconButton } from "../../../components/ui";
import { cn } from "../../../cn";
import { previewDrawer as copy } from "../../copy";

export type PreviewLayout = "side" | "sheet" | "full";

export interface PreviewDrawerProps {
  open: boolean;
  layout: PreviewLayout;
  onClose: () => void;
  /** 열릴 때마다 한 번 부른다(미리보기가 내용을 새로 불러오는 곳). */
  onOpen?: () => void;
  children?: ReactNode;
}

export default function PreviewDrawer({ open, layout, onClose, onOpen, children }: PreviewDrawerProps) {
  const onOpenRef = useRef(onOpen);
  useEffect(() => {
    onOpenRef.current = onOpen;
  });
  useEffect(() => {
    if (open) onOpenRef.current?.();
  }, [open]);
  useEffect(() => {
    if (!open || layout === "side") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, layout, onClose]);

  return (
    <aside
      id="editor-preview-drawer"
      data-testid="preview-drawer"
      data-layout={layout}
      data-state={open ? "open" : "closed"}
      aria-label={copy.label}
      hidden={!open}
      className={cn(
        "min-w-0 flex-col gap-3 border-paper-200 bg-white p-4",
        open && "flex",
        layout === "side" && "sticky top-4 max-h-[calc(100vh-2rem)] overflow-y-auto rounded-card border shadow-ui-sm",
        layout === "sheet" && "fixed inset-x-0 bottom-0 z-40 max-h-[70vh] overflow-y-auto rounded-t-card border-t shadow-ui-md md:left-rail",
        layout === "full" && "fixed inset-0 z-40 overflow-y-auto",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-display text-ui-md font-bold text-ink-900">{copy.title}</h2>
        <IconButton aria-label={copy.close} icon={<X size={16} strokeWidth={2} aria-hidden="true" />} onClick={onClose} />
      </div>
      <div data-testid="preview-drawer-body" className="flex min-w-0 flex-1 flex-col">
        {children}
      </div>
    </aside>
  );
}
