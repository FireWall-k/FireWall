import React, { useState } from "react";
import { useApp, seedDashboard } from "../store/AppStore";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Cell,
} from "recharts";
import { Clock, RotateCcw, AlertCircle, TrendingUp, Users } from "lucide-react";

const StatCard: React.FC<{
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  accent?: string;
}> = ({ icon, label, value, sub, accent = "bg-moss-500/10 text-moss-600" }) => (
  <div className="rounded-2xl border border-paper-200 bg-white p-5 shadow-sm">
    <div className={`mb-3 flex h-9 w-9 items-center justify-center rounded-lg ${accent}`}>
      {icon}
    </div>
    <p className="text-2xl font-semibold text-ink-900">{value}</p>
    <p className="mt-0.5 text-sm text-ink-500">{label}</p>
    {sub && <p className="mt-1.5 text-xs text-moss-600">{sub}</p>}
  </div>
);

export const DashboardPage: React.FC = () => {
  const { tasks } = useApp();
  const publishedTasks = tasks.filter((t) => t.status === "published");
  const [taskId, setTaskId] = useState(publishedTasks[0]?.id ?? tasks[0]?.id);

  // 데모에서는 task1(seed)에 대해서만 상세 집계 데이터를 보여줌
  const dashboard = seedDashboard;
  const currentTask = tasks.find((t) => t.id === taskId);

  const chartData = dashboard.steps.map((s) => ({
    name: `${s.stepOrder}단계`,
    sentence: s.sentence,
    소요시간: s.avgDurationSec,
    반복청취: s.replayCount,
    막힘: s.stuckCount,
  }));

  const maxDuration = Math.max(...dashboard.steps.map((s) => s.avgDurationSec));

  return (
    <div className="mx-auto max-w-6xl">
      <header className="mb-7 flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold text-ink-900">수행 대시보드</h1>
          <p className="mt-1 text-sm text-ink-500">
            근로자의 수행 로그를 집계해 어느 단계가 어려운지 보여줘요.
          </p>
        </div>
        <select
          value={taskId}
          onChange={(e) => setTaskId(e.target.value)}
          className="rounded-lg border border-paper-200 bg-white px-3 py-2 text-sm text-ink-900 focus:border-moss-500 focus:outline-none"
        >
          {tasks.map((t) => (
            <option key={t.id} value={t.id}>
              {t.title}
            </option>
          ))}
        </select>
      </header>

      <div className="mb-6 grid grid-cols-4 gap-4">
        <StatCard
          icon={<Users size={18} />}
          label="수행 완료율"
          value={`${Math.round(dashboard.completionRate * 100)}%`}
          sub={`${dashboard.completedAssignments}/${dashboard.totalAssignments}명 완료`}
        />
        <StatCard
          icon={<TrendingUp size={18} />}
          label="사업주 설명시간 절감"
          value={`${dashboard.avgExplainTimeSavedMin}분`}
          sub="1일 기준 추정"
          accent="bg-clay-400/15 text-clay-600"
        />
        <StatCard
          icon={<AlertCircle size={18} />}
          label="막힌 단계 총합"
          value={`${dashboard.steps.reduce((a, s) => a + s.stuckCount, 0)}건`}
          accent="bg-signal-red/10 text-signal-red"
        />
        <StatCard
          icon={<RotateCcw size={18} />}
          label="반복 청취 총합"
          value={`${dashboard.steps.reduce((a, s) => a + s.replayCount, 0)}회`}
          accent="bg-signal-amber/15 text-clay-600"
        />
      </div>

      <div className="grid grid-cols-[1.3fr_1fr] gap-5">
        <div className="rounded-2xl border border-paper-200 bg-white p-5 shadow-sm">
          <div className="mb-1 flex items-center gap-2">
            <Clock size={16} className="text-ink-500" />
            <h3 className="text-sm font-semibold text-ink-900">단계별 평균 소요 시간</h3>
          </div>
          <p className="mb-4 text-xs text-ink-500">
            빨간색일수록 다른 단계보다 시간이 오래 걸려요 — 재분해 후보
          </p>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={chartData} margin={{ left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E6E0D2" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#647168" }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 12, fill: "#647168" }} axisLine={false} tickLine={false} unit="s" />
              <Tooltip
                formatter={(value) => [`${value}초`, "평균 소요 시간"]}
                labelFormatter={(_, payload) => payload?.[0]?.payload?.sentence ?? ""}
                contentStyle={{ borderRadius: 12, border: "1px solid #E6E0D2", fontSize: 13 }}
              />
              <Bar dataKey="소요시간" radius={[6, 6, 0, 0]}>
                {chartData.map((entry, i) => (
                  <Cell
                    key={i}
                    fill={entry.소요시간 === maxDuration ? "#C24B3F" : "#5C7A52"}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="rounded-2xl border border-paper-200 bg-white p-5 shadow-sm">
          <h3 className="mb-4 text-sm font-semibold text-ink-900">단계별 상세</h3>
          <div className="flex flex-col gap-3">
            {dashboard.steps.map((s) => (
              <div key={s.stepId} className="rounded-xl border border-paper-200 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-ink-500">{s.stepOrder}단계</span>
                  <span className="text-xs font-semibold text-moss-600">
                    {Math.round(s.completionRate * 100)}% 완료
                  </span>
                </div>
                <p className="mt-1 text-sm text-ink-900">{s.sentence}</p>
                <div className="mt-2 flex gap-3 text-xs text-ink-500">
                  <span>평균 {s.avgDurationSec}초</span>
                  <span>·</span>
                  <span>반복청취 {s.replayCount}회</span>
                  {s.stuckCount > 0 && (
                    <>
                      <span>·</span>
                      <span className="font-medium text-signal-red">막힘 {s.stuckCount}건</span>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {currentTask && currentTask.id !== dashboard.taskId && (
        <p className="mt-4 text-xs text-ink-500">
          * 데모 데이터는 "{dashboard.taskTitle}" 기준입니다. 실제로는 선택한 직무별로 GET
          /api/dashboard/tasks/&#123;id&#125; 응답을 그립니다.
        </p>
      )}
    </div>
  );
};
