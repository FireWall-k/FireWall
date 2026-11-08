// 로그인한 근로자의 화면 상태 한 벌(홈·직무 시작·단계·완료 화면이 같이 쓴다).
// - 내 정보·화면 설정(GET /api/worker/me)과 오늘 할 일(include_done=true)을 불러온다.
// - 오늘 할 일은 30초마다, 화면이 다시 보일 때 조용히 다시 받는다(기기 연결 신호도 겸함, 명세 4.2).
// - 완료 기록은 대기열(outbox.ts)로 보낸다: 바로, 다시 연결될 때(online), 30초마다.
// - 인터넷이 끊겨도 받아 둔 일은 할 수 있게 마지막 응답을 기기에 둔다(같은 날·같은 로그인일 때만 쓴다).
// - 401(로그인 풀림)이면 '다시 들어와 주세요' 화면. 대기열은 지우지 않는다(다시 들어오면 보낸다).
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { getAuth, type Step } from "../api";
import { NetworkError } from "../apiErrors";
import { mergeStepMedia, useMediaRefresh } from "../media";
import { toWorkerMessage } from "./copy";
import { getOutbox, type Outbox } from "./outbox";
import { jobProgress, mergeDoneIds } from "./resume";
import { OUTBOX_RETRY_MS, SYNC_NOTICE_MS, SessionContext, TODAY_POLL_MS, type StepCompletion, type WorkerSessionValue } from "./session";
import { StatusScreen } from "./ui/StatusScreen";
import { normalizePrefs, workerApi, type TodayJob, type WorkerMe } from "./workerApi";

// --- 기기에 둔 마지막 응답(오프라인용) ---
const ME_CACHE_KEY = "jobcard_worker_me_v1";
const TODAY_CACHE_PREFIX = "jobcard_today_v1:";

function localDay(d = new Date()): string {
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

function readJson<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function writeJson(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* 저장 못 하면 오프라인에서 새로 받을 수 없을 뿐 */
  }
}

function cachedMe(token: string | undefined): WorkerMe | null {
  const c = readJson<{ token: string; me: WorkerMe }>(ME_CACHE_KEY);
  return c && token && c.token === token ? { ...c.me, a11y_prefs: normalizePrefs(c.me.a11y_prefs) } : null;
}

function cachedJobs(workerId: string): TodayJob[] | null {
  const c = readJson<{ day: string; jobs: TodayJob[] }>(`${TODAY_CACHE_PREFIX}${workerId}`);
  return c && c.day === localDay() && Array.isArray(c.jobs) ? c.jobs : null;
}

type Fatal = "expired" | "offline" | "error" | null;

export function WorkerSession({ onLogout, children }: { onLogout: () => void; children: ReactNode }) {
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

  const load = useCallback(async () => {
    const token = getAuth()?.token;
    let m: WorkerMe | null = meRef.current;
    try {
      m = await workerApi.me();
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
      const list = await workerApi.today();
      writeJson(`${TODAY_CACHE_PREFIX}${m.id}`, { day: localDay(), jobs: list });
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
  }, []);

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
    if (!m) return;
    try {
      const list = await workerApi.today();
      writeJson(`${TODAY_CACHE_PREFIX}${m.id}`, { day: localDay(), jobs: list });
      setJobs(list);
      setOnline(true);
    } catch (e) {
      noteError(e);
    }
  }, [noteError]);

  // 대기열 보내기.
  const flush = useCallback(async () => {
    if (!outbox || outbox.size === 0) return;
    const r = await outbox.flush((body) =>
      workerApi.logStep(body).catch((e: unknown) => {
        if (e instanceof NetworkError) setOnline(false);
        throw e;
      }),
    );
    if (r.expired) {
      setFatal("expired");
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
  }, [outbox]);

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
    };
    const onOnline = () => {
      setOnline(true);
      void flush();
      void refresh();
    };
    const onOffline = () => setOnline(false);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.clearInterval(poll);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, [me, refresh, flush]);

  const onMediaError = useMediaRefresh(async () => {
    const fresh = await workerApi.today();
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
        completed: true,
      });
      void flush();
    },
    [outbox, flush],
  );

  const logout = useCallback(() => {
    onLogout();
    navigate("/w", { replace: true });
  }, [onLogout, navigate]);

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
    refresh,
    progressOf,
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
