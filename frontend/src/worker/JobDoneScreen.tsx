// 직무 완료 / 오늘 일 끝(/w/job/:aid/done, 명세 4.6). 마지막 기록을 서버가 아직 못 받았어도(오프라인) 이 화면은
// 그대로 보이고, 기록은 대기열이 다시 연결될 때 보낸다.
// - 다음 일이 있으면: 칭찬 + 다음 일 미리 보기 + [방금 일 다시 보기](보조) / [다음 일 하기](주).
// - 모두 끝났으면: '오늘 일을 다 했어요' / '선생님께 알려 주세요.' + [했던 일 보기](보조) / [끝내기](주).
// 칭찬 '조용히'(근로자 설정)면 그림·소리 없이 문장만.
import { useEffect, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { IconEnd, IconHistory, IconHome, IconNext } from "../ui/icons";
import { cn } from "../cn";
import { COPY } from "./copy";
import { Thumb } from "./JobCard";
import { useBand, useWorkerSession } from "./session";
import { speakText } from "./speech";
import { ConfirmScreen } from "./ui/ConfirmScreen";
import { Illustration } from "./ui/Illustration";
import { PrimaryAction, SecondaryAction } from "./ui/WorkerButton";
import { BottomBar, TopBar, WorkerScreen } from "./WorkerScreen";

// 아래 막대 두 버튼. 가로 휴대폰(land)에서는 나란히 둔다 — 주 버튼은 제 폭을 지키고(줄지 않음), 보조 버튼이 남는 폭을
// 쓴다. 남는 폭이 모자라면(글자 130%) 보조 버튼 글자만 낱말 단위로 두 줄이 된다. 4차 검증: 둘 다 w-full이라 줄지 못해
// 640×360 130%에서 [다음 일 하기]가 화면 오른쪽 밖으로 잘렸다.
const SECONDARY_CLASS = cn("w-full", "land:min-w-0 land:flex-1 land:whitespace-normal land:break-keep land:!px-3 land:leading-tight");
const PRIMARY_CLASS = cn("w-full", "land:w-auto land:flex-none land:!px-4");

export default function JobDoneScreen() {
  const { aid } = useParams();
  const navigate = useNavigate();
  const { jobs, prefs, progressOf, logout, unsentNote } = useWorkerSession();
  const { band } = useBand();
  const [confirmEnd, setConfirmEnd] = useState(false);
  const job = jobs.find((j) => j.assignment_id === aid);
  const next = jobs.find((j) => j.assignment_id !== aid && progressOf(j).status !== "done") ?? null;
  const quiet = prefs.praise === "quiet";

  const title = job ? COPY.done.title(job.task_title) : "";
  // 칭찬을 먼저 읽는다(명세 4.6, 2026-11-09 창업자 결정: '정말 잘했어요'가 맨 위·가장 크게·먼저).
  const spoken = next
    ? `${COPY.done.praise}. ${title}.`
    : `${COPY.done.praise}. ${COPY.allDone.title}. ${COPY.allDone.body}`;
  useEffect(() => {
    if (job && !quiet && prefs.autoplay_sound) speakText(spoken, { rate: prefs.tts_rate });
    // 들어올 때 한 번만 읽는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aid]);

  if (!job) return <Navigate to="/w/today" replace />;
  if (confirmEnd) {
    return (
      <ConfirmScreen kind="end" speak={prefs.autoplay_sound} ttsRate={prefs.tts_rate}
        note={unsentNote} onStay={() => setConfirmEnd(false)} onLeave={logout} />
    );
  }

  return (
    <WorkerScreen
      testId="job-done-screen"
      top={
        <TopBar
          left={
            <SecondaryAction icon={IconHome} onPress={() => navigate("/w/today")} className="!gap-2 !px-3">
              {COPY.btn.home}
            </SecondaryAction>
          }
        />
      }
      band={band}
      bottom={
        <BottomBar stacked>
          {next ? (
            <>
              <SecondaryAction icon={IconHistory} onPress={() => navigate(`/w/history/${job.assignment_id}`)} className={SECONDARY_CLASS}>
                {COPY.btn.replayJob}
              </SecondaryAction>
              <PrimaryAction icon={IconNext} onPress={() => navigate(`/w/job/${next.assignment_id}`)} className={PRIMARY_CLASS}>
                {COPY.btn.nextJob}
              </PrimaryAction>
            </>
          ) : (
            <>
              <SecondaryAction icon={IconHistory} onPress={() => navigate("/w/history")} className={SECONDARY_CLASS}>
                {COPY.btn.history}
              </SecondaryAction>
              <PrimaryAction icon={IconEnd} onPress={() => setConfirmEnd(true)} className={PRIMARY_CLASS}>
                {COPY.btn.end}
              </PrimaryAction>
            </>
          )}
        </BottomBar>
      }
      // safe center: 내용이 칸보다 크면 위에서부터 스크롤한다(그냥 center는 그림 머리가 위 띠 밑으로 잘렸다).
      mainClassName="items-center gap-3 py-4 text-center [justify-content:safe_center] small:gap-2 small:py-2"
    >
      {/* 명세 4.6: '정말 잘했어요'가 맨 위, 가장 크게(32px 굵게), 근로자 초록. 그 아래 그림, 그 아래 무엇을 다 했는지.
          모두 끝난 날도 같다. 칭찬 '조용히'면 그림 없이 글만. */}
      <div role="status" className="flex flex-col items-center gap-2">
        {/* primary(#1F6340)는 이 바탕에서 6.82:1이라 7:1 목표(명세 8.1)에 못 미친다 — 더 진한 pressed 초록. */}
        <p data-testid="done-praise" className="text-worker-lg font-bold text-worker-primary-pressed hc:text-black">
          {COPY.done.praise}
        </p>
        {!quiet && (
          <Illustration kind="praise" size={240}
            className={cn(
              "max-h-[30dvh] max-w-full land:max-h-[26dvh]",
              // 다음 일이 있으면 미리 보기 카드(다음 일 이름)가 늘 보여야 한다(2차 검증: 작은 휴대폰에서 아래 막대에
              // 가렸다). 작은 휴대폰은 그림을 더 줄이고, 낮은 화면(620 이하)은 그림을 빼고 글만 둔다.
              next ? "small:max-h-[14dvh] [@media(max-height:620px)]:hidden" : "small:max-h-[24dvh]",
            )} />
        )}
        {next ? (
          <h1 className="text-worker-title font-bold">{title}</h1>
        ) : (
          <>
            <h1 className="text-worker-title font-bold">{COPY.allDone.title}</h1>
            <p className="text-worker text-worker-ink-soft hc:text-black">{COPY.allDone.body}</p>
          </>
        )}
      </div>
      {next && (
        <div data-testid="next-preview" className="mt-2 flex w-full max-w-md items-center gap-4 rounded-worker-card border-2 border-worker-line-soft bg-worker-card p-3 text-left shadow-worker-card small:mt-0 small:gap-3 small:p-2">
          <Thumb url={next.steps[0]?.symbol_url} size={96} />
          <p className="min-w-0 flex-1 text-worker font-semibold">{COPY.done.nextPreview(next.task_title)}</p>
        </div>
      )}
    </WorkerScreen>
  );
}
