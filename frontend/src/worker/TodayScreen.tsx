// 오늘 할 일(홈, /w/today, 명세 4.2 + 창업자 결정 7).
// - 선생님이 정한 순서대로 1열. 다음에 할 카드 하나만 강조한다. 다른 카드를 먼저 눌러도 막지 않는다.
// - 다 한 카드는 맨 아래로(서버는 순서를 바꾸지 않는다 — 내리는 일은 화면이 한다).
// - 새 일이 오면 '새 일이 왔어요'를 한 번 소리로 알린다(30초 폴링은 WorkerSession이 한다).
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { IconEnd, IconHistory, IconRetry } from "../ui/icons";
import { COPY } from "./copy";
import { JobCard } from "./JobCard";
import { useBand, useWorkerSession } from "./session";
import { speakText } from "./speech";
import { ConfirmScreen } from "./ui/ConfirmScreen";
import { Illustration } from "./ui/Illustration";
import { PrimaryAction, SecondaryAction } from "./ui/WorkerButton";
import type { TodayJob } from "./workerApi";
import { BottomBar, OfflineMark, TopBar, WorkerScreen } from "./WorkerScreen";

export default function TodayScreen() {
  const navigate = useNavigate();
  const { me, jobs, prefs, progressOf, refresh, logout, unsentNote } = useWorkerSession();
  const { band, offlineMark } = useBand();
  const [confirmEnd, setConfirmEnd] = useState(false);

  // 새 일 알림: 이 화면에 들어올 때 있던 일은 '본 것'으로 치고, 그 뒤에 새로 들어온 일만 알린다.
  const seen = useRef<Set<string> | null>(null);
  useEffect(() => {
    const ids = jobs.map((j) => j.assignment_id);
    if (seen.current == null) {
      seen.current = new Set(ids);
      return;
    }
    const fresh = ids.filter((id) => !seen.current!.has(id));
    ids.forEach((id) => seen.current!.add(id));
    // 소리 자동 재생을 끈 근로자(결정 4)에게는 읽지 않는다(2차 검증: 이것만 설정을 보지 않았다).
    if (fresh.length > 0 && prefs.autoplay_sound) speakText(COPY.band.newJob, { rate: prefs.tts_rate });
  }, [jobs, prefs.tts_rate, prefs.autoplay_sound]);

  const views = jobs.map((job) => ({ job, p: progressOf(job) }));
  const open = views.filter((v) => v.p.status !== "done");
  const finished = views.filter((v) => v.p.status === "done");
  // 다음 카드: 서버 is_next가 있어도, 방금 이 기기에서 끝낸 일(대기열)을 반영해 다시 고른다.
  const nextId = open[0]?.job.assignment_id ?? null;

  if (confirmEnd) {
    return (
      <ConfirmScreen kind="end" speak={prefs.autoplay_sound} ttsRate={prefs.tts_rate}
        note={unsentNote} onStay={() => setConfirmEnd(false)} onLeave={logout} />
    );
  }

  const openJob = (job: TodayJob, done: boolean) =>
    navigate(done ? `/w/history/${job.assignment_id}` : `/w/job/${job.assignment_id}`);

  return (
    <WorkerScreen
      testId="today-screen"
      top={
        <TopBar
          // 좁은 휴대폰에서 인사가 "안녕하..."로 잘리지 않게 두 줄까지(낱말 단위로 넘김), 작은 기기는 20px.
          left={<h1 className="line-clamp-2 text-worker font-bold leading-snug small:text-worker-caption small:font-bold">{COPY.home.greeting(me.display_name)}</h1>}
          center={offlineMark ? <OfflineMark /> : undefined}
          right={
            <SecondaryAction icon={IconEnd} onPress={() => setConfirmEnd(true)} className="!gap-2 !px-3 !text-worker-caption">
              {COPY.btn.end}
            </SecondaryAction>
          }
        />
      }
      band={band}
      bottom={
        <BottomBar>
          <SecondaryAction icon={IconHistory} onPress={() => navigate("/w/history")} className="w-full">
            {COPY.btn.history}
          </SecondaryAction>
        </BottomBar>
      }
      mainClassName="gap-4 py-4 land:py-2"
    >
      {jobs.length === 0 ? (
        <div role="status" className="flex flex-1 flex-col items-center justify-center gap-3 py-6 text-center">
          <Illustration kind="empty" size={200} className="small:size-40" />
          <p className="text-worker-lg font-bold">{COPY.status.empty.title}</p>
          <p className="text-worker text-worker-ink-soft hc:text-black">{COPY.status.empty.body}</p>
          <PrimaryAction onPress={() => void refresh()} icon={IconRetry} className="mt-4 w-full max-w-sm">
            {COPY.btn.refresh}
          </PrimaryAction>
        </div>
      ) : (
        <>
          {/* 가로 휴대폰(낮은 화면)에서는 소제목 줄을 화면에서 빼고(화면낭독기는 읽는다) 카드를 두 칸으로 둔다 — 3차 검증:
              844×390·640×360에서 강조된 다음 카드의 '시작하기 ›'가 아래 막대에 잘리고 두 번째 카드는 보이지 않았다. */}
          <div className="flex items-center justify-between gap-3 land:sr-only">
            <h2 className="text-worker font-bold">{COPY.home.todayCount(jobs.length)}</h2>
            <span aria-hidden="true" className="flex gap-1.5">
              {views.map((v) => (
                <span key={v.job.assignment_id}
                  className={v.p.status === "done" ? "size-3 rounded-full bg-worker-primary" : "size-3 rounded-full border-2 border-worker-line"} />
              ))}
            </span>
          </div>
          <ul className="flex flex-col gap-4 land:grid land:grid-cols-2 land:gap-3">
            {[...open, ...finished].map(({ job, p }) => {
              const done = p.status === "done";
              const statusText = done
                ? COPY.card.done
                : p.status === "in_progress"
                  ? COPY.card.resume(p.resumeIndex + 1)
                  : COPY.card.new;
              return (
                <li key={job.assignment_id}>
                  <JobCard
                    title={job.task_title}
                    steps={job.steps}
                    doneIds={p.doneIds}
                    statusText={statusText}
                    highlight={job.assignment_id === nextId}
                    done={done}
                    onPress={() => openJob(job, done)}
                  />
                </li>
              );
            })}
          </ul>
        </>
      )}
    </WorkerScreen>
  );
}
