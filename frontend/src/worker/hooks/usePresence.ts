// (2c) 근로자 기기 신호(contract §5.2 presence). 사업주 홈의 '지금 단계'·막힘 의심·연결 끊김 판정에 쓴다.
// - 언제 보내나: 단계를 열 때, 다시 듣기·이전 수가 바뀔 때, 그리고 같은 단계에 머무는 동안 30초마다(연결 신호).
// - 오프라인이거나 화면이 숨어 있으면 보내지 않는다. 다시 보이거나 연결되면 바로 한 번 보낸다.
// - 실패는 버린다(화면에 아무것도 띄우지 않음, 오프라인 대기열에 넣지 않음). 서버가 같은 내용은 15초 안에 다시 쓰지 않는다.
// - 시각은 기기 시계로 적어 보낸다(단계를 연 시각·보낸 시각). 서버는 둘의 차이만 쓴다 — 기기 시계가 틀려도 머문 시간은 맞다.
// 측정 이벤트(step_view·step_replay·step_prev·help_open)는 trackWorkerEvent로 모아 2초 뒤 한 번에 보낸다(실패는 버림).
import { useCallback, useEffect, useRef } from "react";
import { signalApi, type PresenceBody, type WorkerEvent } from "../workerApi";

export const PRESENCE_HEARTBEAT_MS = 30_000;
export const WORKER_EVENT_FLUSH_MS = 2_000;

export interface PresenceSignal {
  stepId: string | null;
  replayCount: number;
  prevCount: number;
}

export interface PresenceOptions {
  assignmentId: string;
  online: boolean;
  /** 시험용으로 바꿀 수 있다. */
  send?: (body: PresenceBody) => Promise<unknown>;
}

function hidden(): boolean {
  return typeof document !== "undefined" && document.visibilityState === "hidden";
}

/** 신호를 받는 함수(report)를 돌려준다. StepPlayer의 onSignal에 그대로 넘긴다. */
export function usePresence({ assignmentId, online, send = signalApi.presence }: PresenceOptions) {
  const cur = useRef<{ sig: PresenceSignal; startedAt: string } | null>(null);
  const onlineRef = useRef(online);
  const sendRef = useRef(send);
  useEffect(() => {
    sendRef.current = send;
  });

  const push = useCallback(() => {
    const c = cur.current;
    if (!c || !onlineRef.current || hidden()) return;
    const body: PresenceBody = {
      assignment_id: assignmentId,
      step_id: c.sig.stepId,
      step_started_at: c.startedAt,
      replay_count: c.sig.replayCount,
      prev_count: c.sig.prevCount,
      client_sent_at: new Date().toISOString(),
    };
    try {
      void Promise.resolve(sendRef.current(body)).catch(() => undefined);
    } catch {
      /* 보내기 실패는 버린다 */
    }
  }, [assignmentId]);

  const report = useCallback(
    (sig: PresenceSignal) => {
      const prev = cur.current;
      const sameStep = prev && prev.sig.stepId === sig.stepId;
      cur.current = { sig, startedAt: sameStep ? prev.startedAt : new Date().toISOString() };
      push();
    },
    [push],
  );

  // 연결이 돌아오면 바로 한 번.
  useEffect(() => {
    const was = onlineRef.current;
    onlineRef.current = online;
    if (online && !was) push();
  }, [online, push]);

  // 머무는 동안 30초마다 + 다시 보이면 바로 한 번.
  useEffect(() => {
    const t = window.setInterval(push, PRESENCE_HEARTBEAT_MS);
    const onVis = () => {
      if (!hidden()) push();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(t);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [push]);

  return report;
}

// --- 측정 이벤트(근로자) ---

let queue: WorkerEvent[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;

export function flushWorkerEvents(send: (e: WorkerEvent[]) => Promise<unknown> = signalApi.events): void {
  if (timer) clearTimeout(timer);
  timer = null;
  if (queue.length === 0) return;
  const batch = queue.slice(0, 50);
  queue = queue.slice(50);
  try {
    void Promise.resolve(send(batch)).catch(() => undefined);
  } catch {
    /* 버린다 */
  }
  if (queue.length > 0) flushWorkerEvents(send);
}

/** 이벤트 하나를 모은다. 오프라인이면 버린다(대기열에 넣지 않음, contract §5.2). */
export function trackWorkerEvent(
  name: WorkerEvent["name"],
  extra: { task_id?: string | null; step_id?: string | null },
  online: boolean,
): void {
  if (!online) return;
  queue.push({ name, ...extra, at: new Date().toISOString() });
  if (!timer) timer = setTimeout(() => flushWorkerEvents(), WORKER_EVENT_FLUSH_MS);
}

/** 시험용. */
export function resetWorkerEventsForTest(): void {
  queue = [];
  if (timer) clearTimeout(timer);
  timer = null;
}
