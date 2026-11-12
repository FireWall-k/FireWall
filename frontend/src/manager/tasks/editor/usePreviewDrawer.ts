// 편집기 미리보기 서랍을 열고 닫는 상태(PreviewDrawer.tsx와 머리의 [미리보기] 토글이 함께 씀).
import { useCallback, useState } from "react";

export function usePreviewDrawer() {
  const [open, setOpen] = useState(false);
  const toggle = useCallback(() => setOpen((v) => !v), []);
  const close = useCallback(() => setOpen(false), []);
  return { open, setOpen, toggle, close };
}
