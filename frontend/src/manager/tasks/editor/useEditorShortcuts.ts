// 편집기 단축키(2b-2, tasks §5, 명세 5.5 '단축키'·7.3).
// ↑↓·J/K 단계 옮겨 다니기, Enter 자세히 보기, 1~3 다른 그림 고르기, N 새 단계, E 문장 고치기, P 미리보기, ? 안내.
// 글을 쓰는 칸(input·textarea·select·contenteditable) 안, 모달(Dialog·Sheet)이 열린 동안, 한글 조합 중,
// Ctrl·Alt·⌘를 함께 누른 경우, 다른 부품이 이미 처리한 키(defaultPrevented)는 건드리지 않는다.
// 한글 자판에서도 되도록 글자 키는 e.code(KeyJ 등)로 본다.
import { useEffect, useRef } from "react";
import { useAnyModalOpen } from "../../../components/ui/modalLayer";

export type ShortcutAction =
  | { type: "move"; dir: -1 | 1 }
  | { type: "open" }
  | { type: "pick"; n: 0 | 1 | 2 }
  | { type: "new" }
  | { type: "edit" }
  | { type: "preview" }
  | { type: "help" };

export interface KeyLike {
  key: string;
  code?: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
  isComposing?: boolean;
  defaultPrevented?: boolean;
  target?: EventTarget | null;
}

const TYPING_SELECTOR = "input, textarea, select, [contenteditable=''], [contenteditable='true'], [role='textbox'], [role='combobox']";
/** Enter를 스스로 쓰는 요소 — 여기서는 Enter 단축키를 쓰지 않는다. */
const ACTIVATABLE_SELECTOR =
  "button, a[href], summary, [role='button'], [role='link'], [role='menuitem'], [role='tab'], [role='option'], [role='switch'], [role='checkbox']";

function asElement(t: EventTarget | null | undefined): Element | null {
  return t && typeof (t as Element).closest === "function" ? (t as Element) : null;
}

/** 글을 쓰는 곳인지(입력칸·contenteditable). */
export function isTypingTarget(t: EventTarget | null | undefined): boolean {
  const el = asElement(t);
  if (!el) return false;
  if ((el as HTMLElement).isContentEditable) return true;
  return !!el.closest(TYPING_SELECTOR);
}

/** 화면에 모달 판이 있는지(Dialog·Sheet). 훅의 카운터를 놓쳐도 DOM으로 한 번 더 본다. */
export function hasOpenModal(doc: Document | undefined = typeof document === "undefined" ? undefined : document): boolean {
  return !!doc?.querySelector("[aria-modal='true'], [role='dialog'][open], [role='alertdialog']");
}

/** 키 하나를 단축키 동작으로(꺼지는 조건은 보지 않음). */
export function keyToAction(e: KeyLike): ShortcutAction | null {
  if (e.ctrlKey || e.metaKey || e.altKey) return null;
  const code = e.code ?? "";
  const key = e.key;
  if (key === "?" || (code === "Slash" && e.shiftKey)) return { type: "help" };
  if (key === "ArrowUp") return { type: "move", dir: -1 };
  if (key === "ArrowDown") return { type: "move", dir: 1 };
  if (key === "Enter" && !e.shiftKey) return { type: "open" };
  if (e.shiftKey) return null;
  const letter = code.startsWith("Key") ? code.slice(3).toLowerCase() : key.length === 1 ? key.toLowerCase() : "";
  switch (letter) {
    case "k":
      return { type: "move", dir: -1 };
    case "j":
      return { type: "move", dir: 1 };
    case "n":
      return { type: "new" };
    case "e":
      return { type: "edit" };
    case "p":
      return { type: "preview" };
  }
  const digit = code.startsWith("Digit") || code.startsWith("Numpad") ? code.replace(/^(Digit|Numpad)/, "") : key;
  if (digit === "1" || digit === "2" || digit === "3") return { type: "pick", n: (Number(digit) - 1) as 0 | 1 | 2 };
  return null;
}

/** 이 키를 단축키로 받으면 안 되는지. */
export function shortcutsBlocked(e: KeyLike, modalOpen: boolean): boolean {
  if (modalOpen) return true;
  if (e.isComposing || e.key === "Process") return true;
  if (e.defaultPrevented) return true;
  if (isTypingTarget(e.target)) return true;
  if (e.key === "Enter" && asElement(e.target)?.closest(ACTIVATABLE_SELECTOR)) return true;
  return false;
}

/** 키를 받아 처리할 동작을 돌려준다(꺼지는 조건 포함). */
export function resolveShortcut(e: KeyLike, modalOpen: boolean): ShortcutAction | null {
  const action = keyToAction(e);
  if (!action) return null;
  return shortcutsBlocked(e, modalOpen) ? null : action;
}

export interface UseEditorShortcutsOptions {
  enabled: boolean;
  /** 처리했으면 true(기본 동작을 막는다). */
  onAction: (a: ShortcutAction) => boolean | void;
}

export function useEditorShortcuts({ enabled, onAction }: UseEditorShortcutsOptions) {
  const modalOpen = useAnyModalOpen();
  const latest = useRef(onAction);
  useEffect(() => {
    latest.current = onAction;
  });
  useEffect(() => {
    if (!enabled || modalOpen) return;
    function onKey(e: KeyboardEvent) {
      const a = resolveShortcut(e, hasOpenModal());
      if (!a) return;
      if (latest.current(a) !== false) e.preventDefault();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, modalOpen]);
}
