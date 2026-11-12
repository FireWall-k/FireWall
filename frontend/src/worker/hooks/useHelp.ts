// 도움 요청(명세 4.5, contract §7). 상태를 사실대로 보여 준다:
//   idle → sending('부르는 중') → sent('불렀어요', [취소]) → acked('선생님이 확인했어요', 3초 뒤 닫힘)
//                              ↘ failed('아직 못 불렀어요. 손을 들어 선생님을 불러요.', [다시 부르기])
// - 도움 요청은 대기열에 넣지 않는다: 닿지 않으면 사람에게 직접 청하라고 알린다(늦게 닿은 요청은 쓸모없다).
// - 'sent'인 동안 5초마다 상태를 본다(숨은 탭에서는 멈춤). 사업주가 확인·해결하면 acked.
//   근로자가 누르지 않은 '취소됨'이 보이면(다른 기기 등) 말없이 닫지 않고 '아직 못 불렀어요'로 알린다(2차 검증).
//   이 화면에서 [다 했어요]를 누르지 않았는데 '단계를 끝내서 닫음'이 보여도 같다(늦게 닿은 옛 완료 기록, 4차 검증 2회).
// - [다 했어요]를 누르면 서버가 그 단계의 요청을 '해결됨'으로 닫으므로 띠도 닫는다(markStepDone).
//   서버와 같은 규칙으로, 다른 단계에서 부른 요청은 그대로 둔다(3차 검증: 3단계에서 부르고 [이전]으로 2단계를 끝내면
//   띠만 사라지고 서버에는 열린 요청이 남아, 선생님이 확인해도 근로자는 '선생님이 확인했어요'를 못 봤다).
// - 화면에 들어오면 열려 있던 요청(today 카드의 active_help, 또는 이 탭이 기억한 요청)을 서버에 한 번 물어본 뒤에
//   띠를 보인다(2차 검증: 30초 묵은 목록으로 띠를 그려, 취소한 요청이 '불렀어요'로 되살아나거나 부른 요청이 안 보였다).
//   '선생님이 확인했어요'는 이 기기에서 이미 보인 확인이면 다시 보이지 않는다(sessionStorage).
// - 부르기 요청은 8초 안에 답이 없으면 끊고 '아직 못 불렀어요'를 보인다(와이파이는 잡혔는데 밖으로 안 나가는 경우).
//   [다시 부르기]는 같은 client_request_id를 다시 쓴다 — 늦게라도 닿은 첫 요청과 두 건으로 세지 않게.
// - 답을 못 받은 누름은 키를 기억해 두었다가 [다 했어요] 때 키로 닫는다(cancel-by-client). 서버에 늦게 닿아
//   근로자는 못 보는 '열린 요청'이 사업주 화면에만 남지 않게 한다(2차 검증).
// - [취소] 직후 다시 부르면, 취소가 서버에 닿은 뒤에 새로 부른다(2차 검증: 새 누름이 먼저 닿으면 곧 취소될 옛 요청을
//   돌려받아 '불렀어요'를 보였는데 사업주 화면에는 아무것도 없었다).
import { useCallback, useEffect, useRef, useState } from "react";
import type { HelpOut } from "../../api";
import { newId, workerApi, type ActiveHelp } from "../workerApi";

export type HelpPhase = "idle" | "sending" | "sent" | "failed" | "acked";

export interface HelpController {
  phase: HelpPhase;
  request: () => void;
  cancel: () => void;
  /** 근로자가 그 단계에서 [다 했어요]를 눌렀다(서버가 그 단계·단계 없는 열린 요청을 닫는다). */
  markStepDone: (doneStepId?: string | null) => void;
}

export const HELP_POLL_MS = 5_000;
export const HELP_ACK_CLOSE_MS = 3_000;
export const HELP_SEND_TIMEOUT_MS = 8_000;
/** [취소]가 서버에 닿기를 기다리는 가장 긴 시간(그다음에는 그냥 새로 부른다). */
export const HELP_CANCEL_WAIT_MS = 5_000;

interface HelpApi {
  createHelp: typeof workerApi.createHelp;
  getHelp: typeof workerApi.getHelp;
  cancelHelp: typeof workerApi.cancelHelp;
  cancelHelpByClient?: typeof workerApi.cancelHelpByClient;
}

interface Options {
  assignmentId: string;
  stepId: string | null;
  /** 새로고침 전에 열어 둔 요청(today 카드의 active_help). */
  initial?: ActiveHelp | null;
  api?: HelpApi;
  /** 실제로 부르기를 시작할 때만(이미 '부르는 중'·'불렀어요'라 무시한 누름은 빼고) 한 번 불린다. 측정 이벤트용. */
  onSend?: () => void;
}

// --- 이 탭이 기억하는 것(sessionStorage, 막혀 있으면 기억 없이 동작) ---
const OPEN_KEY = "jobcard_help_open_v1:";
const ACK_SEEN_KEY = "jobcard_help_ack_seen_v1:";

function sget(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function sset(key: string, value: string | null) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, value);
  } catch {
    /* 기억 못 해도 화면은 동작한다 */
  }
}

/** 이 확인을 이 기기에서 이미 보였는지. 보였다고 적는다. */
function ackSeenBefore(h: Pick<HelpOut, "id" | "acknowledged_at">): boolean {
  const key = `${ACK_SEEN_KEY}${h.id}`;
  const stamp = h.acknowledged_at ?? "resolved";
  const seen = sget(key) === stamp;
  sset(key, stamp);
  return seen;
}

function isActive(h: { state: string }): boolean {
  return h.state === "open" || h.state === "acknowledged";
}

export function useHelp({ assignmentId, stepId, initial, api = workerApi, onSend }: Options): HelpController {
  const openKey = `${OPEN_KEY}${assignmentId}`;
  // 처음 확인할 요청: 서버 목록의 active_help, 없으면 이 탭이 기억한 요청(목록이 아직 옛것일 때).
  const [startId] = useState<string | null>(() => initial?.id ?? sget(openKey));
  // 이 탭이 그 요청을 아직 '불렀어요'로 기억하고 있었는지(이 탭의 [다 했어요]·[취소]는 기억을 지운다).
  const [tabRemembered] = useState<boolean>(() => startId !== null && sget(openKey) === startId);
  const [phase, setPhase] = useState<HelpPhase>("idle");
  const helpId = useRef<string | null>(null);
  // 지금 띠의 요청을 부른 단계(서버 HelpOut.step_id). null = 단계 없이 부름.
  const helpStep = useRef<string | null>(null);
  const apiRef = useRef(api);
  const stepRef = useRef(stepId);
  const onSendRef = useRef(onSend);
  // 화면을 떠난 뒤 늦게 온 응답이 상태를 바꾸지 않게.
  const gen = useRef(0);
  useEffect(() => {
    apiRef.current = api;
    stepRef.current = stepId;
    onSendRef.current = onSend;
  });

  const remember = useCallback(
    (id: string | null, step: string | null = null) => {
      helpId.current = id;
      helpStep.current = id ? step : null;
      sset(openKey, id);
    },
    [openKey],
  );

  // 실패한 누름의 client_request_id. [다시 부르기]가 다시 쓴다(서버가 같은 누름으로 묶는다).
  const retryRequestId = useRef<string | null>(null);
  // 지금 보내는 중인 요청(세대 번호 → 누름 키). [다 했어요]로 버린 요청은 답이 오면 취소한다.
  const inflight = useRef<{ gen: number; clientId: string } | null>(null);
  const dropped = useRef(new Set<number>());
  // 답을 못 받은 누름(서버에 닿았는지 모른다). [다 했어요] 때 키로 닫는다.
  const orphans = useRef(new Set<string>());
  // 보내는 중인 [취소]. 새 누름은 이것이 끝난 뒤 보낸다.
  const pendingCancel = useRef<Promise<unknown> | null>(null);

  const closeByClient = useCallback(
    (clientId: string) => {
      const fn = apiRef.current.cancelHelpByClient;
      if (!fn) return;
      fn({ assignment_id: assignmentId, step_id: stepRef.current, client_request_id: clientId })
        .then(() => orphans.current.delete(clientId))
        .catch(() => {
          /* 닿지 않아도 근로자 화면은 닫는다. 늦게 열린 요청은 사업주가 [도와줬어요]로 닫을 수 있다 */
        });
    },
    [assignmentId],
  );

  // 화면에 들어올 때 열려 있던 요청을 서버에 한 번 확인한다.
  useEffect(() => {
    if (!startId) return;
    const my = gen.current;
    apiRef.current
      .getHelp(startId)
      .then((h) => {
        if (gen.current !== my) return;
        if (!isActive(h)) {
          remember(null);
          // 이 탭이 '불렀어요'로 기억한 요청인데 '단계를 끝내서 닫음'이다 = 옛 완료 기록이 늦게 닿아 닫았다.
          // 새로고침 전에 기다리던 근로자에게 사실대로 알린다(4차 검증 2회).
          if (tabRemembered && h.state === "resolved" && h.resolution === "step_done") {
            setPhase("failed");
          }
          return;
        }
        remember(h.id, h.step_id);
        if (h.state === "open") setPhase("sent");
        else if (!ackSeenBefore(h)) setPhase("acked");
        // 이미 본 확인: 선생님이 오는 중이다. 띠는 닫아 두고, 다시 부르면 서버가 같은 요청을 다시 연다.
      })
      .catch(() => {
        if (gen.current !== my) return;
        // 확인을 못 했다(인터넷 끊김). 목록에 열린 요청이 있었으면 그것을 믿는다.
        if (initial && initial.id === startId) {
          remember(initial.id, initial.step_id);
          if (initial.state === "open") setPhase("sent");
          else if (!ackSeenBefore({ id: initial.id, acknowledged_at: null })) setPhase("acked");
        }
      });
    // 처음 한 번만.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const request = useCallback(() => {
    if (phase === "sending" || phase === "sent") return;
    onSendRef.current?.();
    const my = ++gen.current;
    const clientRequestId = (phase === "failed" && retryRequestId.current) || newId();
    retryRequestId.current = clientRequestId;
    inflight.current = { gen: my, clientId: clientRequestId };
    setPhase("sending");
    const ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    let timer: number | null = null;
    const finish = () => {
      if (timer !== null) window.clearTimeout(timer);
      if (inflight.current?.gen === my) inflight.current = null;
    };
    const send = () => {
      timer = window.setTimeout(() => ctrl?.abort(), HELP_SEND_TIMEOUT_MS);
      return apiRef.current.createHelp(
        { assignment_id: assignmentId, step_id: stepRef.current, client_request_id: clientRequestId },
        ctrl?.signal,
      );
    };
    // 방금 누른 [취소]가 먼저 닿게 기다린다(너무 오래 걸리면 그냥 보낸다). 기다릴 취소가 없으면 바로 보낸다.
    const sending: Promise<HelpOut> = pendingCancel.current
      ? Promise.race([pendingCancel.current, new Promise((r) => window.setTimeout(r, HELP_CANCEL_WAIT_MS))]).then(send)
      : send();
    sending
      .then((h) => {
        finish();
        orphans.current.delete(clientRequestId);
        if (dropped.current.delete(my)) {
          // [다 했어요] 뒤에 닿은 요청: 근로자는 이미 일을 마쳤다. 사업주 화면에 남지 않게 닫는다.
          if (isActive(h)) apiRef.current.cancelHelp(h.id).catch(() => {});
          return;
        }
        if (gen.current !== my) return;
        if (h.state === "acknowledged") {
          remember(h.id, h.step_id);
          retryRequestId.current = null;
          ackSeenBefore(h);
          setPhase("acked");
        } else if (h.state === "open") {
          remember(h.id, h.step_id);
          retryRequestId.current = null;
          setPhase("sent");
        } else {
          // 이 누름은 이미 닫혀 있다(다른 기기에서 취소 등). 다시 부르면 새 누름으로.
          retryRequestId.current = null;
          setPhase("failed");
        }
      })
      .catch(() => {
        finish();
        // 서버에 닿았는지 모른다(8초 뒤 끊음·끊김). 키를 기억해 둔다.
        orphans.current.add(clientRequestId);
        if (dropped.current.delete(my)) {
          closeByClient(clientRequestId);
          return;
        }
        if (gen.current !== my) return;
        setPhase("failed");
      });
  }, [assignmentId, phase, closeByClient, remember]);

  const cancel = useCallback(() => {
    const id = helpId.current;
    gen.current += 1;
    remember(null);
    retryRequestId.current = null;
    setPhase("idle");
    // 취소가 닿지 않아도 근로자 화면은 닫는다(선생님이 와도 해가 없다). 409(이미 끝남)도 같다.
    if (id) {
      const p = apiRef.current.cancelHelp(id).catch(() => {});
      pendingCancel.current = p;
      void p.finally(() => {
        if (pendingCancel.current === p) pendingCancel.current = null;
      });
    }
  }, [remember]);

  const markStepDone = useCallback((doneStepId?: string | null) => {
    // 다른 단계에서 부른 요청이 열려 있으면(불렀어요·확인했어요) 서버도 닫지 않는다 — 띠와 상태 확인을 그대로 둔다.
    if (
      (phase === "sent" || phase === "acked") &&
      helpId.current &&
      helpStep.current &&
      doneStepId &&
      helpStep.current !== doneStepId
    ) {
      return;
    }
    if (inflight.current !== null) dropped.current.add(inflight.current.gen);
    gen.current += 1;
    remember(null);
    retryRequestId.current = null;
    // 답을 못 받은 누름은 키로 닫는다(늦게 닿았거나 닿을 요청이 사업주 화면에 남지 않게).
    for (const clientId of [...orphans.current]) closeByClient(clientId);
    // '아직 못 불렀어요'도 닫는다: 근로자가 [다 했어요]를 눌렀다 = 막혔던 일을 풀었다. 다음 단계까지 남기지 않는다.
    setPhase("idle");
  }, [phase, remember, closeByClient]);

  // 'sent' 동안 5초마다 상태 확인.
  useEffect(() => {
    if (phase !== "sent") return;
    const my = gen.current;
    const tick = () => {
      const id = helpId.current;
      if (!id || document.visibilityState === "hidden") return;
      apiRef.current
        .getHelp(id)
        .then((h) => {
          if (gen.current !== my) return;
          if (h.state === "acknowledged" || (h.state === "resolved" && h.resolution === "employer")) {
            ackSeenBefore(h);
            if (h.state === "resolved") remember(null);
            setPhase("acked");
          } else if (h.state === "cancelled") {
            // 이 화면에서 누른 [취소]가 아니다(그때는 이미 idle). 선생님에게 닿지 않으니 사실대로 알린다.
            remember(null);
            retryRequestId.current = null;
            setPhase("failed");
          } else if (h.state === "resolved") {
            // 'sent'인 동안 서버가 '단계를 끝내서 닫음'(step_done)으로 닫았다. 이 화면에서 그 단계 [다 했어요]를 눌렀다면
            // markStepDone이 이미 띠를 닫았다(gen이 바뀌어 여기 오지 않는다). 그러니 이것은 이 도움보다 먼저 끝낸 완료
            // 기록이 늦게 닿아 닫은 것이다(4차 검증 2회: 보내는 중에 몇 초 머문 기록이 그사이 먼저 닿은 도움을 닫았다).
            // 선생님에게는 닿지 않으니 말없이 닫지 않고 '아직 못 불렀어요'로 알린다 — [다시 부르기]는 새 누름이다.
            remember(null);
            retryRequestId.current = null;
            setPhase(h.resolution === "step_done" ? "failed" : "idle");
          }
        })
        .catch(() => {
          /* 확인을 못 해도 '불렀어요'는 사실이다 — 그대로 둔다 */
        });
    };
    const t = window.setInterval(tick, HELP_POLL_MS);
    return () => window.clearInterval(t);
  }, [phase, remember]);

  // '선생님이 확인했어요'는 3초 뒤 닫는다.
  useEffect(() => {
    if (phase !== "acked") return;
    const t = window.setTimeout(() => {
      setPhase("idle");
    }, HELP_ACK_CLOSE_MS);
    return () => window.clearTimeout(t);
  }, [phase]);

  // 화면을 떠나면 늦은 응답을 버린다.
  useEffect(() => {
    return () => {
      gen.current += 1;
    };
  }, []);

  return { phase, request, cancel, markStepDone };
}
