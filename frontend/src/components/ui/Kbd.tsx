// 단축키 표시(명세 7.3). 화면 읽기 프로그램은 글자 그대로 읽는다.
import type { ReactNode } from "react";
import { cn } from "../../cn";

export default function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "inline-flex min-w-6 items-center justify-center rounded border border-paper-200 border-b-line-strong bg-white px-1.5 font-body text-ui-xs font-semibold text-ink-700",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
