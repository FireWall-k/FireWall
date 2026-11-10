// 고치면 좋은 단계(명세 5.2-5, 2열 카드). 단계 그림 96 · 문장 · 신호 칩 · 한국어 제안 · [이 단계 고치기](주).
// 제안은 서버가 규칙만으로 고른다(유료 모델 없이 동작). [이 단계 고치기]는 편집기 그 단계로 바로 간다(?step=&fix=).
import { Link } from "react-router-dom";
import { Lightbulb } from "lucide-react";
import { buttonClasses, cardClasses } from "../../components/ui";
import { cn } from "../../cn";
import type { CoachingCard } from "../api/types";
import { coaching as copy } from "../copy";
import Thumb from "./Thumb";
import { editorLink } from "./time";

function Chip({ children }: { children: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-paper-200 bg-paper-50 px-2 py-0.5 text-ui-xs font-semibold tabular-nums text-ink-700">
      {children}
    </span>
  );
}

export default function CoachingCards({ cards }: { cards: CoachingCard[] }) {
  if (cards.length === 0) {
    return (
      <div className={cn(cardClasses, "p-6")}>
        <p className="text-ui-base font-semibold text-ink-900">{copy.empty}</p>
        <p className="mt-1 text-ui-sm text-ink-700">{copy.emptyBody}</p>
      </div>
    );
  }
  return (
    <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2">
      {cards.map((c) => {
        const s = c.signals;
        const chips = [
          s.replay_avg >= 1 ? copy.replay(s.replay_avg) : null,
          s.duration_avg_sec > 0 ? copy.avg(s.duration_avg_sec) : null,
          s.help_count > 0 ? copy.help(s.help_count) : null,
          copy.runs(s.runs),
        ].filter((x): x is string => !!x);
        return (
          <li key={`${c.task_id}:${c.source_step_id}`} data-testid="coaching-card" className={cn(cardClasses, "flex gap-4 p-4")}>
            <Thumb url={c.thumb_url} size={96} />
            <div className="flex min-w-0 flex-1 flex-col gap-2">
              <p className="text-ui-sm text-ink-700">{c.task_title}</p>
              <p className="text-ui-md font-semibold text-ink-900">{c.sentence}</p>
              <div className="flex flex-wrap gap-1">
                {chips.map((t) => (
                  <Chip key={t}>{t}</Chip>
                ))}
              </div>
              {c.after && (
                <p className="text-ui-sm text-ink-700">
                  {copy.after(c.after.since_version_no)} · {copy.afterAvg(c.after.duration_avg_sec)}
                </p>
              )}
              <p className="flex items-center gap-1 text-ui-sm font-semibold text-ink-900">
                <Lightbulb size={16} strokeWidth={2} aria-hidden="true" className="shrink-0 text-warn-700" />
                <span className="sr-only">{copy.suggestionLabel} </span>
                {copy.suggestion[c.suggestion]}
              </p>
              <div>
                {c.step_id ? (
                  <Link
                    to={editorLink(c.task_id, c.source_step_id, c.suggestion)}
                    aria-label={copy.fixLabel(c.task_title, c.sentence)}
                    className={buttonClasses("primary", "md")}
                  >
                    {copy.fix}
                  </Link>
                ) : (
                  <p className="text-ui-sm text-ink-700">{copy.removed}</p>
                )}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
