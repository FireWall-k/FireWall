import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AlertCircle, BarChart3, CheckCircle2, Clock, RotateCcw, Sparkles } from "lucide-react";
import { api, AuthError, type Coaching, type Dashboard, type TaskSummary } from "../api";

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

function DashboardPage() {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [taskId, setTaskId] = useState<string>("");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [coaching, setCoaching] = useState<Coaching | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.listTasks()
      .then((list) => {
        if (!alive) return;
        setTasks(list);
        const firstPublished = list.find((t) => t.status === "published") ?? list[0];
        setTaskId(firstPublished?.id ?? "");
      })
      .catch((e) => {
        if (!alive) return;
        setError(e instanceof AuthError ? "다시 로그인해 주세요." : e instanceof Error ? e.message : "직무 목록을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!taskId) return;
    let alive = true;
    Promise.all([
      api.dashboard(taskId),
      api.coaching(taskId).catch(() => null),
    ])
      .then(([d, c]) => {
        if (!alive) return;
        setDashboard(d);
        setCoaching(c);
      })
      .catch((e) => {
        if (!alive) return;
        setDashboard(null);
        setCoaching(null);
        setError(e instanceof AuthError ? "다시 로그인해 주세요." : e instanceof Error ? e.message : "대시보드를 불러오지 못했습니다.");
      })

    return () => { alive = false; };
  }, [taskId]);

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

  const replayTotal = dashboard?.steps.reduce((sum, step) => sum + step.replay_count, 0) ?? 0;
  const stuckTotal = dashboard?.stuck_steps.length ?? 0;

  function selectTask(id: string) {
    setTaskId(id);
    setDashboard(null);
    setCoaching(null);
    setError(null);
  }

  if (loading) return <EmptyState message="직무 목록을 불러오는 중입니다…" />;

  return (
    <div className="mx-auto max-w-6xl">
      <header className="mb-7 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold text-ink-900">수행 대시보드</h1>
          <p className="mt-1 text-sm text-ink-500">
            백엔드 수행 로그를 집계해 완료율, 반복 청취, 막힘 단계를 보여줘요.
          </p>
        </div>
        <select
          value={taskId}
          onChange={(e) => selectTask(e.target.value)}
          className="rounded-lg border border-paper-200 bg-white px-3 py-2 text-sm text-ink-900 focus:border-moss-500 focus:outline-none"
          aria-label="대시보드 직무 선택"
        >
          {tasks.map((t) => (
            <option key={t.id} value={t.id}>
              {t.title} {t.status === "published" ? "(게시됨)" : "(초안)"}
            </option>
          ))}
        </select>
      </header>

      {error && <div role="alert" className="mb-5 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</div>}
      {!tasks.length && <EmptyState message="아직 생성된 직무가 없습니다. 먼저 직무 입력 화면에서 직무를 만들어 주세요." />}
      {tasks.length > 0 && taskId && !dashboard && !error && <EmptyState message="선택한 직무의 수행 로그를 불러오는 중입니다…" />}
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
                    <Bar dataKey="소요시간" radius={[6, 6, 0, 0]} fill="#5C7A52" />
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
