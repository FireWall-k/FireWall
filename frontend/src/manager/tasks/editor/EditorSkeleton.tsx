// 편집기 모양 스켈레톤(명세 3.4-A 3번, tasks §4.3). [이대로 그림 고르기] 뒤 초안을 만드는 동안(서버가 그림을 고르고
// 목소리를 만든다) 편집기 자리에 그린다. 진행은 단계 이름만 보인다: '그림을 고르고 있어요 → 목소리를 만들고 있어요'.
// 퍼센트·남은 시간 같은 숫자는 꾸며내지 않는다(서버가 진행률을 주지 않는다).
import { useEffect, useState } from "react";
import { Check, LoaderCircle } from "lucide-react";
import Skeleton from "../../../components/ui/Skeleton";
import { cn } from "../../../cn";
import { editorProgress as copy } from "../../copy";

/** 그림 단계를 이만큼 보인 뒤 목소리 단계로 넘긴다(서버는 그림을 먼저, 목소리를 나중에 만든다). */
export const VOICE_STAGE_MS = 2500;

export interface EditorSkeletonProps {
  /** creating: 초안을 만드는 중(진행 단계를 보임), loading: 이미 있는 직무를 불러오는 중. */
  mode: "creating" | "loading";
  /** 단계 줄 수(나눈 줄 수를 알면 그만큼). */
  rows?: number;
}

export default function EditorSkeleton({ mode, rows = 5 }: EditorSkeletonProps) {
  const [stage, setStage] = useState<0 | 1>(0);
  useEffect(() => {
    if (mode !== "creating") return;
    const t = window.setTimeout(() => setStage(1), VOICE_STAGE_MS);
    return () => window.clearTimeout(t);
  }, [mode]);

  const stages = [copy.pictures, copy.voice];
  return (
    <div data-testid="editor-skeleton" aria-busy="true" className="flex flex-col gap-4">
      <div className="flex h-16 items-center gap-3 rounded-card border border-paper-200 bg-white px-4">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-5 w-16" />
        <span className="flex-1" />
        <Skeleton className="hidden h-9 w-28 md:block" />
        <Skeleton className="h-9 w-20" />
      </div>

      <div role="status" className="rounded-card border border-paper-200 bg-white p-4">
        {mode === "creating" ? (
          <>
            <p className="sr-only">{copy.label}</p>
            <ol className="flex flex-wrap items-center gap-x-3 gap-y-2 text-ui-md">
              {stages.map((label, i) => {
                const done = i < stage;
                const current = i === stage;
                return (
                  <li key={label} className="flex items-center gap-2" aria-current={current ? "step" : undefined}>
                    {i > 0 && (
                      <span aria-hidden="true" className="text-ink-500">
                        →
                      </span>
                    )}
                    {done ? (
                      <Check size={18} strokeWidth={2} aria-hidden="true" className="text-ok-700" />
                    ) : (
                      <LoaderCircle
                        size={18}
                        strokeWidth={2}
                        aria-hidden="true"
                        className={cn("text-moss-600", current ? "animate-spin motion-reduce:animate-none" : "opacity-40")}
                      />
                    )}
                    <span className={cn(current ? "font-bold text-ink-900" : "text-ink-700")}>{label}</span>
                  </li>
                );
              })}
            </ol>
          </>
        ) : (
          <p className="text-ui-md text-ink-700">{copy.loading}</p>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-[280px_minmax(0,1fr)] xl:grid-cols-[320px_minmax(0,1fr)]">
        <ul aria-hidden="true" className="flex flex-col gap-2">
          {Array.from({ length: Math.min(Math.max(rows, 3), 8) }, (_, i) => (
            <li key={i} className="flex h-[88px] items-center gap-3 rounded-card border border-paper-200 bg-white px-3">
              <Skeleton className="size-16 shrink-0" />
              <span className="flex flex-1 flex-col gap-2">
                <Skeleton className="h-4 w-4/5" />
                <Skeleton className="h-3 w-1/2" />
              </span>
            </li>
          ))}
        </ul>
        <div aria-hidden="true" className="hidden flex-col gap-4 rounded-card border border-paper-200 bg-white p-5 md:flex">
          <Skeleton className="size-[280px] max-w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-4 w-1/3" />
        </div>
      </div>
    </div>
  );
}
