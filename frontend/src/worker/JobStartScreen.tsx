// 직무 시작(/w/job/:aid, 명세 4.3). 대표 그림·'컵 씻기를 시작해요'·'4단계예요'·진행 점 + [시작하기].
// [시작하기] 누름이 브라우저의 소리 잠금을 풀고 화면 꺼짐 방지를 켠다(명세 3.5-3).
// 하다 만 일이면 '3단계부터 이어서 해요' + [이어서 하기](주), 그 위 24px에 [처음부터 하기](보조).
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { IconExit, IconNext, IconPlay, IconRetry } from "../ui/icons";
import { COPY } from "./copy";
import { acquireWakeLock } from "./hooks/useWakeLock";
import { Thumb } from "./JobCard";
import { ProgressDots } from "./ProgressDots";
import { useBand, useWorkerSession } from "./session";
import { unlockAudio } from "./sound";
import { PrimaryAction, SecondaryAction } from "./ui/WorkerButton";
import { BottomBar, TopBar, WorkerScreen } from "./WorkerScreen";

export default function JobStartScreen() {
  const { aid } = useParams();
  const navigate = useNavigate();
  const { jobs, progressOf } = useWorkerSession();
  const { band } = useBand();
  const job = jobs.find((j) => j.assignment_id === aid);
  if (!job || job.steps.length === 0) return <Navigate to="/w/today" replace />;

  const p = progressOf(job);
  const resuming = p.status === "in_progress" && p.resumeIndex < job.steps.length;

  const go = (n: number) => {
    // 이 누름 안에서 소리·화면 꺼짐 방지를 푼다(브라우저는 사용자 누름이 있어야 허락한다).
    unlockAudio();
    void acquireWakeLock();
    navigate(`/w/job/${job.assignment_id}/step/${n}`);
  };

  return (
    <WorkerScreen
      testId="job-start-screen"
      top={
        <TopBar
          left={
            <SecondaryAction icon={IconExit} onPress={() => navigate("/w/today")} className="!gap-2 !px-3">
              {COPY.btn.exit}
            </SecondaryAction>
          }
        />
      }
      band={band}
      bottom={
        <BottomBar stacked={resuming}>
          {resuming ? (
            <>
              <SecondaryAction icon={IconRetry} onPress={() => go(1)} className="w-full">
                {COPY.btn.restart}
              </SecondaryAction>
              <PrimaryAction icon={IconNext} onPress={() => go(p.resumeIndex + 1)} className="w-full">
                {COPY.btn.resume}
              </PrimaryAction>
            </>
          ) : (
            <PrimaryAction icon={IconPlay} onPress={() => go(1)} className="w-full">
              {COPY.btn.start}
            </PrimaryAction>
          )}
        </BottomBar>
      }
      // safe center: 내용이 칸보다 크면 가운데 맞춤을 풀고 위에서부터 스크롤한다(그냥 center는 위가 잘려
      // 스크롤로도 못 본다, 1차 검증). 대표 그림은 정사각형 그대로 남는 높이에 맞춰 준다(가로 휴대폰에서
      // 300×156 빈 띠가 생기던 문제).
      mainClassName="items-center gap-4 py-4 text-center [justify-content:safe_center] small:gap-2 small:py-2"
    >
      <Thumb url={job.steps[0]?.symbol_url} size={300}
        className="aspect-square max-h-[40dvh] max-w-full !w-auto !rounded-worker-pic object-contain land:max-h-[34dvh] tablet:!h-[480px] tablet:max-h-[45dvh]" />
      <h1 className="text-worker-lg font-bold">{COPY.start.title(job.task_title)}</h1>
      <p className="text-worker text-worker-ink-soft hc:text-black">
        {resuming ? COPY.card.resume(p.resumeIndex + 1) : COPY.start.stepCount(job.steps.length)}
      </p>
      <ProgressDots total={job.steps.length} current={-1} done={(i) => p.doneIds.has(job.steps[i].id)} className="justify-center" />
    </WorkerScreen>
  );
}
