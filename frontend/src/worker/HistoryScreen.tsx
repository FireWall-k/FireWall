// 했던 일(/w/history, 명세 4.8). 날짜 묶음('오늘'·'어제'·'11월 6일 목요일', ISO 날짜는 쓰지 않음) + 홈의 JobCard.
// 상태 글: '다 했어요' / '하다가 멈췄어요'. 카드를 누르면 /w/history/:aid — StepPlayer review(도와주세요 없음,
// [이전][다음], 소리 자동 재생 끔).
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import type { HistoryCard } from "../api";
import { mergeStepMedia, useMediaRefresh } from "../media";
import { IconHome, IconRetry } from "../ui/icons";
import { COPY, toWorkerMessage } from "./copy";
import { JobCard } from "./JobCard";
import { useBand, useWorkerSession } from "./session";
import { StepPlayer } from "./StepPlayer";
import { Illustration } from "./ui/Illustration";
import { StatusScreen } from "./ui/StatusScreen";
import { PrimaryAction, SecondaryAction } from "./ui/WorkerButton";
import { workerApi, type TodayJob } from "./workerApi";
import { jobProgress, mergeDoneIds } from "./resume";
import { historyDateLabel } from "./historyDate";
import { TopBar, WorkerScreen } from "./WorkerScreen";

type Load = { kind: "loading" } | { kind: "ok"; items: HistoryCard[] } | { kind: "error"; err: "offline" | "error" };

function localDate(d = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** 오늘 할 일(기기에 받아 둔 것)을 했던 일 카드 모양으로. 인터넷이 끊겨 했던 일을 못 받을 때 쓴다. */
function fromToday(jobs: readonly TodayJob[]): HistoryCard[] {
  return jobs
    .filter((j) => j.steps.length > 0)
    .map((j) => {
      const done = new Set(j.done_step_ids);
      return {
        assignment_id: j.assignment_id,
        task_id: j.task_id,
        task_title: j.task_title,
        assigned_date: localDate(),
        status: j.status === "done" ? "done" : "in_progress",
        steps: j.steps.map((s) => ({ ...s, completed: done.has(s.id) })),
      };
    });
}

/**
 * 서버 기록에 이 기기가 아는 완료(못 보낸·보내는 중인 대기열, 이 화면에서 끝낸 것)를 더한다(3차 검증). 홈이
 * '다 했어요'로 보인 일이 했던 일에서 '하다가 멈췄어요'로 열리지 않게 — 홈(progressOf)과 같은 규칙.
 */
function useMergedCard() {
  const { localDoneIds } = useWorkerSession();
  return useCallback(
    (c: HistoryCard) => {
      const doneIds = mergeDoneIds(
        c.steps,
        c.steps.filter((s) => s.completed).map((s) => s.id),
        localDoneIds(c.assignment_id),
      );
      const done = jobProgress(c.steps, doneIds, c.status === "done").status === "done";
      return { doneIds, done };
    },
    [localDoneIds],
  );
}

function useHistory() {
  const { reportError, jobs } = useWorkerSession();
  const [state, setState] = useState<Load>({ kind: "loading" });
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    let alive = true;
    workerApi
      .history()
      .then((items) => alive && setState({ kind: "ok", items }))
      .catch((e: unknown) => {
        if (!alive) return;
        reportError(e);
        const kind = toWorkerMessage(e);
        // 인터넷이 끊겼으면 받아 둔 오늘 할 일로 보인다(방금 끝낸 일을 다시 볼 수 있게).
        if (kind === "offline" && jobs.length > 0) return setState({ kind: "ok", items: fromToday(jobs) });
        setState({ kind: "error", err: kind === "offline" ? "offline" : "error" });
      });
    return () => {
      alive = false;
    };
    // 오늘 할 일이 바뀌어도 다시 받지 않는다(끊겼을 때 대신 쓰는 값일 뿐).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce, reportError]);
  const onMediaError = useMediaRefresh(async () => {
    const fresh = await workerApi.history();
    setState((cur) => (cur.kind === "ok" ? { kind: "ok", items: mergeStepMedia(cur.items, fresh) } : cur));
  });
  const retry = () => {
    setState({ kind: "loading" });
    setNonce((n) => n + 1);
  };
  return { state, retry, onMediaError };
}

export function HistoryScreen() {
  const navigate = useNavigate();
  const { band } = useBand();
  const { state, retry } = useHistory();
  const merged = useMergedCard();

  if (state.kind === "loading") return <StatusScreen kind="loading" onAction={retry} />;
  if (state.kind === "error") return <StatusScreen kind={state.err} onAction={retry} />;

  const groups: { label: string; items: HistoryCard[] }[] = [];
  for (const c of state.items) {
    const label = historyDateLabel(c.assigned_date);
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.items.push(c);
    else groups.push({ label, items: [c] });
  }

  return (
    <WorkerScreen
      testId="history-screen"
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
      mainClassName="gap-4 py-4"
    >
      {state.items.length === 0 ? (
        <div role="status" className="flex flex-1 flex-col items-center justify-center gap-4 text-center">
          <Illustration kind="empty" size={200} className="small:size-40" />
          <p className="text-worker-lg font-bold">{COPY.history.empty}</p>
          <PrimaryAction icon={IconHome} onPress={() => navigate("/w/today")} className="w-full max-w-sm">
            {COPY.btn.home}
          </PrimaryAction>
        </div>
      ) : (
        groups.map((g) => (
          <section key={g.label} className="flex flex-col gap-3">
            <h2 className="text-worker font-bold">{g.label}</h2>
            {g.items.map((c) => {
              const { doneIds, done } = merged(c);
              const statusText = done ? COPY.card.done : doneIds.size > 0 ? COPY.card.stopped : COPY.card.new;
              return (
                <JobCard
                  key={c.assignment_id}
                  title={c.task_title}
                  steps={c.steps}
                  doneIds={doneIds}
                  statusText={statusText}
                  done={done}
                  onPress={() => navigate(`/w/history/${c.assignment_id}`)}
                />
              );
            })}
          </section>
        ))
      )}
    </WorkerScreen>
  );
}

export function HistoryDetailScreen() {
  const { aid } = useParams();
  const navigate = useNavigate();
  const { prefs, online } = useWorkerSession();
  const { band } = useBand();
  const { state, retry, onMediaError } = useHistory();
  const merged = useMergedCard();
  const [index, setIndex] = useState(0);

  if (state.kind === "loading") return <StatusScreen kind="loading" onAction={retry} />;
  if (state.kind === "error") return <StatusScreen kind={state.err} onAction={retry} />;
  const card = state.items.find((c) => c.assignment_id === aid);
  if (!card || card.steps.length === 0) {
    return (
      <WorkerScreen top={<TopBar />} mainClassName="items-center gap-4 text-center [justify-content:safe_center]">
        <p className="text-worker-lg font-bold">{COPY.history.empty}</p>
        <PrimaryAction icon={IconRetry} onPress={() => navigate("/w/history")} className="w-full max-w-sm">
          {COPY.btn.history}
        </PrimaryAction>
      </WorkerScreen>
    );
  }
  const i = Math.min(index, card.steps.length - 1);
  const { doneIds } = merged(card);
  return (
    <StepPlayer
      mode="review"
      title={card.task_title}
      steps={card.steps}
      index={i}
      doneIds={doneIds}
      prefs={prefs}
      band={band}
      offline={!online}
      onPrev={() => setIndex(Math.max(0, i - 1))}
      onNext={() => setIndex(Math.min(card.steps.length - 1, i + 1))}
      onExit={() => navigate("/w/history")}
      onMediaError={onMediaError}
    />
  );
}
