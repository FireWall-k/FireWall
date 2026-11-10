// 로그인한 근로자의 화면 상태 한 벌(홈·직무 시작·단계·완료 화면이 같이 쓴다).
// - 내 정보·화면 설정(GET /api/worker/me)과 오늘 할 일(include_done=true)을 불러온다.
// - 오늘 할 일은 30초마다, 화면이 다시 보일 때 조용히 다시 받는다(기기 연결 신호도 겸함, 명세 4.2).
// - 완료 기록은 대기열(outbox.ts)로 보낸다: 바로, 다시 연결될 때(online), 30초마다.
// - 인터넷이 끊겨도 받아 둔 일은 할 수 있게 마지막 응답을 기기에 둔다(같은 날·같은 로그인일 때만 쓴다).
// - 401(로그인 풀림)이면 '다시 들어와 주세요' 화면. 대기열은 지우지 않는다(다시 들어오면 보낸다).
// - 모든 호출은 세션을 연 토큰(token)으로 보낸다(3차 검증). 저장된 로그인은 기기에 하나라, 앞사람이 [끝내기]를 누른 뒤
//   (대기열은 계속 보낸다) 뒷사람이 들어오거나 다른 탭에서 다른 근로자가 들어오면, 예전에는 앞사람 기록이 뒷사람
//   토큰으로 가 404로 버려졌고, 오늘 할 일도 뒷사람 것이 앞사람 화면·기기 사본에 들어갔다.
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { getAuth, type Step } from "../api";
import { NetworkError } from "../apiErrors";
import { mergeStepMedia, useMediaRefresh } from "../media";
import { COPY, toWorkerMessage } from "./copy";
import { getOutbox, type Outbox } from "./outbox";
import { preloadPictures } from "./preload";
import { jobProgress, mergeDoneIds } from "./resume";
import { LOGOUT_FLUSH_WAIT_MS, OUTBOX_RETRY_MS, SYNC_NOTICE_MS, SessionContext, TODAY_POLL_MS, type StepCompletion, type WorkerSessionValue } from "./session";
import { StatusScreen } from "./ui/StatusScreen";
import { cachedJobs, cachedMe, ME_CACHE_KEY, noteSentInTodayCache, writeJson, writeTodayCache } from "./todayCache";
import { workerApi, type TodayJob, type WorkerMe } from "./workerApi";

type Fatal = "expired" | "offline" | "error" | null;

export function WorkerSession({ token, onLogout, children }: { token: string; onLogout: () => void; children: ReactNode }) {
  const navigate = useNavigate();
  const [me, setMe] = useState<WorkerMe | null>(null);
  const [jobs, setJobs] = useState<TodayJob[] | null>(null);
  const [fatal, setFatal] = useState<Fatal>(null);
  const [online, setOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine !== false));
  const [synced, setSynced] = useState(false);
  const [sessionDone, setSessionDone] = useState<Record<string, string[]>>({});
  const [, setOutboxTick] = useState(0);
  const backlog = useRef(false);
  const meRef = useRef<WorkerMe | null>(null);

  const outbox: Outbox | null = useMemo(() => (me ? getOutbox(me.id) : null), [me]);

  const noteError = useCallback((e: unknown) => {
    const kind = toWorkerMessage(e);
    if (kind === "expired") setFatal("expired");
    else if (kind === "offline") setOnline(false);
  }, []);

  /**
   * 저장된 로그인이 다른 토큰으로 바뀌었는지(다른 탭·다음 근로자가 들어왔으면 App이 곧 세션을 새로 만든다).
   * 4차 검증: 예전에는 '저장된 토큰 === 이 세션 토큰'을 봤는데, 이 세션의 요청이 401을 받으면 toError가 저장된
   * 로그인을 먼저 지워(null) 늘 '내 것 아님'이 됐다. 그래서 '다시 들어와 주세요'가 뜨지 않고 오늘 할 일 다시 받기도
   * 멈춘 채, 근로자는 기록이 하나도 안 가는 일을 계속했다. 지워진 것(null)은 이 세션이 풀린 것으로 본다.
   */
  const replaced = useCallback(() => {
    const now = getAuth()?.token;
    return now != null && now !== token;
  }, [token]);

  const load = useCallback(async () => {
    let m: WorkerMe | null = meRef.current;
    try {
      m = await workerApi.me(token);
      writeJson(ME_CACHE_KEY, { token, me: m });
      setOnline(true);
    } catch (e) {
      const kind = toWorkerMessage(e);
      if (kind === "expired") return setFatal("expired");
      m = m ?? cachedMe(token);
      if (!m) return setFatal(kind === "offline" ? "offline" : "error");
      if (kind === "offline") setOnline(false);
    }
    meRef.current = m;
    setMe(m);
    try {
      const list = writeTodayCache(m.id, await workerApi.today(token));
      setJobs(list);
      setOnline(true);
    } catch (e) {
      const kind = toWorkerMessage(e);
      if (kind === "expired") return setFatal("expired");
      const cached = cachedJobs(m.id);
      if (cached) {
        setJobs((cur) => cur ?? cached);
        if (kind === "offline") setOnline(false);
        return;
      }
      setFatal(kind === "offline" ? "offline" : "error");
    }
  }, [token]);

  useEffect(() => {
    // 첫 화면을 그린 뒤 불러온다(effect 안에서 바로 상태를 바꾸지 않게).
    const t = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(t);
  }, [load]);

  const retry = useCallback(() => {
    setFatal(null);
    void load();
  }, [load]);

  // 조용히 다시 받기(폴링·화면 복귀·다시 연결). 실패해도 지금 화면을 그대로 둔다.
  const refresh = useCallback(async () => {
    const m = meRef.current;
    if (!m || replaced()) return;
    try {
      const list = writeTodayCache(m.id, await workerApi.today(token));
      setJobs(list);
      setOnline(true);
    } catch (e) {
      noteError(e);
    }
  }, [noteError, replaced, token]);

  // 대기열 보내기.
  const flush = useCallback(async () => {
    if (!outbox || outbox.size === 0) return;
    const workerId = outbox.workerId;
    const r = await outbox.flush((body) =>
      // 대기열 주인(이 세션)의 토큰으로 보낸다. 화면을 떠난 뒤에도 이어지는 보내기도 같은 토큰을 쓴다.
      workerApi.logStep(body, undefined, token).then(
        (res) => {
          if (body.completed) noteSentInTodayCache(workerId, body.assignment_id, body.step_id);
          return res;
        },
        (e: unknown) => {
          // 끊김(NetworkError)과 답 없음(12초 뒤 끊은 AbortError) 모두 '인터넷 끊김'으로 보인다.
          if (e instanceof NetworkError || (e instanceof DOMException && e.name === "AbortError")) setOnline(false);
          throw e;
        },
      ),
    );
    if (r.expired) {
      if (!replaced()) setFatal("expired");
      return;
    }
    if (r.failed) {
      backlog.current = true;
      return;
    }
    if (r.sent > 0) setOnline(true);
    if (r.remaining === 0 && backlog.current) {
      backlog.current = false;
      setSynced(true);
    }
  }, [outbox, token, replaced]);

  useEffect(() => {
    if (!synced) return;
    const t = window.setTimeout(() => setSynced(false), SYNC_NOTICE_MS);
    return () => window.clearTimeout(t);
  }, [synced]);

  // 대기열이 바뀌면 다시 그린다(홈 카드가 '다 했어요'를 대기열로도 판단한다).
  useEffect(() => {
    if (!outbox) return;
    const unsub = outbox.subscribe(() => setOutboxTick((n) => n + 1));
    // 지난번에 못 보낸 기록이 있으면 들어오자마자 보낸다.
    const t = window.setTimeout(() => void flush(), 0);
    return () => {
      unsub();
      window.clearTimeout(t);
    };
  }, [outbox, flush]);

  // 30초마다: 오늘 할 일 다시 받기 + 대기열 다시 보내기. 화면이 다시 보이면 바로.
  useEffect(() => {
    if (!me) return;
    const tick = () => {
      if (document.visibilityState === "hidden") return;
      void refresh();
      void flush();
    };
    const poll = window.setInterval(tick, Math.min(TODAY_POLL_MS, OUTBOX_RETRY_MS));
    const onVisible = () => {
      if (document.visibilityState === "visible") tick();
      // 화면을 잠그거나 탭을 숨기기 직전에도 남은 기록을 한 번 보낸다(숨은 동안은 30초 타이머가 돌지 않는다).
      else void flush();
    };
    const onPageHide = () => void flush();
    const onOnline = () => {
      setOnline(true);
      void flush();
      void refresh();
    };
    const onOffline = () => setOnline(false);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("pagehide", onPageHide);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.clearInterval(poll);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("pagehide", onPageHide);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, [me, refresh, flush]);

  // 끝나지 않은 일의 그림을 미리 받아 둔다(일하는 중 인터넷이 끊겨도 다음 단계 그림이 보이게, preload.ts).
  useEffect(() => {
    for (const j of jobs ?? []) if (j.status !== "done") preloadPictures(j.steps);
  }, [jobs]);

  const onMediaError = useMediaRefresh(async () => {
    const fresh = await workerApi.today(token);
    setJobs((cur) => (cur ? mergeStepMedia(cur, fresh) : cur));
  });

  const progressOf = useCallback(
    (job: TodayJob) => {
      const pending = (outbox?.list() ?? []).filter((x) => x.assignment_id === job.assignment_id).map((x) => x.step_id);
      const ids = mergeDoneIds(job.steps, job.done_step_ids, pending, sessionDone[job.assignment_id] ?? []);
      return jobProgress(job.steps, ids, job.status === "done");
    },
    // outbox 내용은 subscribe로 다시 그릴 때 새로 읽는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [outbox, sessionDone, outbox?.size],
  );

  const localDoneIds = useCallback(
    (assignmentId: string) => {
      const pending = (outbox?.list() ?? []).filter((x) => x.assignment_id === assignmentId && x.completed);
      return [...pending.map((x) => x.step_id), ...(sessionDone[assignmentId] ?? [])];
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [outbox, sessionDone, outbox?.size],
  );

  const completeStep = useCallback(
    (job: TodayJob, step: Step, info: StepCompletion) => {
      setSessionDone((cur) => {
        const prev = cur[job.assignment_id] ?? [];
        return prev.includes(step.id) ? cur : { ...cur, [job.assignment_id]: [...prev, step.id] };
      });
      if (!outbox) return;
      outbox.put({
        assignment_id: job.assignment_id,
        step_id: step.id,
        duration_sec: Math.round(info.durationSec * 10) / 10,
        replay_count: info.replayCount,
        stuck: info.stuck,
        prev_count: info.prevCount ?? 0,
        completed: true,
      });
      void flush();
    },
    [outbox, flush],
  );

  // 2차 검증: 예전에는 못 보낸 기록을 보내 보지도 않고 바로 나갔다. 같은 근로자가 이 기기로 다시 들어와야만 보내져,
  // 공용 태블릿·다른 기기를 쓰는 날에는 사업주가 끝난 일을 못 봤다. 나가기 전에 한 번(최대 3초) 보내 본다.
  const leaving = useRef(false);
  const logout = useCallback(() => {
    if (leaving.current) return;
    leaving.current = true;
    const finish = () => {
      onLogout();
      navigate("/w", { replace: true });
    };
    if (!outbox || outbox.size === 0) return finish();
    let done = false;
    const go = () => {
      if (done) return;
      done = true;
      finish();
    };
    window.setTimeout(go, LOGOUT_FLUSH_WAIT_MS);
    void flush().catch(() => {}).finally(go);
  }, [onLogout, navigate, outbox, flush]);

  if (fatal === "expired") return <StatusScreen kind="expired" speak onAction={logout} />;
  if (fatal === "offline") return <StatusScreen kind="offline" speak onAction={retry} />;
  if (fatal === "error") return <StatusScreen kind="error" speak onAction={retry} />;
  if (!me || !jobs) return <StatusScreen kind="loading" onAction={retry} />;

  const value: WorkerSessionValue = {
    me,
    prefs: me.a11y_prefs,
    jobs,
    online,
    synced,
    pendingCount: outbox?.size ?? 0,
    unsentNote: (outbox?.size ?? 0) > 0 && !online ? COPY.confirm.unsent : null,
    refresh,
    progressOf,
    localDoneIds,
    completeStep,
    onMediaError,
    logout,
    reportError: noteError,
  };

  const prefs = me.a11y_prefs;
  return (
    <SessionContext.Provider value={value}>
      <div
        data-contrast={prefs.contrast}
        data-hand={prefs.hand}
        data-font={prefs.font_size}
        className="contents"
      >
        {children}
      </div>
    </SessionContext.Provider>
  );
}
