// 도움 요청(명세 4.5, contract §7). 상태를 사실대로 보여 준다:
//   idle → sending('부르는 중') → sent('불렀어요', [취소]) → acked('선생님이 확인했어요', 3초 뒤 닫힘)
//                              ↘ failed('아직 못 불렀어요. 손을 들어 선생님을 불러요.', [다시 부르기])
// - 도움 요청은 대기열에 넣지 않는다: 닿지 않으면 사람에게 직접 청하라고 알린다(늦게 닿은 요청은 쓸모없다).
// - 'sent'인 동안 5초마다 상태를 본다(숨은 탭에서는 멈춤). 사업주가 확인·해결하면 acked.
// - [다 했어요]를 누르면 서버가 요청을 '해결됨'으로 닫으므로 띠도 닫는다(markStepDone).
// - 새로고침 뒤에는 today 카드의 active_help로 띠를 되살린다.
import { useCallback, useEffect, useRef, useState } from "react";
import { newId, workerApi, type ActiveHelp } from "../workerApi";

export type HelpPhase = "idle" | "sending" | "sent" | "failed" | "acked";

export interface HelpController {
  phase: HelpPhase;
  request: () => void;
  cancel: () => void;
  /** 근로자가 [다 했어요]를 눌렀다(서버가 열린 요청을 닫는다). */
  markStepDone: () => void;
}

export const HELP_POLL_MS = 5_000;
export const HELP_ACK_CLOSE_MS = 3_000;

interface HelpApi {
  createHelp: typeof workerApi.createHelp;
  getHelp: typeof workerApi.getHelp;
  cancelHelp: typeof workerApi.cancelHelp;
}

interface Options {
  assignmentId: string;
  stepId: string | null;
  /** 새로고침 전에 열어 둔 요청(today 카드의 active_help). */
  initial?: ActiveHelp | null;
  api?: HelpApi;
}

function initialPhase(initial?: ActiveHelp | null): HelpPhase {
  if (!initial) return "idle";
  return initial.state === "acknowledged" ? "acked" : "sent";
}

export function useHelp({ assignmentId, stepId, initial, api = workerApi }: Options): HelpController {
  const [phase, setPhase] = useState<HelpPhase>(() => initialPhase(initial));
  const helpId = useRef<string | null>(initial?.id ?? null);
  const apiRef = useRef(api);
  const stepRef = useRef(stepId);
  // 화면을 떠난 뒤 늦게 온 응답이 상태를 바꾸지 않게.
  const gen = useRef(0);
  useEffect(() => {
    apiRef.current = api;
    stepRef.current = stepId;
  });

  const request = useCallback(() => {
    if (phase === "sending" || phase === "sent") return;
    const my = ++gen.current;
    setPhase("sending");
    apiRef.current
      .createHelp({ assignment_id: assignmentId, step_id: stepRef.current, client_request_id: newId() })
      .then((h) => {
        if (gen.current !== my) return;
        helpId.current = h.id;
        if (h.state === "acknowledged") setPhase("acked");
        else if (h.state === "open") setPhase("sent");
        else setPhase("failed");
      })
      .catch(() => {
        if (gen.current !== my) return;
        setPhase("failed");
      });
  }, [assignmentId, phase]);

  const cancel = useCallback(() => {
    const id = helpId.current;
    gen.current += 1;
    helpId.current = null;
    setPhase("idle");
    // 취소가 닿지 않아도 근로자 화면은 닫는다(선생님이 와도 해가 없다). 409(이미 끝남)도 같다.
    if (id) apiRef.current.cancelHelp(id).catch(() => {});
  }, []);

  const markStepDone = useCallback(() => {
    gen.current += 1;
    helpId.current = null;
    setPhase((p) => (p === "idle" || p === "failed" ? p : "idle"));
  }, []);

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
          if (h.state === "acknowledged" || (h.state === "resolved" && h.resolution === "employer")) setPhase("acked");
          else if (h.state === "cancelled" || h.state === "resolved") {
            helpId.current = null;
            setPhase("idle");
          }
        })
        .catch(() => {
          /* 확인을 못 해도 '불렀어요'는 사실이다 — 그대로 둔다 */
        });
    };
    const t = window.setInterval(tick, HELP_POLL_MS);
    return () => window.clearInterval(t);
  }, [phase]);

  // '선생님이 확인했어요'는 3초 뒤 닫는다.
  useEffect(() => {
    if (phase !== "acked") return;
    const t = window.setTimeout(() => {
      helpId.current = null;
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
