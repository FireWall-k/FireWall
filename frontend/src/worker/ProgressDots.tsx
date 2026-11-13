// 진행 점(명세 4.4-B, 7.1 ProgressDots). 숫자는 화면에 쓰지 않는다 — 화면 읽기 프로그램만 '6단계 중 3단계'로 읽는다.
// 끝낸 단계: 초록 바탕 흰 체크(20px) / 지금 단계: 초록 바탕 흰 점(28px) + 바깥 링 / 남은 단계: 2px 테두리(20px).
// 색만이 아니라 모양(체크·점·빈 원)으로도 다르다(2026-11-13, COGA 'Make Each Step Clear'). 다시 보기(missed)에서
// 하지 않은 단계는 회색 줄표로, 아직 할 단계와 구별한다. 12개가 넘거나 위 띠 안(fit)이면 칸 막대.
import { cn } from "../cn";
import { COPY } from "./copy";
import { IconDone } from "../ui/icons";

export const DOTS_MAX = 12;

export function ProgressDots({
  total,
  current,
  done,
  size = "md",
  fit = false,
  missed = false,
  className,
}: {
  total: number;
  /** 지금 단계(0부터). 없으면 -1(홈 카드처럼 '지금'이 없는 곳). */
  current: number;
  /** i번째 단계를 끝냈는지. */
  done: (i: number) => boolean;
  size?: "sm" | "md";
  /** 다시 보기: 끝내지 않은 단계를 '안 함'(회색 줄표)으로 그린다. 일하는 중에는 끄고 '남음'(빈 원)으로 그린다. */
  missed?: boolean;
  /** 주어진 폭에 맞춘 칸 막대로(위 띠 안). 4차 검증: 가로 휴대폰 130% 글자에서 점이 두 줄로 꺾여 위 띠가 높아졌다.
   *  4차 검증 2회: 한 줄 점을 넘치는 대로 잘랐더니 지금 칸 고리가 잘리고 10단계 일은 점이 4개만 보였다 — 칸 막대는
   *  폭이 모자라면 칸이 좁아질 뿐 잘리지 않고, 지금 칸은 고리 대신 높이와 테두리로 다르다(밖으로 나가는 것이 없다). */
  fit?: boolean;
  className?: string;
}) {
  const label = current >= 0 ? COPY.step.srProgress(current + 1, total) : undefined;
  const items = Array.from({ length: total }, (_, i) => i);
  if (total > DOTS_MAX || fit) {
    return (
      <div role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}
        data-testid="progress-dots" data-layout="bar"
        className={cn("flex w-full min-w-0 items-center", fit ? "max-w-[16rem] gap-0.5" : "gap-1", className)}>
        {/* 지금 칸은 색만이 아니라 높이(20px)와 초록 테두리로도 다르다(3차 검증: 예전에는 주황(도움 색) 칸 하나로만 보였다,
            명세 6.1·8.1). 끝낸 칸은 초록 바탕, 남은 칸은 테두리만. */}
        {items.map((i) => (
          <span key={i}
            data-state={i === current ? "current" : done(i) ? "done" : missed ? "missed" : "todo"}
            className={cn("min-w-0 flex-1 rounded-full",
              i === current
                ? cn("h-5 min-w-[12px] border-[3px] border-worker-primary", done(i) ? "bg-worker-primary" : "bg-worker-card")
                : done(i) ? "h-3 bg-worker-primary" : missed ? "h-1.5 bg-worker-line" : "h-3 border-2 border-worker-line bg-worker-card")} />
        ))}
      </div>
    );
  }
  const sm = size === "sm";
  return (
    <div role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}
      data-testid="progress-dots" className={cn("flex flex-wrap items-center", sm ? "gap-1.5" : "gap-3", className)}>
      {items.map((i) => {
        const isDone = done(i);
        const isCurrent = i === current;
        const isMissed = missed && !sm && !isDone && !isCurrent;
        return (
          <span
            key={i}
            data-state={isCurrent ? "current" : isDone ? "done" : isMissed ? "missed" : "todo"}
            className={cn(
              "flex shrink-0 items-center justify-center rounded-full",
              sm ? "size-3" : isCurrent ? "size-7" : "size-5",
              isDone || isCurrent
                ? "bg-worker-primary text-white"
                : isMissed
                  ? "bg-transparent"
                  : "border-2 border-worker-line bg-worker-card",
              isCurrent && "ring-2 ring-worker-primary ring-offset-2 ring-offset-worker-bg",
            )}
          >
            {isDone && !sm && <IconDone size={isCurrent ? 18 : 14} strokeWidth={3.5} />}
            {isCurrent && !isDone && !sm && <span aria-hidden="true" className="size-2.5 rounded-full bg-white" />}
            {isMissed && !sm && <span aria-hidden="true" className="h-1 w-3.5 rounded-full bg-worker-line" />}
          </span>
        );
      })}
    </div>
  );
}
