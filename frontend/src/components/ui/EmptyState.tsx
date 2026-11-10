// 빈 자리 하나로 세 상황을 모양부터 다르게 보인다(명세 7.3):
// - loading: 회색 막대(스켈레톤) + '불러오는 중이에요'(role=status)
// - empty: 상자 그림 + 제목 + [만들기] 같은 다음 할 일
// - error: 빨간 아이콘 + 무엇이 안 됐는지 + [다시 시도](role=alert)
import type { ReactNode } from "react";
import { CircleAlert, Inbox } from "lucide-react";
import { cn } from "../../cn";
import { ui as copy } from "../../manager/copy";
import Button from "./Button";
import Skeleton from "./Skeleton";

export interface EmptyStateProps {
  kind: "loading" | "empty" | "error";
  title?: ReactNode;
  description?: ReactNode;
  /** 다음 할 일 버튼들(빈 상태). */
  actions?: ReactNode;
  /** 오류일 때 [다시 시도]. */
  onRetry?: () => void;
  /** 빈 상태 그림(없으면 상자 아이콘). */
  illustration?: ReactNode;
  className?: string;
}

export default function EmptyState({ kind, title, description, actions, onRetry, illustration, className }: EmptyStateProps) {
  if (kind === "loading") {
    return (
      <div role="status" data-state="loading" className={cn("flex flex-col gap-3 p-6", className)}>
        <span className="sr-only">{title ?? copy.loading}</span>
        <Skeleton className="h-5 w-1/3" />
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-4 w-1/2" />
      </div>
    );
  }
  const isError = kind === "error";
  return (
    <div
      role={isError ? "alert" : undefined}
      data-state={kind}
      className={cn("flex flex-col items-center gap-3 px-6 py-10 text-center", className)}
    >
      {isError ? (
        <span className="flex size-12 items-center justify-center rounded-full bg-danger-50 text-danger-700">
          <CircleAlert size={24} strokeWidth={2} aria-hidden="true" />
        </span>
      ) : (
        illustration ?? (
          <span className="flex size-16 items-center justify-center rounded-full bg-paper-100 text-ink-500">
            <Inbox size={28} strokeWidth={2} aria-hidden="true" />
          </span>
        )
      )}
      <p className={cn("text-ui-md font-bold", isError ? "text-danger-700" : "text-ink-900")}>
        {title ?? (isError ? copy.loadFailed : copy.empty)}
      </p>
      {description && <p className="max-w-md text-ui-base text-ink-700">{description}</p>}
      {(actions || (isError && onRetry)) && (
        <div className="mt-1 flex flex-wrap justify-center gap-2">
          {isError && onRetry && (
            <Button variant="secondary" onClick={onRetry}>
              {copy.retry}
            </Button>
          )}
          {actions}
        </div>
      )}
    </div>
  );
}
