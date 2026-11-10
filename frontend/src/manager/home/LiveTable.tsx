// 근로자 실시간 표(명세 5.2-4, 행 56). 열: 근로자(이니셜 + 이름) · 지금 하는 일 · 진행(점 + '3/6') ·
// 지금 단계(썸네일 40 + 문장 1줄) · 상태 배지 · 마지막 활동 · … 메뉴.
// 행(또는 이름 버튼)을 누르면 오른쪽 서랍에 오늘 기록이 열린다. 상태는 서버가 판정한 배지를 그대로 보인다.
// 휴대폰(768 미만)에서는 하는 일·진행을 이름 아래 한 줄로 줄이고 열은 숨긴다.
import { useNavigate } from "react-router-dom";
import { Ellipsis } from "lucide-react";
import { Avatar, Menu, Table, iconButtonClasses, type Column } from "../../components/ui";
import type { LiveWorker } from "../api/types";
import { liveTable as copy } from "../copy";
import { LiveStatusBadge } from "./badge";
import Thumb from "./Thumb";
import { agoText, minutesSince } from "./time";

export interface LiveTableProps {
  workers: LiveWorker[];
  /** 서버 시계로 맞춘 지금(ms). */
  now: number;
  onOpen: (w: LiveWorker) => void;
  empty?: string;
}

function ProgressDots({ done, total }: { done: number; total: number }) {
  const n = Math.min(total, 10);
  const filled = Math.round((done / Math.max(1, total)) * n);
  return (
    <span className="inline-flex items-center gap-2" aria-label={copy.progressLabel(done, total)} role="img">
      <span aria-hidden="true" className="inline-flex gap-0.5">
        {Array.from({ length: n }, (_, i) => (
          <span key={i} className={i < filled ? "size-1.5 rounded-full bg-moss-600" : "size-1.5 rounded-full bg-paper-200"} />
        ))}
      </span>
      <span aria-hidden="true" className="text-ui-sm tabular-nums text-ink-700">
        {copy.progress(done, total)}
      </span>
    </span>
  );
}

function taskText(w: LiveWorker): string {
  if (w.current) return w.current.task_title;
  if (w.today.length > 0 && w.today.every((t) => t.status === "done")) return copy.allDone;
  return copy.noTask;
}

export default function LiveTable({ workers, now, onOpen, empty }: LiveTableProps) {
  const navigate = useNavigate();
  const columns: Column<LiveWorker>[] = [
    {
      key: "worker",
      header: copy.colWorker,
      cell: (w) => (
        <div className="flex min-w-0 items-center gap-3">
          <Avatar initials={w.initials} />
          <div className="flex min-w-0 flex-col">
            <button
              type="button"
              data-testid="live-worker-name"
              onClick={(e) => {
                e.stopPropagation();
                onOpen(w);
              }}
              className="max-w-full truncate rounded-control text-left font-semibold text-ink-900 hover:underline"
            >
              {w.display_name}
            </button>
            <span className="truncate text-ui-sm text-ink-700 md:hidden">
              {taskText(w)}
              {w.current && ` · ${copy.progress(w.current.done, w.current.total)}`}
            </span>
          </div>
        </div>
      ),
    },
    {
      key: "task",
      header: copy.colTask,
      hideBelow: "md",
      cell: (w) => <span className="line-clamp-1 text-ink-900">{taskText(w)}</span>,
    },
    {
      key: "progress",
      header: copy.colProgress,
      hideBelow: "md",
      cell: (w) =>
        w.current ? <ProgressDots done={w.current.done} total={w.current.total} /> : <span className="text-ink-500">{copy.notYet}</span>,
    },
    {
      key: "step",
      header: copy.colStep,
      hideBelow: "lg",
      cell: (w) =>
        w.current?.step ? (
          <span className="flex min-w-0 items-center gap-2">
            <Thumb url={w.current.step.thumb_url} />
            <span className="line-clamp-1 min-w-0 text-ui-sm text-ink-900">{copy.stepLine(w.current.step.order, w.current.step.sentence)}</span>
          </span>
        ) : (
          <span className="text-ink-500">{copy.notYet}</span>
        ),
    },
    {
      key: "status",
      header: copy.colStatus,
      cell: (w) => (
        <span className="flex flex-col items-start gap-0.5">
          <LiveStatusBadge badge={w.badge} />
          {w.badge === "offline" && (
            <span className="whitespace-nowrap text-ui-xs text-ink-700">{copy.offlineSince(minutesSince(w.last_signal_at, now))}</span>
          )}
        </span>
      ),
    },
    {
      key: "activity",
      header: copy.colActivity,
      hideBelow: "md",
      cell: (w) => (
        <span className="whitespace-nowrap text-ui-sm tabular-nums text-ink-700">
          {w.last_activity_at ? agoText(w.last_activity_at, now) : copy.notYet}
        </span>
      ),
    },
    {
      key: "menu",
      header: <span className="sr-only">{copy.colMenu}</span>,
      align: "right",
      cell: (w) => (
        // 메뉴를 눌러도 행 클릭(서랍 열기)으로 번지지 않게 한다.
        <span onClick={(e) => e.stopPropagation()}>
          <Menu
            label={copy.rowMenu(w.display_name)}
            items={[
              { id: "timeline", label: copy.openTimeline, onSelect: () => onOpen(w) },
              { id: "worker", label: copy.workerInfo, onSelect: () => navigate("/m/workers") },
            ]}
            trigger={(p) => (
              <button {...p} type="button" aria-label={copy.rowMenu(w.display_name)} className={iconButtonClasses("ghost")}>
                <Ellipsis size={20} strokeWidth={2} aria-hidden="true" />
              </button>
            )}
          />
        </span>
      ),
    },
  ];

  return (
    <div data-testid="live-table">
      <Table
        columns={columns}
        rows={workers}
        rowKey={(w) => w.worker_id}
        caption={copy.caption}
        onRowClick={onOpen}
        empty={<p className="px-4 py-10 text-center text-ui-base text-ink-500">{empty ?? copy.emptyFiltered}</p>}
      />
    </div>
  );
}
