// … 메뉴(명세 5.3, 7.3). 단추를 누르면 아래(또는 위)에 항목이 열린다.
// 키보드(WAI-ARIA menu button): ↓/↑로 옮기고 Home/End, Enter·Space로 고르고, Esc면 닫혀 단추로 돌아가고
// Tab이면 닫힌다. 지금 쓸 수 없는 항목은 aria-disabled + 이유(hint, 예: '새 편집기에서 열려요')를 함께 보인다.
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "../../cn";
import { popoverClasses } from "./styles";

export interface MenuItem {
  id: string;
  label: ReactNode;
  onSelect?: () => void;
  icon?: ReactNode;
  disabled?: boolean;
  /** 항목 아래 작은 설명(쓸 수 없는 이유 등). */
  hint?: ReactNode;
  danger?: boolean;
}

export interface MenuTriggerProps {
  id: string;
  "aria-haspopup": "menu";
  "aria-expanded": boolean;
  "aria-controls": string | undefined;
  onClick: () => void;
  onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => void;
}

export interface MenuProps {
  /** 단추를 그린다. 단추에 그대로 펼쳐 붙일 속성을 받는다. */
  trigger: (props: MenuTriggerProps) => ReactNode;
  items: MenuItem[];
  align?: "left" | "right";
  /** up: 단추 위로 연다(휴대폰 아래 탭바). */
  placement?: "down" | "up";
  /** 메뉴 이름(화면 읽기 프로그램). */
  label: string;
  /** 단추와 메뉴를 감싸는 칸의 클래스(아래 탭바처럼 칸을 꽉 채울 때). */
  className?: string;
}

export default function Menu({ trigger, items, align = "right", placement = "down", label, className }: MenuProps) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const baseId = useId();
  const menuId = baseId + "-menu";
  const triggerId = baseId + "-trigger";

  const enabled = items.map((it, i) => (it.disabled ? -1 : i)).filter((i) => i >= 0);

  function openAt(index: number) {
    setOpen(true);
    setActive(index);
  }
  function close(returnFocus = true) {
    setOpen(false);
    // 단추는 trigger가 그리므로 ref 대신 id로 찾는다(렌더 중 ref를 넘기지 않음).
    if (returnFocus) document.getElementById(triggerId)?.focus();
  }

  // 열리면 고른 항목으로 초점을 옮긴다.
  useEffect(() => {
    if (open) itemRefs.current[active]?.focus();
  }, [open, active]);

  // 바깥을 누르면 닫는다.
  useEffect(() => {
    if (!open) return;
    function onDown(e: PointerEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  function move(dir: 1 | -1 | "first" | "last") {
    if (enabled.length === 0) return;
    if (dir === "first") return setActive(enabled[0]);
    if (dir === "last") return setActive(enabled[enabled.length - 1]);
    const pos = enabled.indexOf(active);
    setActive(enabled[(pos + dir + enabled.length) % enabled.length]);
  }

  function onMenuKeyDown(e: KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      move(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      move(-1);
    } else if (e.key === "Home") {
      e.preventDefault();
      move("first");
    } else if (e.key === "End") {
      e.preventDefault();
      move("last");
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close();
    } else if (e.key === "Tab") {
      close(false);
    }
  }

  function select(it: MenuItem) {
    if (it.disabled) return;
    close();
    it.onSelect?.();
  }

  const triggerProps: MenuTriggerProps = {
    id: triggerId,
    "aria-haspopup": "menu",
    "aria-expanded": open,
    "aria-controls": open ? menuId : undefined,
    onClick: () => (open ? close(false) : openAt(enabled[0] ?? 0)),
    onKeyDown: (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        openAt(enabled[0] ?? 0);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        openAt(enabled[enabled.length - 1] ?? 0);
      }
    },
  };

  return (
    <div ref={wrapRef} className={cn("relative inline-flex", className)}>
      {trigger(triggerProps)}
      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label={label}
          onKeyDown={onMenuKeyDown}
          className={cn(
            popoverClasses,
            "absolute z-40 min-w-48 animate-pop-in py-1",
            align === "right" ? "right-0" : "left-0",
            placement === "down" ? "top-full mt-1" : "bottom-full mb-1",
          )}
        >
          {items.map((it, i) => (
            <button
              key={it.id}
              ref={(el) => {
                itemRefs.current[i] = el;
              }}
              type="button"
              role="menuitem"
              tabIndex={i === active ? 0 : -1}
              aria-disabled={it.disabled || undefined}
              aria-labelledby={it.hint ? baseId + "-label-" + i : undefined}
              aria-describedby={it.hint ? baseId + "-hint-" + i : undefined}
              onClick={() => select(it)}
              onMouseEnter={() => !it.disabled && setActive(i)}
              className={cn(
                "flex min-h-control w-full items-start gap-2 px-3 py-2 text-left text-ui-base coarse:min-h-control-coarse",
                it.disabled
                  ? "cursor-not-allowed text-ink-500"
                  : it.danger
                    ? "text-danger-700 hover:bg-danger-50 focus-visible:bg-danger-50"
                    : "text-ink-900 hover:bg-paper-100 focus-visible:bg-paper-100",
              )}
            >
              {it.icon && <span className="mt-0.5 shrink-0">{it.icon}</span>}
              <span className="flex min-w-0 flex-col">
                <span id={baseId + "-label-" + i} className="whitespace-nowrap font-semibold">
                  {it.label}
                </span>
                {it.hint && (
                  <span id={baseId + "-hint-" + i} className="text-ui-xs text-ink-500">
                    {it.hint}
                  </span>
                )}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
