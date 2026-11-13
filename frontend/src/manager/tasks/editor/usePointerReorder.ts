// 단계 목록 마우스·손가락 끌기(2b-2, 명세 5.5 '순서 바꾸기'). 키보드 손잡이는 StepList에 있다([↑][↓] 단추는 2026-11-13 사용자 요청으로 뺌).
// 손잡이를 누른 채 6px 넘게 움직이면 끌기가 시작된다. 놓을 자리는 누른 순간의 행 위치(가운데 선)로 정한다 —
// 끄는 동안 미리 바뀐 순서로 행이 움직여도 놓을 자리가 흔들리지 않게.
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

export interface PointerDrag {
  id: string;
  from: number;
  at: number;
}

const THRESHOLD = 6;

/** 끄는 단계(from)를 뺀 행들 중 가운데 선이 포인터보다 위에 있는 수 = 놓을 자리. */
export function dropIndex(mids: number[], from: number, y: number): number {
  let at = 0;
  mids.forEach((m, i) => {
    if (i !== from && m < y) at += 1;
  });
  return at;
}

export function usePointerReorder({
  ids,
  disabled,
  onMove,
  rowSelector = "[data-step-id]",
}: {
  ids: string[];
  disabled: boolean;
  onMove: (from: number, to: number) => void;
  rowSelector?: string;
}) {
  const [drag, setDrag] = useState<PointerDrag | null>(null);
  const onMoveRef = useRef(onMove);
  useEffect(() => {
    onMoveRef.current = onMove;
  });
  const stop = useRef<(() => void) | null>(null);
  useEffect(() => () => stop.current?.(), []);

  // 미리 바뀐 순서로 행이 DOM에서 옮겨지면 손잡이의 포인터 잡기(capture)가 풀린다 — 그래서 창에서 듣는다.
  function onPointerDown(e: ReactPointerEvent<HTMLElement>, id: string) {
    if (disabled || (e.pointerType === "mouse" && e.button !== 0)) return;
    const from = ids.indexOf(id);
    if (from < 0) return;
    const list = e.currentTarget.closest("ol, ul");
    const rows = list ? Array.from(list.querySelectorAll<HTMLElement>(rowSelector)) : [];
    const mids = rows.map((r) => {
      const b = r.getBoundingClientRect();
      return b.top + b.height / 2;
    });
    const pointerId = e.pointerId;
    const y0 = e.clientY;
    let current: PointerDrag | null = null;
    stop.current?.();

    const move = (ev: PointerEvent) => {
      if (ev.pointerId !== pointerId) return;
      if (!current && Math.abs(ev.clientY - y0) < THRESHOLD) return;
      ev.preventDefault();
      const at = dropIndex(mids, from, ev.clientY);
      if (!current || current.at !== at) {
        current = { id, from, at };
        setDrag(current);
      }
    };
    const end = (commit: boolean) => (ev: PointerEvent) => {
      if (ev.pointerId !== pointerId) return;
      const d = current;
      cleanup();
      setDrag(null);
      if (commit && d && d.at !== d.from) onMoveRef.current(d.from, d.at);
    };
    const up = end(true);
    const cancel = end(false);
    function cleanup() {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel);
      stop.current = null;
    }
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
    stop.current = cleanup;
  }

  return {
    drag,
    handleProps: (id: string) => ({
      onPointerDown: (e: ReactPointerEvent<HTMLElement>) => onPointerDown(e, id),
    }),
  };
}
