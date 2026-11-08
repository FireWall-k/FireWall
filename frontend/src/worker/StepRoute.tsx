// /w/job/:aid/step/:n — 일하는 중인 단계 화면(StepPlayer live)에 데이터를 잇는다.
// - 어디서 이어 갈지: 주소의 n + 서버 done_step_ids + 대기열(resume.ts). 새로고침·다른 기기에서도 그 자리.
// - [다 했어요] → 대기열에 기록(오프라인이어도 잃지 않음) → 다음 단계 / 마지막이면 완료 화면.
// - 도움 요청은 따로(useHelp), [다 했어요]를 누르면 서버가 열린 요청을 닫는다.
// - 화면 꺼짐 방지는 이 화면에 있는 동안 켠다.
import { useCallback } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { useHelp } from "./hooks/useHelp";
import { useWakeLock } from "./hooks/useWakeLock";
import { resolveStepIndex } from "./resume";
import { useBand, useWorkerSession } from "./session";
import { StepPlayer, type StepDoneInfo } from "./StepPlayer";
import type { TodayJob } from "./workerApi";

function LiveStep({ job, n }: { job: TodayJob; n: string | undefined }) {
  const navigate = useNavigate();
  const { prefs, progressOf, completeStep, onMediaError, online } = useWorkerSession();
  const { band } = useBand();
  const p = progressOf(job);
  const index = resolveStepIndex(job.steps, n, p.doneIds);
  const step = index == null ? null : job.steps[index];
  const help = useHelp({
    assignmentId: job.assignment_id,
    stepId: step?.id ?? null,
    initial: job.active_help,
  });
  useWakeLock(true);

  const base = `/w/job/${job.assignment_id}`;
  const onDone = useCallback(
    (info: StepDoneInfo) => {
      completeStep(job, info.step, { durationSec: info.durationSec, replayCount: info.replayCount, stuck: info.stuck });
      help.markStepDone();
      if (info.index + 1 >= job.steps.length) navigate(`${base}/done`, { replace: true });
      else navigate(`${base}/step/${info.index + 2}`, { replace: true });
    },
    [completeStep, job, help, navigate, base],
  );

  if (index == null) return <Navigate to={`${base}/done`} replace />;
  // 주소가 범위 밖이었으면 이어서 할 단계 주소로 바꿔 둔다(새로고침해도 같은 자리).
  if (String(index + 1) !== n) return <Navigate to={`${base}/step/${index + 1}`} replace />;

  // 이 화면에서 끝낸 단계도 점에 바로 보이게(서버 응답을 기다리지 않음).
  return (
    <StepPlayer
      mode="live"
      title={job.task_title}
      steps={job.steps}
      index={index}
      doneIds={p.doneIds}
      prefs={prefs}
      help={help}
      band={band}
      offline={!online}
      onDone={onDone}
      onPrev={() => navigate(`${base}/step/${Math.max(1, index)}`, { replace: true })}
      onExit={() => navigate("/w/today")}
      onMediaError={onMediaError}
    />
  );
}

export default function StepRoute() {
  const { aid, n } = useParams();
  const { jobs } = useWorkerSession();
  const job = jobs.find((j) => j.assignment_id === aid);
  if (!job || job.steps.length === 0) return <Navigate to="/w/today" replace />;
  // 배정이 바뀌면 도움·소리 상태를 새로 시작한다.
  return <LiveStep key={job.assignment_id} job={job} n={n} />;
}
