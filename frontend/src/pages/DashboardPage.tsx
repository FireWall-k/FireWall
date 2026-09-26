import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AlertCircle, BarChart3, CalendarDays, CheckCircle2, ChevronLeft, ChevronRight, Clock, RefreshCw, RotateCcw, Sparkles, Trash2 } from "lucide-react";
import { api, AuthError, type Coaching, type Dashboard, type TaskSummary, type Worker } from "../api";
import { BAR_COLOR, SLOWEST_BAR_COLOR, slowestIndex } from "../dashboardChart";

const DASHBOARD_POLL_MS = 10_000;

const formatClock = (d: Date) =>
  d.toLocaleTimeString("ko-KR", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });

const StatCard = ({
  icon,
  label,
  value,
  sub,
  accent = "bg-moss-500/10 text-moss-600",
}: {
  icon: ReactNode;
  label: string;
  value: string;
  sub?: string;
  accent?: string;
}) => (
  <div className="rounded-2xl border border-paper-200 bg-white p-5 shadow-sm">
    <div className={`mb-3 flex h-9 w-9 items-center justify-center rounded-lg ${accent}`}>{icon}</div>
    <p className="text-2xl font-semibold text-ink-900">{value}</p>
    <p className="mt-0.5 text-sm text-ink-500">{label}</p>
    {sub && <p className="mt-1.5 text-xs text-moss-600">{sub}</p>}
  </div>
);

function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-paper-200 bg-white p-8 text-center text-ink-500">
      {message}
    </div>
  );
}

function formatDuration(sec: number) {
  if (!sec) return "0초";
  if (sec < 60) return `${Math.round(sec)}초`;
  const min = Math.floor(sec / 60);
  const rest = Math.round(sec % 60);
  return rest ? `${min}분 ${rest}초` : `${min}분`;
}

// 같은 이름의 직무를 드롭다운에서 구별하기 위해 생성 시각을 "M/D HH:mm"로 보여준다.
function formatCreatedAt(iso: string) {
  // 백엔드는 UTC로 저장하지만 직렬화 문자열에 tz 표시(Z/+09:00)가 없을 수 있다.
  // 그대로 두면 브라우저가 현지 시각으로 오해하므로, tz가 없으면 UTC(Z)로 간주한다.
  const hasTz = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso);
  const d = new Date(hasTz ? iso : `${iso}Z`);
  if (Number.isNaN(d.getTime())) return "";
  const mm = d.getMonth() + 1;
  const dd = d.getDate();
  const hh = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return `${mm}/${dd} ${hh}:${min}`;
}

function ymd(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

function MiniCalendar({
  selected,
  activeDates,
  onPick,
}: {
  selected: string;
  activeDates: string[];
  onPick: (date: string) => void;
}) {
  const sel = new Date(`${selected}T00:00:00`);
  const [view, setView] = useState(new Date(sel.getFullYear(), sel.getMonth(), 1));
  const todayYmd = ymd(new Date());
  const active = new Set(activeDates);
  const year = view.getFullYear();
  const month = view.getMonth();
  const firstWeekday = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: (number | null)[] = [];
  for (let i = 0; i < firstWeekday; i += 1) cells.push(null);
  for (let d = 1; d <= daysInMonth; d += 1) cells.push(d);

  return (
    <div className="absolute right-0 top-full z-30 mt-2 w-72 rounded-xl border border-paper-200 bg-white p-3 shadow-lg">
      <div className="mb-2 flex items-center justify-between">
        <button onClick={() => setView(new Date(year, month - 1, 1))} className="rounded p-1 text-ink-500 hover:bg-paper-100" aria-label="이전 달">
          <ChevronLeft size={16} />
        </button>
        <span className="text-sm font-semibold text-ink-900">{year}년 {month + 1}월</span>
        <button onClick={() => setView(new Date(year, month + 1, 1))} className="rounded p-1 text-ink-500 hover:bg-paper-100" aria-label="다음 달">
          <ChevronRight size={16} />
        </button>
      </div>
      <div className="grid grid-cols-7 gap-0.5 text-center">
        {WEEKDAYS.map((w) => (
          <div key={w} className="py-1 text-xs font-medium text-ink-500">{w}</div>
        ))}
        {cells.map((d, i) => {
          if (d === null) return <div key={`empty-${i}`} />;
          const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
          const isSel = dateStr === selected;
          const isToday = dateStr === todayYmd;
          const hasData = active.has(dateStr);
          return (
            <button
              key={dateStr}
              onClick={() => onPick(dateStr)}
              className={
                "relative aspect-square rounded-lg text-sm " +
                (isSel
                  ? "bg-moss-500 font-bold text-white"
                  : isToday
                    ? "bg-paper-100 font-semibold text-ink-900"
                    : "text-ink-700 hover:bg-paper-100")
              }
            >
              {d}
              {hasData && !isSel && (
                <span className="absolute bottom-1 left-1/2 h-1 w-1 -translate-x-1/2 rounded-full bg-moss-500" />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function DashboardPage() {
  // 근로자 중심: 근로자 먼저 고르고 → 그 근로자의 직무를 본다.
  const [allWorkers, setAllWorkers] = useState<Worker[]>([]);
  const [workerId, setWorkerId] = useState<string>("");
  const [workerTasks, setWorkerTasks] = useState<TaskSummary[]>([]);
  const [taskId, setTaskId] = useState<string>("");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [coaching, setCoaching] = useState<Coaching | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 달력: 선택한 날짜(기본 오늘)의 직무만 본다. activeDates는 달력에 활동일 표시용.
  const [selectedDate, setSelectedDate] = useState<string>(() => ymd(new Date()));
  const [showCalendar, setShowCalendar] = useState(false);
  const [activeDates, setActiveDates] = useState<string[]>([]);

  // 사업주의 전체 근로자 목록을 불러와 첫 근로자를 고른다.
  useEffect(() => {
    let alive = true;
    api.listWorkers()
      .then((ws) => {
        if (!alive) return;
        setAllWorkers(ws);
        setWorkerId(ws[0]?.id ?? "");
      })
      .catch((e) => {
        if (!alive) return;
        setError(e instanceof AuthError ? "다시 로그인해 주세요." : e instanceof Error ? e.message : "근로자 목록을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => { alive = false; };
  }, []);

  // 근로자가 바뀌면 그 근로자의 활동일(달력 표시용)을 불러온다.
  useEffect(() => {
    // workerId는 ""(첫 렌더)에서 근로자 id로만 바뀐다(선택 목록에 빈 항목이 없다).
    // 빈 값일 때 상태는 이미 초기값(빈 목록)이므로 따로 비우지 않는다.
    if (!workerId) return;
    let alive = true;
    api.workerActiveDates(workerId)
      .then((ds) => { if (alive) setActiveDates(ds); })
      .catch(() => { if (alive) setActiveDates([]); });
    return () => { alive = false; };
  }, [workerId]);

  // (근로자, 날짜)가 정해지면 그 날짜에 배정된 직무 목록을 불러와 첫 직무를 고른다.
  useEffect(() => {
    if (!workerId) return; // 위와 같은 이유로 초기값 그대로 둔다.
    // 이전 화면 지우기(setDashboard/setCoaching(null))는 근로자·날짜를 바꾸는 핸들러
    // (selectWorker, 달력 onPick)가 한다 — effect 안에서 바로 setState하면 렌더가 연쇄된다.
    let alive = true;
    api.workerTasks(workerId, selectedDate)
      .then((ts) => {
        if (!alive) return;
        setWorkerTasks(ts);
        setTaskId(ts[0]?.id ?? "");
      })
      .catch((e) => {
        if (!alive) return;
        setWorkerTasks([]);
        setTaskId("");
        setError(e instanceof AuthError ? "다시 로그인해 주세요." : e instanceof Error ? e.message : "직무 목록을 불러오지 못했습니다.");
      });
    return () => { alive = false; };
  }, [workerId, selectedDate]);

  // 근로자가 수행하는 동안 화면이 따라오도록 주기적으로 다시 불러온다(실시간 푸시가 아니라 폴링).
  // 코칭은 LLM 호출이라 폴링에 넣지 않는다 — 첫 로드와 수동 새로고침 때만 갱신한다.
  const viewKey = useRef("");
  const inFlightKey = useRef("");
  // 근로자·직무를 바꾸면 이전 화면의 갱신 상태가 남지 않도록 화면 키(viewKeyNow)로 태깅해 둔다.
  const viewKeyNow = taskId && workerId ? `${taskId}|${workerId}` : "";
  const [sync, setSync] = useState<{ key: string; at: Date | null; failed: boolean; busy: boolean }>(
    { key: "", at: null, failed: false, busy: false }
  );
  const current = sync.key === viewKeyNow;
  const lastUpdated = current ? sync.at : null;
  const pollFailed = current && sync.failed;
  const refreshing = current && sync.busy;

  const loadDashboard = useCallback(
    (opts: { coaching: boolean; initial: boolean }) => {
      if (!taskId || !workerId) return;
      const key = `${taskId}|${workerId}`;
      if (inFlightKey.current === key) return; // 같은 화면의 요청이 이미 진행 중이면 겹치지 않는다.
      inFlightKey.current = key;
      Promise.all([
        api.dashboard(taskId, workerId),
        opts.coaching ? api.coaching(taskId, workerId).catch(() => null) : Promise.resolve(undefined),
      ])
        .then(([d, c]) => {
          if (viewKey.current !== key) return; // 그 사이 근로자·직무를 바꿨다면 늦게 온 응답은 버린다.
          setDashboard(d);
          if (c !== undefined) setCoaching(c);
          setSync({ key, at: new Date(), failed: false, busy: false });
        })
        .catch((e) => {
          if (viewKey.current !== key) return;
          if (e instanceof AuthError) {
            setError("다시 로그인해 주세요.");
          } else if (opts.initial) {
            setDashboard(null);
            setCoaching(null);
            setError(e instanceof Error ? e.message : "대시보드를 불러오지 못했습니다.");
          } else {
            setSync((p) => ({ ...p, key, failed: true })); // 백그라운드 갱신 실패는 기존 화면을 지우지 않고 표시만 한다.
          }
        })
        .finally(() => {
          if (inFlightKey.current === key) inFlightKey.current = "";
          if (viewKey.current === key) setSync((p) => (p.key === key ? { ...p, busy: false } : p));
        });
    },
    [taskId, workerId]
  );

  // 스피너는 사용자가 누른 새로고침에만 보여 준다(자동 갱신이 깜빡이지 않게).
  function manualRefresh() {
    if (!viewKeyNow) return;
    setSync((p) => ({ key: viewKeyNow, at: p.key === viewKeyNow ? p.at : null, failed: p.key === viewKeyNow && p.failed, busy: true }));
    loadDashboard({ coaching: true, initial: false });
  }

  // 선택된 (근로자, 직무)의 수행 데이터와 코칭을 처음 불러온다.
  useEffect(() => {
    viewKey.current = taskId && workerId ? `${taskId}|${workerId}` : "";
    if (!taskId || !workerId) return;
    loadDashboard({ coaching: true, initial: true });
  }, [taskId, workerId, loadDashboard]);

  // 10초마다, 그리고 탭으로 돌아왔을 때 다시 불러온다. 숨겨진 탭에서는 요청하지 않는다.
  useEffect(() => {
    if (!taskId || !workerId) return;
    const tick = () => {
      if (!document.hidden) loadDashboard({ coaching: false, initial: false });
    };
    const timer = window.setInterval(tick, DASHBOARD_POLL_MS);
    document.addEventListener("visibilitychange", tick);
    window.addEventListener("focus", tick);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
      window.removeEventListener("focus", tick);
    };
  }, [taskId, workerId, loadDashboard]);

  const chartData = useMemo(
    () => dashboard?.steps.map((s) => ({
      name: `${s.order}단계`,
      sentence: s.sentence,
      소요시간: Math.round(s.duration_sec),
      반복청취: s.replay_count,
      막힘: s.stuck ? 1 : 0,
    })) ?? [],
    [dashboard]
  );
  const slowest = useMemo(() => slowestIndex(chartData.map((d) => d.소요시간)), [chartData]);

  const replayTotal = dashboard?.steps.reduce((sum, step) => sum + step.replay_count, 0) ?? 0;
  const stuckTotal = dashboard?.stuck_steps.length ?? 0;

  function selectWorker(id: string) {
    setWorkerId(id);
    setSelectedDate(ymd(new Date())); // 근로자를 바꾸면 '오늘' 업무로 리셋
    setShowCalendar(false);
    setDashboard(null);
    setCoaching(null);
    setError(null);
  }

  function selectTask(id: string) {
    setTaskId(id);
    setDashboard(null);
    setCoaching(null);
    setError(null);
  }

  async function deleteCurrentTask() {
    if (!taskId) return;
    const current = workerTasks.find((t) => t.id === taskId);
    if (!window.confirm(`'${current?.title ?? "이 직무"}'를 삭제할까요?\n수행 기록도 함께 삭제되며 되돌릴 수 없습니다.`)) {
      return;
    }
    try {
      await api.deleteTask(taskId);
      const remaining = workerTasks.filter((t) => t.id !== taskId);
      setWorkerTasks(remaining);
      setTaskId(remaining[0]?.id ?? "");
      setDashboard(null);
      setCoaching(null);
      setError(null);
    } catch (e) {
      setError(e instanceof AuthError ? "다시 로그인해 주세요." : e instanceof Error ? e.message : "직무 삭제에 실패했습니다.");
    }
  }

  if (loading) return <EmptyState message="근로자 목록을 불러오는 중입니다…" />;

  return (
    <div className="mx-auto max-w-6xl">
      <header className="sticky top-0 z-20 -mx-8 mb-6 flex flex-col gap-4 border-b border-paper-200 bg-paper-50/95 px-8 py-4 backdrop-blur md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold text-ink-900">수행 대시보드</h1>
          <p className="mt-1 text-sm text-ink-500">
            근로자의 수행 기록을 모아 완료율, 반복 청취, 막힘 단계를 보여줘요.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {allWorkers.length > 0 && (
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowCalendar((v) => !v)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-paper-200 bg-white px-3 py-2 text-sm font-medium text-ink-700 hover:bg-paper-100"
                aria-label="날짜 선택 달력 열기"
              >
                <CalendarDays size={15} />
                {selectedDate === ymd(new Date()) ? "오늘" : selectedDate}
              </button>
              {showCalendar && (
                <>
                  <div className="fixed inset-0 z-20" onClick={() => setShowCalendar(false)} />
                  <MiniCalendar
                    selected={selectedDate}
                    activeDates={activeDates}
                    onPick={(d) => {
                      setShowCalendar(false);
                      if (d === selectedDate) return; // 같은 날짜면 직무 목록을 다시 불러오지 않으니 화면도 그대로 둔다.
                      setSelectedDate(d);
                      setDashboard(null);
                      setCoaching(null);
                    }}
                  />
                </>
              )}
            </div>
          )}
          {allWorkers.length > 0 && (
            <select
              value={workerId}
              onChange={(e) => selectWorker(e.target.value)}
              className="rounded-lg border border-paper-200 bg-white px-3 py-2 text-sm text-ink-900 focus:border-moss-500 focus:outline-none"
              aria-label="대시보드 근로자 선택"
            >
              {allWorkers.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.display_name} (코드 {w.access_code})
                </option>
              ))}
            </select>
          )}
          {workerTasks.length > 0 && (
            <select
              value={taskId}
              onChange={(e) => selectTask(e.target.value)}
              className="rounded-lg border border-paper-200 bg-white px-3 py-2 text-sm text-ink-900 focus:border-moss-500 focus:outline-none"
              aria-label="대시보드 직무 선택"
            >
              {workerTasks.map((t) => (
                <option key={t.id} value={t.id}>
                  {formatCreatedAt(t.created_at)} · {t.title} {t.status === "published" ? "(게시됨)" : "(초안)"}
                </option>
              ))}
            </select>
          )}
          {taskId && (
            <div className="flex items-center gap-2">
              <span
                className={`text-xs ${pollFailed ? "text-signal-red" : "text-ink-500"}`}
                role="status"
                aria-live="polite"
              >
                {pollFailed
                  ? "갱신 실패 — 다시 시도 중"
                  : lastUpdated
                    ? `마지막 갱신 ${formatClock(lastUpdated)}`
                    : "불러오는 중…"}
              </span>
              <button
                type="button"
                onClick={manualRefresh}
                disabled={refreshing}
                className="inline-flex items-center gap-1.5 rounded-lg border border-paper-200 bg-white px-3 py-2 text-sm font-medium text-ink-700 hover:bg-paper-100 disabled:opacity-60"
                aria-label="대시보드 새로고침"
              >
                <RefreshCw size={15} className={refreshing ? "animate-spin" : ""} />
                새로고침
              </button>
            </div>
          )}
          {taskId && (
            <button
              type="button"
              onClick={deleteCurrentTask}
              className="inline-flex items-center gap-1.5 rounded-lg border border-paper-200 bg-white px-3 py-2 text-sm font-medium text-signal-red hover:bg-signal-red/5"
              aria-label="선택한 직무 삭제"
            >
              <Trash2 size={15} />
              삭제
            </button>
          )}
        </div>
      </header>

      {error && <div role="alert" className="mb-5 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</div>}
      {!allWorkers.length && <EmptyState message="아직 등록된 근로자가 없습니다. ‘직무 입력·검토’ 화면에서 근로자를 추가하고 직무를 보내 주세요." />}
      {allWorkers.length > 0 && workerId && !workerTasks.length && !error && (
        <EmptyState
          message={
            selectedDate === ymd(new Date())
              ? "이 근로자에게 오늘 배정된 직무가 없습니다. 달력에서 다른 날짜를 선택해 보세요."
              : `${selectedDate}에 이 근로자에게 배정된 직무가 없습니다. 달력에서 다른 날짜를 선택해 보세요.`
          }
        />
      )}
      {workerTasks.length > 0 && taskId && !dashboard && !error && (
        <EmptyState message="선택한 직무의 수행 로그를 불러오는 중입니다…" />
      )}
      {dashboard && (
        <>
          <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              icon={<CheckCircle2 size={18} />}
              label="단계 완료율"
              value={`${dashboard.completion_rate}%`}
              sub={`${dashboard.completed_steps}/${dashboard.total_steps}단계 완료`}
            />
            <StatCard
              icon={<AlertCircle size={18} />}
              label="막힘 표시 단계"
              value={`${stuckTotal}개`}
              sub={stuckTotal ? `${dashboard.stuck_steps.join(", ")}단계 확인 필요` : "막힘 기록 없음"}
              accent="bg-signal-red/10 text-signal-red"
            />
            <StatCard
              icon={<RotateCcw size={18} />}
              label="반복 청취 총합"
              value={`${replayTotal}회`}
              sub="근로자가 다시 듣기를 누른 횟수"
              accent="bg-signal-amber/15 text-clay-600"
            />
            <StatCard
              icon={<BarChart3 size={18} />}
              label="전체 단계 수"
              value={`${dashboard.total_steps}개`}
              sub={dashboard.task_title}
              accent="bg-clay-400/15 text-clay-600"
            />
          </div>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1.3fr_1fr]">
            <div className="rounded-2xl border border-paper-200 bg-white p-5 shadow-sm">
              <div className="mb-1 flex items-center gap-2">
                <Clock size={16} className="text-ink-500" />
                <h3 className="text-sm font-semibold text-ink-900">단계별 소요 시간</h3>
              </div>
              <p className="mb-4 text-xs text-ink-500">
                완료 로그가 쌓이면 어떤 단계에서 시간이 오래 걸렸는지 확인할 수 있어요.
                {slowest >= 0 && (
                  <span className="ml-1 font-medium" style={{ color: SLOWEST_BAR_COLOR }}>
                    빨간 막대는 가장 오래 걸린 단계({chartData[slowest].name})예요.
                  </span>
                )}
              </p>
              {chartData.length ? (
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={chartData} margin={{ left: -10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#E6E0D2" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#647168" }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 12, fill: "#647168" }} axisLine={false} tickLine={false} unit="s" />
                    <Tooltip
                      formatter={(value) => [`${value}초`, "소요 시간"]}
                      labelFormatter={(_, payload) => payload?.[0]?.payload?.sentence ?? ""}
                      contentStyle={{ borderRadius: 12, border: "1px solid #E6E0D2", fontSize: 13 }}
                    />
                    <Bar dataKey="소요시간" radius={[6, 6, 0, 0]}>
                      {chartData.map((d, i) => (
                        <Cell key={d.name} fill={i === slowest ? SLOWEST_BAR_COLOR : BAR_COLOR} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <EmptyState message="아직 표시할 단계가 없습니다." />
              )}
            </div>

            <div className="rounded-2xl border border-paper-200 bg-white p-5 shadow-sm">
              <h3 className="mb-4 text-sm font-semibold text-ink-900">단계별 상세</h3>
              <div className="flex flex-col gap-3">
                {dashboard.steps.map((s) => (
                  <div key={`${s.order}-${s.sentence}`} className="rounded-xl border border-paper-200 p-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-ink-500">{s.order}단계</span>
                      <span className={`text-xs font-semibold ${s.completed ? "text-moss-600" : "text-ink-500"}`}>
                        {s.completed ? "완료됨" : "미완료"}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-ink-900">{s.sentence}</p>
                    <div className="mt-2 flex flex-wrap gap-2 text-xs text-ink-500">
                      <span>{formatDuration(s.duration_sec)}</span>
                      <span>반복청취 {s.replay_count}회</span>
                      {s.stuck && <span className="font-medium text-signal-red">막힘 기록</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <section className="mt-5 rounded-2xl border border-paper-200 bg-white p-5 shadow-sm">
            <div className="mb-3 flex items-center gap-2">
              <Sparkles size={17} className="text-clay-600" />
              <h3 className="text-sm font-semibold text-ink-900">AI 코칭 제안</h3>
            </div>
            {coaching ? (
              <div>
                <p className="rounded-xl bg-paper-100 px-4 py-3 text-sm text-ink-700">{coaching.summary || "아직 충분한 로그가 없습니다."}</p>
                <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                  {coaching.suggestions.map((s) => (
                    <div key={`${s.order}-${s.action}`} className="rounded-xl border border-paper-200 p-3">
                      <p className="text-xs font-bold text-clay-600">{s.order}단계 · {s.action}</p>
                      <p className="mt-1 text-sm font-semibold text-ink-900">{s.issue}</p>
                      <p className="mt-1 text-sm text-ink-600">{s.suggestion}</p>
                    </div>
                  ))}
                  {!coaching.suggestions.length && (
                    <p className="text-sm text-ink-500">현재는 추가 제안이 없습니다.</p>
                  )}
                </div>
              </div>
            ) : (
              <p className="text-sm text-ink-500">코칭 정보를 불러오지 못했습니다. 수행 로그는 위 대시보드에서 확인할 수 있습니다.</p>
            )}
          </section>
        </>
      )}
    </div>
  );
}

export { DashboardPage };
export default DashboardPage;
