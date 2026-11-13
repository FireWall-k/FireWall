// 요약 카드 4칸(명세 5.2-3, 높이 96): 지금 일하는 사람 3/5명 · 도움 요청 1건 · 막힘 의심 2단계 · 확인이 필요한 직무 1개.
// 앞의 셋은 누르면 아래 표를 그 조건으로 걸러 본다(다시 누르면 풀림, aria-pressed). 넷째는 직무 목록 '확인 필요'로 간다.
// '전체 단계 수'와 '완료율 %'는 보이지 않는다.
import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { cn } from "../../cn";
import type { LiveSummary } from "../api/types";
import { summaryCards as copy } from "../copy";

export type HomeFilter = "working" | "help" | "stuck";

export interface SummaryCardsProps {
  summary: LiveSummary;
  /** 화면에서 누른 결과까지 반영한 열린 도움 수. */
  openHelp: number;
  filter: HomeFilter | null;
  onFilter: (f: HomeFilter | null) => void;
}

const CARD = cn(
  "flex h-24 min-w-0 flex-col justify-between rounded-card border bg-white p-4 text-left shadow-ui-sm transition-colors duration-hover",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-moss-600 focus-visible:ring-offset-2",
);

export default function SummaryCards({ summary, openHelp, filter, onFilter }: SummaryCardsProps) {
  const cards: { id: HomeFilter; label: string; value: string; alert: boolean }[] = [
    { id: "working", label: copy.working, value: copy.workingValue(summary.working, summary.total_workers), alert: false },
    { id: "help", label: copy.openHelp, value: copy.openHelpValue(openHelp), alert: openHelp > 0 },
    { id: "stuck", label: copy.stuck, value: copy.stuckValue(summary.stuck_steps), alert: summary.stuck_steps > 0 },
  ];
  return (
    <ul aria-label={copy.label} className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {cards.map((c) => {
        const pressed = filter === c.id;
        return (
          <li key={c.id} className="min-w-0">
            <button
              type="button"
              aria-pressed={pressed}
              data-testid={`summary-${c.id}`}
              onClick={() => onFilter(pressed ? null : c.id)}
              className={cn(CARD, "w-full", pressed ? "border-moss-600 ring-1 ring-moss-600" : "border-paper-200 hover:bg-paper-50")}
            >
              <span className="text-ui-sm font-semibold text-ink-700">{c.label}</span>
              <span className={cn("font-display text-ui-xl font-bold tabular-nums", c.alert ? "text-warn-700" : "text-ink-900")}>{c.value}</span>
            </button>
          </li>
        );
      })}
      <li className="min-w-0">
        <Link to="/manager/tasks?filter=needs_check" data-testid="summary-needs-check" className={cn(CARD, "border-paper-200 hover:bg-paper-50")}>
          <span className="text-ui-sm font-semibold text-ink-700">{copy.needsCheck}</span>
          <span className="flex items-end justify-between gap-2">
            <span className="font-display text-ui-xl font-bold tabular-nums text-ink-900">{copy.needsCheckValue(summary.needs_check_tasks)}</span>
            <span className="inline-flex items-center text-ui-xs font-semibold text-ink-500">
              {copy.needsCheckHint}
              <ChevronRight size={14} strokeWidth={2} aria-hidden="true" />
            </span>
          </span>
        </Link>
      </li>
    </ul>
  );
}
