// Dialog·Sheet가 함께 쓰는 초점 규칙(명세 8.2): 열리면 안으로 초점을 옮기고, Tab은 안에서만 돌고,
// Esc로 닫히고, 닫히면 열기 전 자리(누른 버튼)로 초점을 돌려 놓는다.
import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type=hidden])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

/** Tab으로 갈 수 있는 요소만(tabindex=-1인 비활성 탭 같은 것은 뺀다 — 마지막 요소로 잘못 세면 초점이 판 밖으로 샌다). */
export function focusableIn(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) =>
      el.tabIndex >= 0 &&
      !el.closest("[inert]") &&
      !el.closest("[aria-hidden='true']"),
  );
}

// 열린 판(Dialog·Sheet)의 쌓임. Esc·초점 되찾기는 맨 위 판 하나만 한다(판 안에 판이 열려도 하나씩 닫힌다).
const trapStack: HTMLElement[] = [];

interface TrapOptions {
  onEscape?: () => void;
  /** 처음 초점을 줄 요소. 없으면 [data-autofocus] → 첫 초점 가능 요소 → 판 자체. */
  initialFocus?: RefObject<HTMLElement | null>;
}

export function useFocusTrap(ref: RefObject<HTMLElement | null>, active: boolean, opts: TrapOptions = {}) {
  // 매 렌더 바뀌는 콜백을 effect 의존성에 넣으면 열린 채로 초점이 처음 자리로 튄다 — ref로 최신 값만 읽는다.
  const optsRef = useRef(opts);
  useEffect(() => {
    optsRef.current = opts;
  });

  useEffect(() => {
    if (!active) return;
    const root = ref.current;
    if (!root) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const first =
      optsRef.current.initialFocus?.current ??
      root.querySelector<HTMLElement>("[data-autofocus]") ??
      focusableIn(root)[0] ??
      root;
    // 먼저 쌓아야 아래 판의 focusin 되찾기가 새 판으로 가는 초점을 빼앗지 않는다.
    trapStack.push(root);
    first.focus();

    function onKeyDown(e: KeyboardEvent) {
      if (!root) return;
      if (e.key === "Escape") {
        if (optsRef.current.onEscape) {
          e.stopPropagation();
          optsRef.current.onEscape();
        }
        return;
      }
      if (e.key !== "Tab") return;
      const items = focusableIn(root);
      if (items.length === 0) {
        e.preventDefault();
        root.focus();
        return;
      }
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      const cur = document.activeElement;
      if (e.shiftKey && (cur === firstEl || !root.contains(cur))) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && (cur === lastEl || !root.contains(cur))) {
        e.preventDefault();
        firstEl.focus();
      }
    }
    root.addEventListener("keydown", onKeyDown);
    const isTop = () => trapStack[trapStack.length - 1] === root;
    // 초점이 어떤 이유로든 판 밖에 있어도 Esc로 닫힌다(판 안의 처리기가 이미 했으면 stopPropagation으로 여기 안 옴).
    function onDocKeyDown(e: KeyboardEvent) {
      if (!root || !isTop() || e.key !== "Escape" || root.contains(e.target as Node)) return;
      if (optsRef.current.onEscape) {
        e.stopPropagation();
        optsRef.current.onEscape();
      }
    }
    // 초점이 판 밖으로 나가면 판 안으로 되찾는다(명세 8.2 '초점을 가두고').
    function onFocusIn(e: FocusEvent) {
      if (!root || !isTop()) return;
      const t = e.target as Node | null;
      if (t && !root.contains(t)) (focusableIn(root)[0] ?? root).focus();
    }
    document.addEventListener("keydown", onDocKeyDown);
    document.addEventListener("focusin", onFocusIn);
    return () => {
      root.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("keydown", onDocKeyDown);
      document.removeEventListener("focusin", onFocusIn);
      const i = trapStack.lastIndexOf(root);
      if (i >= 0) trapStack.splice(i, 1);
      // 닫힌 뒤 열었던 버튼으로 돌아간다(그 버튼이 아직 화면에 있을 때만).
      if (opener && opener.isConnected) opener.focus();
    };
  }, [active, ref]);
}
