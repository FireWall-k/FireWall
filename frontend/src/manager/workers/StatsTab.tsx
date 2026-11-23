// 근로자 상세 '현황'(명세 5.7: 옛 대시보드 차트를 옮김). 최근 7일.
// - 위: 다 한 일·도움 요청·단계 평균 시간('2분 28초').
// - 날마다 다 한 일(막대 7개, 막대마다 숫자), 단계별 평균 시간(가로 막대 + '2분 28초').
// - [표로 보기]를 누르면 같은 값을 표로 보인다(명세 8.2: 차트에는 숫자 레이블과 표로 보기).
// 단계별 평균 시간: 도움 요청이 있었던 단계는 빨간 막대 + '도움 요청 N번' 글자(색만으로 뜻을 전하지 않는다, 명세 8.2).
// 다시 듣기가 있으면 '다시 듣기 N번'도 함께 적는다. 날마다 다 한 일은 moss-600 하나.
import { useCallback, useEffect, useState } from "react";
import { Card, Button, EmptyState } from "../../components/ui";
import { duration, workerStats as copy } from "../copy";
import { workerStats } from "../api/workers";
import type { WorkerStats } from "../api/workerTypes";
import { errorMessage } from "../tasks/listHelpers";
import { monthDay } from "./helpers";

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <Card className="flex flex-col gap-1">
      <span className="text-ui-sm text-ink-700">{label}</span>
      <span className="text-ui-xl font-bold tabular-nums text-ink-900">{value}</span>
    </Card>
  );
}

export default function StatsTab({ workerId }: { workerId: string }) {
  const [data, setData] = useState<WorkerStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asTable, setAsTable] = useState(false);

  const load = useCallback(() => {
    workerStats(workerId, 7)
      .then(setData)
      .catch((e) => setError(errorMessage(e)));
  }, [workerId]);
  useEffect(() => {
    load();
  }, [load]);

  if (error) return <EmptyState kind="error" description={error} onRetry={() => {
            setError(null);
            load();
          }} />;
  if (!data) return <EmptyState kind="loading" />;

  const totalDone = data.daily.reduce((a, d) => a + d.done, 0);
  const totalHelp = data.daily.reduce((a, d) => a + d.help, 0);
  const maxDone = Math.max(1, ...data.daily.map((d) => d.done));
  const maxSec = Math.max(1, ...data.steps.map((s) => s.avg_duration_sec));
  const dayLabel = (day: string) => {
    const [m, d] = monthDay(day);
    return copy.dayLabel(m, d);
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-ui-lg font-bold text-ink-900">{copy.heading}</h2>
        <Button size="sm" aria-pressed={asTable} onClick={() => setAsTable((v) => !v)}>
          {asTable ? copy.showChart : copy.showTable}
        </Button>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Tile label={copy.totalDone} value={copy.times(totalDone)} />
        <Tile label={copy.totalHelp} value={copy.times(totalHelp)} />
        <Tile label={copy.avgStep} value={duration(data.avg_step_sec)} />
      </div>

      {asTable ? (
        <>
          <StatTable
            caption={copy.dayCaption}
            head={[copy.colDay, copy.colAssigned, copy.colDone, copy.totalHelp]}
            rows={data.daily.map((d) => [dayLabel(d.day), copy.times(d.assigned), copy.times(d.done), copy.times(d.help)])}
          />
          {data.steps.length > 0 && (
            <StatTable
              caption={copy.tableCaption}
              head={[copy.colTask, copy.colStep, copy.colAvg, copy.colReplay, copy.colHelp]}
              rows={data.steps.map((s) => [
                s.task_title,
                copy.stepName(s.order, s.sentence),
                duration(s.avg_duration_sec),
                copy.times(s.replay_count),
                copy.times(s.help_count),
              ])}
            />
          )}
        </>
      ) : (
        <>
          <Card>
            <h3 className="mb-3 text-ui-base font-semibold text-ink-900">{copy.doneChart}</h3>
            <ul className="grid h-40 grid-cols-7 items-end gap-2" data-testid="done-chart">
              {data.daily.map((d) => (
                <li key={d.day} className="flex h-full flex-col items-center justify-end gap-1" aria-label={copy.doneBarLabel(dayLabel(d.day), d.done)}>
                  <span aria-hidden="true" className="text-ui-sm font-semibold tabular-nums text-ink-900">
                    {d.done}
                  </span>
                  <span
                    aria-hidden="true"
                    className="w-full max-w-8 rounded-t bg-moss-600"
                    style={{ height: d.done > 0 ? `${Math.max(6, (d.done / maxDone) * 100)}%` : "2px" }}
                  />
                  <span aria-hidden="true" className="text-ui-xs tabular-nums text-ink-700">
                    {dayLabel(d.day)}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
          <Card>
            <h3 className="text-ui-base font-semibold text-ink-900">{copy.stepChart}</h3>
            <p className="mb-3 text-ui-sm text-ink-700">
              <span className="font-semibold text-danger-700">{copy.stepLegendRed}</span>
              {copy.stepLegendPost}
            </p>
            {data.steps.length === 0 ? (
              <EmptyState kind="empty" title={copy.emptyTitle} description={copy.emptyBody} />
            ) : (
              <ul className="flex flex-col gap-3" data-testid="step-chart">
                {data.steps.map((s) => {
                  const helped = s.help_count > 0;
                  return (
                    <li key={`${s.task_id}-${s.order}`} className="flex flex-col gap-1" data-helped={helped ? "true" : undefined}>
                      <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-ui-sm text-ink-700">
                        <span>
                          {s.task_title} · {copy.stepName(s.order, s.sentence)}
                        </span>
                        {helped && <span className="font-semibold text-danger-700">{copy.helpTag(s.help_count)}</span>}
                        {s.replay_count > 0 && <span className="text-ink-700">{copy.replayTag(s.replay_count)}</span>}
                      </span>
                      <span className="flex items-center gap-2">
                        <span aria-hidden="true" className="h-3 flex-1 rounded-r bg-paper-100">
                          <span
                            className={helped ? "block h-3 rounded-r bg-signal-red" : "block h-3 rounded-r bg-moss-600"}
                            style={{ width: `${Math.max(2, (s.avg_duration_sec / maxSec) * 100)}%` }}
                          />
                        </span>
                        <span className="w-24 shrink-0 whitespace-nowrap text-right text-ui-sm font-semibold tabular-nums text-ink-900">
                          {duration(s.avg_duration_sec)}
                        </span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

function StatTable({ caption, head, rows }: { caption: string; head: string[]; rows: string[][] }) {
  return (
    // 좁은 화면에서 옆으로 넘기는 표는 키보드로도 넘길 수 있게 초점을 받는다(axe scrollable-region-focusable).
    <div role="region" aria-label={caption} tabIndex={0} className="overflow-x-auto rounded-card border border-paper-200 bg-white">
      <table className="w-full border-collapse text-ui-base text-ink-900">
        <caption className="px-4 pt-3 text-left text-ui-base font-semibold">{caption}</caption>
        <thead>
          <tr>
            {head.map((h, i) => (
              <th key={i} scope="col" className="whitespace-nowrap border-b border-paper-200 bg-paper-50 px-4 py-2 text-left text-ui-xs font-semibold text-ink-700">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-paper-200 last:border-b-0">
              {r.map((c, j) => (
                <td key={j} className="px-4 py-2 tabular-nums">
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
