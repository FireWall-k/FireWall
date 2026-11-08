// 직무 카드(명세 4.2·4.8, 7.1 JobCard). 홈과 했던 일에서 같이 쓴다. 카드 전체가 버튼 하나다.
// 왼쪽 대표 그림 96(첫 단계 그림), 오른쪽 이름(28px 굵게, 2줄까지)·진행 점·상태 글(20px).
// 다음에 할 카드 하나만 4px 초록 테두리 + '시작하기 ›'. 다 한 카드는 연한 초록 바탕 + 체크.
import type { Step } from "../api";
import { cn } from "../cn";
import { IconDone, IconNext } from "../ui/icons";
import { COPY } from "./copy";
import { ProgressDots } from "./ProgressDots";

export function Thumb({ url, size, className }: { url: string | null | undefined; size: number; className?: string }) {
  return url ? (
    <img src={url} alt="" width={size} height={size} draggable={false}
      style={{ width: size, height: size }}
      className={cn("shrink-0 rounded-worker-btn border-2 border-worker-line-soft bg-white object-contain", className)} />
  ) : (
    <span aria-hidden="true" style={{ width: size, height: size }}
      className={cn("shrink-0 rounded-worker-btn border-2 border-worker-line-soft bg-worker-card", className)} />
  );
}

export function JobCard({
  title,
  steps,
  doneIds,
  statusText,
  highlight = false,
  done = false,
  onPress,
}: {
  title: string;
  steps: Step[];
  doneIds: ReadonlySet<string>;
  statusText: string;
  highlight?: boolean;
  done?: boolean;
  onPress: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onPress}
      data-testid="job-card"
      data-next={highlight || undefined}
      data-done={done || undefined}
      className={cn(
        "flex min-h-32 w-full shrink-0 items-center gap-4 rounded-worker-card p-4 text-left shadow-worker-card",
        done ? "border-2 border-worker-primary bg-worker-primary-tint" : "bg-worker-card",
        highlight ? "border-4 border-worker-primary" : !done && "border-2 border-worker-line-soft",
        "hc:border-black",
      )}
    >
      <span className="relative shrink-0">
        <Thumb url={steps[0]?.symbol_url} size={96} />
        {done && (
          <span className="absolute -right-2 -top-2 flex size-9 items-center justify-center rounded-full bg-worker-primary text-white">
            <IconDone size={22} strokeWidth={3.5} />
          </span>
        )}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span className="line-clamp-2 whitespace-normal text-worker-title">{title}</span>
        <ProgressDots total={steps.length} current={-1} done={(i) => doneIds.has(steps[i]?.id ?? "")} size="sm" />
        <span className="whitespace-normal text-worker-caption text-worker-ink-soft hc:text-black">{statusText}</span>
        {highlight && (
          <span className="flex items-center gap-1 text-worker font-bold text-worker-primary hc:text-black">
            {COPY.btn.start}
            <IconNext size={24} />
          </span>
        )}
      </span>
    </button>
  );
}
