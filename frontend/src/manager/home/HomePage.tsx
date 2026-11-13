// 홈 · 오늘 현황(/manager, 명세 5.2). 위에서 아래로:
// 1) 제목 줄: '오늘 현황' + '11월 8일 일요일 · 마지막 갱신 14:02:31'(끊기면 '연결이 잠시 끊겼어요 · 마지막 갱신 …') + [새 직무]
// 2) 도움 요청 띠는 틀(AppShell)이 모든 /manager 화면 맨 위에 그린다(HelpBand).
// 3) 요약 카드 4칸(누르면 아래 표를 걸러 봄) 4) 근로자 실시간 표(행을 누르면 오늘 기록 서랍) 5) 고치면 좋은 단계
// 6) 새 사업장이면 시작 점검표.
// 현황은 LiveProvider(5초 폴링 하나)를 읽는다. 이 화면이 따로 부르는 것은 코칭 카드(처음 한 번)와 서랍의 타임라인뿐이다.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Plus } from "lucide-react";
import { EmptyState, Skeleton, buttonClasses } from "../../components/ui";
import { cn } from "../../cn";
import { getCoaching } from "../api/live";
import type { CoachingCard, LiveWorker } from "../api/types";
import { coaching as coachingCopy, home, live as liveCopy, liveTable, summaryCards } from "../copy";
import { clockText, useLive } from "../shell/useLive";
import { WORKING_BADGES } from "./badgeMeta";
import CoachingCards from "./CoachingCards";
import HomeEmpty from "./HomeEmpty";
import LiveTable from "./LiveTable";
import SummaryCards, { type HomeFilter } from "./SummaryCards";
import TimelineDrawer from "./TimelineDrawer";

function dateText(ms: number): string {
  const d = new Date(ms);
  return home.date(d.getMonth() + 1, d.getDate(), home.weekdays[d.getDay()]);
}

const FILTER_LABEL: Record<HomeFilter, string> = {
  working: summaryCards.working,
  help: summaryCards.openHelp,
  stuck: summaryCards.stuck,
};

function matches(w: LiveWorker, f: HomeFilter | null): boolean {
  if (!f) return true;
  if (f === "working") return WORKING_BADGES.has(w.badge);
  if (f === "help") return w.badge === "help" || w.badge === "help_acked";
  return w.badge === "stuck_suspect";
}

export default function HomePage() {
  const { data, help, updatedAt, disconnected, now } = useLive();
  const [filter, setFilter] = useState<HomeFilter | null>(null);
  const [open, setOpen] = useState<{ id: string; name: string } | null>(null);
  const [cards, setCards] = useState<CoachingCard[] | null>(null);
  const [cardsFailed, setCardsFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    getCoaching(7)
      .then((c) => alive && setCards(Array.isArray(c) ? c : []))
      .catch(() => alive && setCardsFailed(true));
    return () => {
      alive = false;
    };
  }, []);

  const workers = useMemo(() => (data?.workers ?? []).filter((w) => matches(w, filter)), [data, filter]);
  const openHelp = help.filter((h) => h.state === "open").length;

  const setup: [boolean, boolean, boolean] | null = data
    ? [
        data.workers.length > 0,
        data.workers.some((w) => w.last_signal_at != null || w.last_activity_at != null),
        data.workers.some((w) => w.today.length > 0),
      ]
    : null;
  const setupDone = setup?.every(Boolean) ?? true;

  const statusLine = updatedAt
    ? `${disconnected ? liveCopy.disconnected : dateText(updatedAt)} · ${liveCopy.lastUpdated(clockText(updatedAt))}`
    : disconnected
      ? liveCopy.disconnected
      : liveCopy.loading;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex min-h-16 flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-ui-xl text-ink-900">{home.heading}</h1>
          <p
            data-testid="live-status-line"
            className={cn("mt-0.5 text-ui-sm tabular-nums", disconnected ? "font-semibold text-warn-700" : "text-ink-500")}
          >
            {statusLine}
          </p>
        </div>
        <Link to="/manager/tasks/new" className={cn(buttonClasses("primary", "md"), "hidden md:inline-flex")}>
          <Plus size={16} strokeWidth={2} aria-hidden="true" />
          {home.newTask}
        </Link>
      </div>

      {!data ? (
        disconnected ? (
          <EmptyState kind="error" title={liveCopy.loadFailed} description={liveCopy.loadFailedBody} />
        ) : (
          <div className="flex flex-col gap-3" aria-busy="true">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-24 w-full" />
              ))}
            </div>
            <Skeleton className="h-40 w-full" />
          </div>
        )
      ) : (
        <>
          {!setupDone && setup && <HomeEmpty done={setup} />}

          {data.workers.length > 0 && (
            <>
              <SummaryCards summary={data.summary} openHelp={openHelp} filter={filter} onFilter={setFilter} />

              <section aria-labelledby="live-table-title" className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-3">
                  <h2 id="live-table-title" className="text-ui-lg font-bold text-ink-900">
                    {liveTable.heading}
                  </h2>
                  {filter && (
                    <p role="status" className="flex flex-wrap items-center gap-2 text-ui-sm text-ink-700">
                      {summaryCards.filtering(FILTER_LABEL[filter])}
                      <button type="button" className={buttonClasses("ghost", "sm")} onClick={() => setFilter(null)}>
                        {summaryCards.clearFilter}
                      </button>
                    </p>
                  )}
                </div>
                <LiveTable workers={workers} now={now} onOpen={(w) => setOpen({ id: w.worker_id, name: w.display_name })} />
              </section>
            </>
          )}

          <section aria-labelledby="coaching-title" className="flex flex-col gap-3">
            <div>
              <h2 id="coaching-title" className="text-ui-lg font-bold text-ink-900">
                {coachingCopy.heading}
              </h2>
              <p className="text-ui-sm text-ink-700">{coachingCopy.description}</p>
            </div>
            {cardsFailed ? (
              <p className="text-ui-sm text-ink-700">{coachingCopy.loadFailed}</p>
            ) : cards == null ? (
              <Skeleton className="h-32 w-full" />
            ) : (
              <CoachingCards cards={cards} />
            )}
          </section>
        </>
      )}

      {open && <TimelineDrawer workerId={open.id} name={open.name} onClose={() => setOpen(null)} />}
    </div>
  );
}
