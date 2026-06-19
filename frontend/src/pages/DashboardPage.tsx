import { useEffect, useState } from "react";
import { api, type Coaching, type Dashboard, type TaskSummary } from "../api";

const ACTION_LABEL: Record<string, string> = {
  rephrase: "문장 쉽게",
  photo: "사진으로 교체",
  split: "단계 분할",
  ok: "양호",
};

export default function DashboardPage() {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [taskId, setTaskId] = useState("");
  const [data, setData] = useState<Dashboard | null>(null);
  const [coaching, setCoaching] = useState<Coaching | null>(null);
  const [coachingBusy, setCoachingBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listTasks()
      .then((ts) => {
        setTasks(ts);
        if (ts[0]) {
          setTaskId(ts[0].id);
          load(ts[0].id);
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : "직무 목록 조회 실패"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function load(id: string) {
    if (!id) return;
    setError(null);
    setCoaching(null);
    try {
      setData(await api.dashboard(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "조회 실패");
    }
  }

  async function loadCoaching() {
    if (!taskId) return;
    setCoachingBusy(true);
    setError(null);
    try {
      setCoaching(await api.coaching(taskId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "AI 코칭 조회 실패");
    } finally {
      setCoachingBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-bold text-slate-900">진행 현황</h1>

      <div className="flex gap-2">
        <select
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
          value={taskId}
          onChange={(e) => { setTaskId(e.target.value); load(e.target.value); }}
          aria-label="직무 선택"
        >
          {tasks.length === 0 && <option value="">직무 없음</option>}
          {tasks.map((t) => (
            <option key={t.id} value={t.id}>
              {t.title} ({t.status})
            </option>
          ))}
        </select>
        <button onClick={() => load(taskId)} disabled={!taskId}
          className="rounded-lg bg-blue-700 px-4 py-2 font-semibold text-white disabled:opacity-50">
          새로고침
        </button>
      </div>

      {error && <div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</div>}

      {data && (
        <>
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <div className="text-sm text-slate-500">{data.task_title}</div>
            <div className="mt-1 flex items-end gap-2">
              <span className="text-4xl font-bold text-slate-900">{data.completion_rate}%</span>
              <span className="pb-1 text-sm text-slate-500">
                {data.completed_steps} / {data.total_steps} 단계 완료
              </span>
            </div>
            <div className="mt-3 h-3 w-full overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full bg-green-600" style={{ width: `${data.completion_rate}%` }} />
            </div>
            {data.stuck_steps.length > 0 && (
              <p className="mt-3 text-sm text-amber-700">막힌 단계: {data.stuck_steps.join(", ")}</p>
            )}
          </div>

          <table className="w-full overflow-hidden rounded-xl border border-slate-200 bg-white text-sm">
            <thead className="bg-slate-50 text-left text-slate-500">
              <tr>
                <th className="px-3 py-2">단계</th>
                <th className="px-3 py-2">내용</th>
                <th className="px-3 py-2">상태</th>
                <th className="px-3 py-2">소요(초)</th>
                <th className="px-3 py-2">다시듣기</th>
                <th className="px-3 py-2">막힘</th>
              </tr>
            </thead>
            <tbody>
              {data.steps.map((s) => (
                <tr key={s.order} className="border-t border-slate-100">
                  <td className="px-3 py-2 font-medium">{s.order}</td>
                  <td className="px-3 py-2">{s.sentence}</td>
                  <td className="px-3 py-2">
                    {s.completed ? <span className="text-green-700">완료</span> : <span className="text-slate-400">대기</span>}
                  </td>
                  <td className="px-3 py-2">{s.duration_sec || "-"}</td>
                  <td className="px-3 py-2">{s.replay_count}</td>
                  <td className="px-3 py-2">{s.stuck ? <span className="text-amber-700">●</span> : <span className="text-slate-300">-</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <section className="rounded-xl border border-indigo-200 bg-indigo-50/50 p-5">
            <div className="flex items-center justify-between">
              <h2 className="font-bold text-slate-900">AI 코칭 제안</h2>
              <button onClick={loadCoaching} disabled={coachingBusy}
                className="rounded-lg bg-indigo-700 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
                {coachingBusy ? "분석 중…" : "제안 받기"}
              </button>
            </div>
            <p className="mt-1 text-xs text-slate-500">
              근로자의 막힘·다시듣기·소요시간을 분석해 개선책을 제안합니다.
            </p>
            {coaching && (
              <div className="mt-3 space-y-2">
                <p className="text-sm font-medium text-slate-700">{coaching.summary}</p>
                {coaching.suggestions.length === 0 ? (
                  <p className="text-sm text-slate-500">현재 특별히 개선할 단계가 없습니다.</p>
                ) : (
                  coaching.suggestions.map((s) => (
                    <div key={s.order} className="rounded-lg border border-indigo-100 bg-white p-3">
                      <div className="flex items-center gap-2">
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-bold text-slate-700">
                          {s.order}단계
                        </span>
                        <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-semibold text-indigo-800">
                          {ACTION_LABEL[s.action] ?? s.action}
                        </span>
                      </div>
                      <p className="mt-2 text-sm text-slate-500">{s.issue}</p>
                      <p className="mt-1 text-sm font-medium text-slate-900">→ {s.suggestion}</p>
                    </div>
                  ))
                )}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
