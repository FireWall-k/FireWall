// 2a-0 보내기 관련 새 API 호출(contract §1.4). 공용 요청 함수 req(api.ts)를 그대로 쓴다.
import { req, type Step } from "../../api";
import { ApiError } from "../../apiErrors";
import type { Recipients, SendCheck, SendDay, SendResult } from "./types";

const enc = encodeURIComponent;

export const sendApi = {
  /** 자동으로 붙은 그림을 사업주가 "맞다"고 확인한다. 서버가 그 단계를 확인함(picture_state=confirmed)으로 둔다. */
  confirmPicture: (taskId: string, stepId: string) =>
    req<Step>(`/api/tasks/${enc(taskId)}/steps/${enc(stepId)}/picture/confirm`, { method: "POST" }),

  /** 보내기 점검표. 막는 항목(blocking)의 step_ids로 그 단계를 가리킨다. */
  sendCheck: (taskId: string) => req<SendCheck>(`/api/tasks/${enc(taskId)}/send-check`),

  /** 근로자들에게 보낸다. 서버가 같은 검사를 하고, 막히면 422(send_blocked·no_steps)·409(archived). */
  send: (taskId: string, workerIds: string[], day: SendDay = "today") =>
    req<SendResult>(`/api/tasks/${enc(taskId)}/send`, {
      method: "POST",
      body: JSON.stringify({ worker_ids: workerIds, day }),
    }),

  recipients: (taskId: string) => req<Recipients>(`/api/tasks/${enc(taskId)}/recipients`),
};

/** 점검표에서 아직 통과하지 못한 막는 항목의 단계 id(중복 없이, 서버가 준 순서대로). */
export function blockedStepIdsOf(check: SendCheck): string[] {
  const out: string[] = [];
  for (const b of check.blocking) {
    if (b.total === 0 || b.done >= b.total) continue;
    for (const id of b.step_ids) if (!out.includes(id)) out.push(id);
  }
  return out;
}

/**
 * 보내기(게시·배정)가 서버 검사에 막혔을 때(422·409) 어느 단계 때문인지 점검표로 알아낸다.
 * 오류 본문의 step_ids는 공용 ApiError가 싣지 않으므로 점검표를 한 번 더 읽는다. 막힌 것이 아니거나
 * 점검표를 못 읽으면 빈 목록이다(오류 문장은 호출한 쪽이 그대로 보여 준다).
 */
export async function blockedStepIdsAfterSendError(taskId: string, error: unknown): Promise<string[]> {
  if (!(error instanceof ApiError) || (error.status !== 422 && error.status !== 409)) return [];
  try {
    return blockedStepIdsOf(await sendApi.sendCheck(taskId));
  } catch {
    return [];
  }
}
