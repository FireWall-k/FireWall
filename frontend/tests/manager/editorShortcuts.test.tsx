// 편집기 단축키(2b-2): 키 → 동작, 꺼지는 조건(입력칸·contenteditable·모달·조합 중·보조키), 끌기 놓을 자리.
import { describe, expect, it, vi, afterEach } from "vitest";
import { render, renderHook, cleanup, fireEvent } from "@testing-library/react";
import { Dialog } from "../../src/components/ui";
import {
  hasOpenModal, isTypingTarget, keyToAction, resolveShortcut, shortcutsBlocked, useEditorShortcuts,
} from "../../src/manager/tasks/editor/useEditorShortcuts";
import { dropIndex } from "../../src/manager/tasks/editor/usePointerReorder";

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("keyToAction", () => {
  it.each([
    [{ key: "ArrowUp" }, { type: "move", dir: -1 }],
    [{ key: "ArrowDown" }, { type: "move", dir: 1 }],
    [{ key: "k", code: "KeyK" }, { type: "move", dir: -1 }],
    [{ key: "j", code: "KeyJ" }, { type: "move", dir: 1 }],
    [{ key: "ㅓ", code: "KeyJ" }, { type: "move", dir: 1 }], // 한글 자판
    [{ key: "Enter" }, { type: "open" }],
    [{ key: "1", code: "Digit1" }, { type: "pick", n: 0 }],
    [{ key: "3", code: "Numpad3" }, { type: "pick", n: 2 }],
    [{ key: "n", code: "KeyN" }, { type: "new" }],
    [{ key: "E", code: "KeyE" }, { type: "edit" }],
    [{ key: "p", code: "KeyP" }, { type: "preview" }],
    [{ key: "?", code: "Slash", shiftKey: true }, { type: "help" }],
  ])("%o → %o", (e, want) => {
    expect(keyToAction(e)).toEqual(want);
  });

  it("다른 키·보조키는 무시", () => {
    expect(keyToAction({ key: "4", code: "Digit4" })).toBeNull();
    expect(keyToAction({ key: "x", code: "KeyX" })).toBeNull();
    expect(keyToAction({ key: "j", code: "KeyJ", ctrlKey: true })).toBeNull();
    expect(keyToAction({ key: "p", code: "KeyP", metaKey: true })).toBeNull();
    expect(keyToAction({ key: "1", code: "Digit1", altKey: true })).toBeNull();
    expect(keyToAction({ key: "N", code: "KeyN", shiftKey: true })).toBeNull();
  });
});

describe("꺼지는 조건", () => {
  function el(html: string) {
    document.body.innerHTML = html;
    return document.body.firstElementChild as HTMLElement;
  }

  it("입력칸·textarea·select·contenteditable 안에서는 꺼짐", () => {
    for (const html of ["<input />", "<textarea></textarea>", "<select></select>", "<div contenteditable='true'><b>x</b></div>"]) {
      const node = el(html);
      const target = node.firstElementChild ?? node;
      expect(isTypingTarget(target)).toBe(true);
      expect(resolveShortcut({ key: "j", code: "KeyJ", target }, false)).toBeNull();
    }
    expect(isTypingTarget(el("<div><span>x</span></div>"))).toBe(false);
  });

  it("모달이 열려 있으면 꺼짐", () => {
    expect(shortcutsBlocked({ key: "j", target: document.body }, true)).toBe(true);
    expect(resolveShortcut({ key: "j", code: "KeyJ", target: document.body }, false)).toEqual({ type: "move", dir: 1 });
  });

  it("조합 중·이미 처리한 키는 꺼짐", () => {
    expect(shortcutsBlocked({ key: "j", isComposing: true, target: document.body }, false)).toBe(true);
    expect(shortcutsBlocked({ key: "Process", target: document.body }, false)).toBe(true);
    expect(shortcutsBlocked({ key: "ArrowUp", defaultPrevented: true, target: document.body }, false)).toBe(true);
  });

  it("단추 위의 Enter는 단추에게 맡김(J는 됨)", () => {
    const b = el("<button>x</button>");
    expect(resolveShortcut({ key: "Enter", target: b }, false)).toBeNull();
    expect(resolveShortcut({ key: "j", code: "KeyJ", target: b }, false)).toEqual({ type: "move", dir: 1 });
  });

  it("DOM에 aria-modal 판이 있으면 hasOpenModal", () => {
    expect(hasOpenModal()).toBe(false);
    el("<div role='dialog' aria-modal='true'></div>");
    expect(hasOpenModal()).toBe(true);
  });
});

describe("useEditorShortcuts", () => {
  it("창 키를 받아 동작을 부르고, 입력칸·Dialog가 열린 동안·enabled=false면 부르지 않음", () => {
    const onAction = vi.fn();
    const { rerender } = renderHook(({ enabled }) => useEditorShortcuts({ enabled, onAction }), { initialProps: { enabled: true } });
    fireEvent.keyDown(document.body, { key: "j", code: "KeyJ" });
    expect(onAction).toHaveBeenLastCalledWith({ type: "move", dir: 1 });

    const input = document.createElement("input");
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: "k", code: "KeyK" });
    expect(onAction).toHaveBeenCalledTimes(1);

    const dlg = render(<Dialog open onClose={() => {}} title="창" />);
    fireEvent.keyDown(document.body, { key: "?", code: "Slash", shiftKey: true });
    expect(onAction).toHaveBeenCalledTimes(1);
    dlg.unmount();

    fireEvent.keyDown(document.body, { key: "?", code: "Slash", shiftKey: true });
    expect(onAction).toHaveBeenLastCalledWith({ type: "help" });

    rerender({ enabled: false });
    fireEvent.keyDown(document.body, { key: "n", code: "KeyN" });
    expect(onAction).toHaveBeenCalledTimes(2);
  });

  it("처리하면 기본 동작을 막음", () => {
    renderHook(() => useEditorShortcuts({ enabled: true, onAction: () => true }));
    const ev = new KeyboardEvent("keydown", { key: "n", code: "KeyN", bubbles: true, cancelable: true });
    document.body.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(true);
  });
});

describe("dropIndex", () => {
  const mids = [50, 150, 250, 350];
  it("끄는 행을 뺀 가운데 선 기준", () => {
    expect(dropIndex(mids, 0, 10)).toBe(0);
    expect(dropIndex(mids, 0, 200)).toBe(1);
    expect(dropIndex(mids, 0, 400)).toBe(3);
    expect(dropIndex(mids, 3, 10)).toBe(0);
    expect(dropIndex(mids, 2, 160)).toBe(2);
  });
});
