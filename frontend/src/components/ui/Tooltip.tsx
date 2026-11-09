// 도움말 풍선(명세 7.3). 마우스를 올리거나 초점이 가면 보이고, Esc나 떠나면 사라진다.
// 안의 요소에 aria-describedby를 붙여 화면 읽기 프로그램도 읽는다. 눌리지 않는 버튼에도 쓸 수 있게
// 감싸는 span이 이벤트를 받는다 — disabled 속성 버튼은 초점을 못 받으므로 그런 자리는 aria-disabled를 쓴다.
import { cloneElement, isValidElement, useId, useState, type ReactElement, type ReactNode } from "react";
import { cn } from "../../cn";

export interface TooltipProps {
  content: ReactNode;
  children: ReactElement<{ "aria-describedby"?: string }>;
  side?: "top" | "bottom";
  className?: string;
}

export default function Tooltip({ content, children, side = "top", className }: TooltipProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const child = isValidElement(children)
    ? cloneElement(children, {
        "aria-describedby": [children.props["aria-describedby"], id].filter(Boolean).join(" "),
      })
    : children;
  return (
    <span
      className={cn("relative inline-flex", className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.stopPropagation();
          setOpen(false);
        }
      }}
    >
      {child}
      <span
        id={id}
        role="tooltip"
        hidden={!open}
        className={cn(
          "pointer-events-none absolute left-1/2 z-40 w-max max-w-64 -translate-x-1/2 animate-pop-in rounded-control bg-ink-900 px-2.5 py-1.5 text-ui-sm text-white shadow-ui-md",
          side === "top" ? "bottom-full mb-2" : "top-full mt-2",
        )}
      >
        {content}
      </span>
    </span>
  );
}
