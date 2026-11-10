// 근로자 오늘 기록 서랍(명세 5.2-4, Sheet 480). 단계별 걸린 시간·다시 듣기·이전 누름·도움과 시간 순 기록.
// 막대(걸린 시간)에는 '표로 보기' 대안을 함께 둔다(명세 8.2: 차트만으로 뜻을 전하지 않음).
import { useEffect, useState } from "react";
import { EmptyState, Sheet, Skeleton, Tabs } from "../../components/ui";
import { getTimeline } from "../api/live";
import type { TimelineAssignment, TimelineOut } from "../api/types";
import { durationText, liveBadge, timeline as copy } from "../copy";
import { clockText } from "../shell/useLive";
import Thumb from "./Thumb";
import { parseUtc } from "./time";

type View = "chart" | "table";

export interface TimelineDrawerProps {
  workerId: string | null;
  /** 서랍 제목에 쓸 이름(불러오기 전에도 보이게). */
  name: string;
  onClose: () => void;
}

export default function TimelineDrawer({ workerId, name, onClose }: TimelineDrawerProps) {
  const [attempt, setAttempt] = useState(0);
  return (
    <Sheet open={workerId != null} onClose={onClose} title={copy.title(name)} description={copy.description}>
      {workerId && <TimelineBody key={`${workerId}:${attempt}`} workerId={workerId} onRetry={() => setAttempt((n) => n + 1)} />}
    </Sheet>
  );
}

/** 서랍 안. 근로자나 다시 불러오기가 바뀌면 key로 새로 만든다(상태를 처음부터). */
function TimelineBody({ workerId, onRetry }: { workerId: string; onRetry: () => void }) {
  const [data, setData] = useState<TimelineOut | null>(null);
  const [failed, setFailed] = useState(false);
  const [view, setView] = useState<View>("chart");

  useEffect(() => {
    let alive = true;
    getTimeline(workerId)
      .then((t) => alive && setData(t))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [workerId]);

  if (failed) return <EmptyState kind="error" title={copy.loadFailed} onRetry={onRetry} />;
  if (!data) {
    return (
      <div className="flex flex-col gap-3" aria-busy="true">
        <Skeleton className="h-6 w-1/2" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  if (data.assignments.length === 0) return <EmptyState kind="empty" title={copy.noRecord} />;
  return (
    <div className="flex flex-col gap-6">
      <Tabs<View>
        items={[
          { id: "chart", label: copy.chartView },
          { id: "table", label: copy.tableView },
        ]}
        value={view}
        onChange={setView}
        label={copy.viewLabel}
      />
      {data.assignments.map((a) => (
        <section key={a.assignment_id} aria-label={a.task_title} className="flex flex-col gap-3">
          <h3 className="flex items-center gap-2 text-ui-md font-bold text-ink-900">
            <span className="min-w-0 truncate">{a.task_title}</span>
            <span className="shrink-0 text-ui-sm font-semibold text-ink-700">{liveBadge[a.status]}</span>
          </h3>
          {view === "chart" ? <Bars a={a} /> : <StepTable a={a} />}
        </section>
      ))}
      <section aria-labelledby="timeline-events" className="flex flex-col gap-2">
        <h3 id="timeline-events" className="text-ui-md font-bold text-ink-900">
          {copy.eventsHeading}
        </h3>
        <ol className="flex flex-col gap-1 text-ui-base text-ink-700">
          {data.events.map((e, i) => {
            const title = data.assignments.find((x) => x.assignment_id === e.assignment_id)?.task_title ?? "";
            const what = e.kind === "step_done" ? copy.event.step_done(e.step_order ?? 0) : copy.event[e.kind];
            const t = parseUtc(e.at);
            return (
              <li key={`${e.at}-${i}`} className="flex gap-3">
                <span className="w-20 shrink-0 tabular-nums text-ink-700">{Number.isNaN(t) ? "" : clockText(t)}</span>
                <span className="min-w-0">
                  {title && <span className="text-ink-700">{title} · </span>}
                  {what}
                </span>
              </li>
            );
          })}
        </ol>
      </section>
    </div>
  );
}

/** 걸린 시간 막대(꾸밈). 숫자는 막대 옆에도 글로 적는다. */
function Bars({ a }: { a: TimelineAssignment }) {
  const max = Math.max(1, ...a.steps.map((s) => s.duration_sec ?? 0));
  return (
    <ul className="flex flex-col gap-2" data-testid="timeline-bars">
      {a.steps.map((s) => (
        <li key={s.step_id} className="flex items-center gap-3">
          <Thumb url={s.thumb_url} />
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="truncate text-ui-sm text-ink-900">
              {s.order}. {s.sentence}
            </span>
            <div className="flex items-center gap-2">
              <span aria-hidden="true" className="h-2 rounded-full bg-moss-600" style={{ width: `${Math.max(2, ((s.duration_sec ?? 0) / max) * 100)}%`, opacity: s.completed ? 1 : 0.25 }} />
              <span className="shrink-0 text-ui-xs tabular-nums text-ink-700">
                {s.completed && s.duration_sec != null ? durationText(s.duration_sec) : copy.notDone}
              </span>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

function StepTable({ a }: { a: TimelineAssignment }) {
  return (
    <div className="overflow-x-auto rounded-card border border-paper-200">
      <table className="w-full border-collapse text-ui-sm text-ink-900" data-testid="timeline-table">
        <caption className="sr-only">{copy.tableCaption(a.task_title)}</caption>
        <thead>
          <tr className="bg-paper-50 text-ui-xs text-ink-700">
            <th scope="col" className="px-3 py-2 text-left font-semibold">{copy.colStep}</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">{copy.colDuration}</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">{copy.colReplay}</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">{copy.colPrev}</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">{copy.colHelp}</th>
          </tr>
        </thead>
        <tbody>
          {a.steps.map((s) => (
            <tr key={s.step_id} className="border-t border-paper-200">
              <th scope="row" className="max-w-40 truncate px-3 py-2 text-left font-normal">
                {s.order}. {s.sentence}
              </th>
              <td className="px-3 py-2 text-right tabular-nums">
                {s.completed && s.duration_sec != null ? durationText(s.duration_sec) : copy.notDone}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{copy.times(s.replay_count)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{copy.times(s.prev_count)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{copy.times(s.help_count)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

