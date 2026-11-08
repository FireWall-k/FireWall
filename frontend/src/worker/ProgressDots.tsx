// 진행 점(명세 4.4-B, 7.1 ProgressDots). 숫자는 화면에 쓰지 않는다 — 화면 읽기 프로그램만 '6단계 중 3단계'로 읽는다.
// 끝낸 단계: 초록 바탕 흰 체크 / 지금 단계: 24px + 바깥 링 / 남은 단계: 2px 테두리. 12개가 넘으면 칸 막대.
import { cn } from "../cn";
import { COPY } from "./copy";
import { IconDone } from "../ui/icons";

export const DOTS_MAX = 12;

export function ProgressDots({
  total,
  current,
  done,
  size = "md",
  className,
}: {
  total: number;
  /** 지금 단계(0부터). 없으면 -1(홈 카드처럼 '지금'이 없는 곳). */
  current: number;
  /** i번째 단계를 끝냈는지. */
  done: (i: number) => boolean;
  size?: "sm" | "md";
  className?: string;
}) {
  const label = current >= 0 ? COPY.step.srProgress(current + 1, total) : undefined;
  const items = Array.from({ length: total }, (_, i) => i);
  if (total > DOTS_MAX) {
    return (
      <div role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}
        data-testid="progress-dots" className={cn("flex w-full items-center gap-1", className)}>
        {items.map((i) => (
          <span key={i}
            className={cn("h-3 flex-1 rounded-full",
              done(i) ? "bg-worker-primary" : i === current ? "bg-worker-help-line" : "border-2 border-worker-line bg-worker-card")} />
        ))}
      </div>
    );
  }
  const sm = size === "sm";
  return (
    <div role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}
      data-testid="progress-dots" className={cn("flex flex-wrap items-center", sm ? "gap-1.5" : "gap-2.5", className)}>
      {items.map((i) => {
        const isDone = done(i);
        const isCurrent = i === current;
        return (
          <span
            key={i}
            data-state={isCurrent ? "current" : isDone ? "done" : "todo"}
            className={cn(
              "flex shrink-0 items-center justify-center rounded-full",
              sm ? "size-3" : isCurrent ? "size-6" : "size-4",
              isDone ? "bg-worker-primary text-white" : isCurrent ? "bg-worker-card" : "border-2 border-worker-line bg-worker-card",
              isCurrent && "ring-[3px] ring-worker-primary ring-offset-2 ring-offset-worker-bg",
              isCurrent && isDone && "bg-worker-primary",
            )}
          >
            {isDone && !sm && <IconDone size={isCurrent ? 16 : 12} strokeWidth={3.5} />}
          </span>
        );
      })}
    </div>
  );
}
