// 상태 배지(명세 7.3, 8.2): 색만으로 뜻을 전하지 않는다 — 색 + 아이콘 + 글을 함께 둔다.
// auto(보라)는 아직 확인하지 않은 자동 결과에만 쓰고 아이콘은 ✦다('AI'라고 적지 않음, 명세 5.10).
import type { ReactNode } from "react";
import { CircleAlert, CircleCheck, CircleX, Info } from "lucide-react";
import { cn } from "../../cn";

export type Tone = "neutral" | "success" | "warning" | "danger" | "auto" | "info";

const TONE: Record<Tone, string> = {
  neutral: cn("border-paper-200 bg-paper-100 text-ink-700"),
  success: cn("border-ok-700/20 bg-ok-50 text-ok-700"),
  warning: cn("border-warn-line/30 bg-warn-50 text-warn-700"),
  danger: cn("border-danger-700/20 bg-danger-50 text-danger-700"),
  auto: cn("border-auto-700/20 bg-auto-50 text-auto-700"),
  info: cn("border-info-700/20 bg-white text-info-700"),
};

const DOT: Record<Tone, string> = {
  neutral: cn("bg-ink-500"),
  success: cn("bg-ok-700"),
  warning: cn("bg-warn-line"),
  danger: cn("bg-danger-700"),
  auto: cn("bg-auto-700"),
  info: cn("bg-info-700"),
};

function ToneIcon({ tone }: { tone: Tone }) {
  const p = { size: 14, strokeWidth: 2, "aria-hidden": true as const, className: "shrink-0" };
  switch (tone) {
    case "success":
      return <CircleCheck {...p} />;
    case "warning":
      return <CircleAlert {...p} />;
    case "danger":
      return <CircleX {...p} />;
    case "info":
      return <Info {...p} />;
    case "auto":
      return (
        <span aria-hidden="true" className="shrink-0 leading-none">
          ✦
        </span>
      );
    default:
      return null;
  }
}

export interface BadgeProps {
  tone?: Tone;
  /** 기본 아이콘 대신 쓸 아이콘. false면 아이콘 없이(neutral처럼 글만으로 충분할 때). */
  icon?: ReactNode | false;
  className?: string;
  children: ReactNode;
}

export function Badge({ tone = "neutral", icon, className, children }: BadgeProps) {
  return (
    <span
      className={cn(
        "badge inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-ui-xs font-semibold tabular-nums",
        TONE[tone],
        className,
      )}
    >
      {icon === false ? null : icon ?? <ToneIcon tone={tone} />}
      {children}
    </span>
  );
}

/** 표 안의 짧은 상태(점 + 글). 점은 꾸밈이고 뜻은 글이 전한다. */
export function StatusDot({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap text-ui-sm text-ink-700", className)}>
      <span aria-hidden="true" className={cn("size-2 shrink-0 rounded-full", DOT[tone])} />
      {children}
    </span>
  );
}
