// 적던 내용이 있을 때 화면 안 링크(사이드바·이동 경로·[새 직무] 등)로 떠나려 하면 먼저 묻는다(tasks §4.3).
// 앱은 BrowserRouter라 react-router의 useBlocker(데이터 라우터 전용)를 쓸 수 없다 — 문서의 링크 누르기를 잡는다(capture).
// 새 탭·수정 키를 누른 클릭·다른 사이트 주소·지금 주소와 같은 링크는 건드리지 않는다.
// 링크가 아닌 곳에서 navigate()로 떠나는 메뉴(사용자 메뉴·'더보기'의 설정·로그아웃)는 guardLeave(go)로 감싼다 —
// 가드가 켜져 있으면 같은 대화상자를 띄우고, [나가기]를 누르면 그때 go를 부른다(1회차 검증).
// 브라우저 뒤로 가기·새로고침은 막지 않는다: 원문은 이 기기에 임시 저장되어 돌아오면 다시 채워진다.
import { useEffect, useRef, useState } from "react";

/** 떠날 곳: 링크 주소(to) 또는 메뉴가 하려던 일(go). */
export interface LeavePending {
  to?: string;
  go?: () => void;
}

let activeGuard: ((go: () => void) => boolean) | null = null;

/** 메뉴처럼 navigate()로 떠나는 곳에서 쓴다. 적던 내용이 있으면 묻고(go는 [나가기] 때), 없으면 바로 go. */
export function guardLeave(go: () => void) {
  if (activeGuard && activeGuard(go)) return;
  go();
}

export function useLeaveGuard(active: boolean) {
  const [pending, setPending] = useState<LeavePending | null>(null);
  const activeRef = useRef(active);
  useEffect(() => {
    activeRef.current = active;
  });

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (!activeRef.current || e.defaultPrevented || e.button !== 0) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!a || (a.target && a.target !== "_self") || a.hasAttribute("download")) return;
      const url = new URL(a.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      const to = url.pathname + url.search + url.hash;
      if (to === window.location.pathname + window.location.search + window.location.hash) return;
      e.preventDefault();
      e.stopPropagation();
      setPending({ to });
    }
    const guard = (go: () => void) => {
      if (!activeRef.current) return false;
      setPending({ go });
      return true;
    };
    activeGuard = guard;
    document.addEventListener("click", onClick, true);
    return () => {
      document.removeEventListener("click", onClick, true);
      if (activeGuard === guard) activeGuard = null;
    };
  }, []);

  return { pending, cancel: () => setPending(null), clear: () => setPending(null) };
}
