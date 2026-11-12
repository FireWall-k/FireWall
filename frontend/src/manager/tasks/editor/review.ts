// 편집기 확인 대기열 규칙(명세 5.5 그림 4상태, contract §3.3). 화면은 picture_state 4상태만 본다 — 확신 점수 숫자는
// 오지 않는다. '확인할 것' = 확인함(confirmed)이 아닌 단계(✦ 자동 · 확인 필요, 골라 주세요, 그림 없음). 이 셋은 서버가
// 보내기에서 막는 것과 같다(no_picture·unconfirmed_auto).
import type { Tone } from "../../../components/ui";
import type { EditorStep, EditorTask, PictureCandidate, PictureState } from "../../api/types";

export function needsReview(s: Pick<EditorStep, "picture_state">): boolean {
  return s.picture_state !== "confirmed";
}

export function reviewSteps(task: Pick<EditorTask, "steps">): EditorStep[] {
  return task.steps.filter(needsReview);
}

/** 지금 단계 다음의 확인할 단계(끝까지 없으면 처음부터 다시 찾는다). 없으면 null. */
export function nextReviewId(task: Pick<EditorTask, "steps">, currentId: string | null): string | null {
  const steps = task.steps;
  const at = currentId ? steps.findIndex((s) => s.id === currentId) : -1;
  for (let k = 1; k <= steps.length; k++) {
    const s = steps[(at + k + steps.length) % steps.length];
    if (s && needsReview(s) && s.id !== currentId) return s.id;
  }
  return null;
}

export const STATE_TONE: Record<PictureState, Tone> = {
  confirmed: "success",
  auto_high: "auto",
  choose: "warning",
  none: "danger",
};

/** 같은 단계 목록인지(id·순서). 서버 응답이 다른 단계 묶음을 주면(나눔·합침·지움) 화면의 기억을 다시 맞춘다. */
export function sameIds(a: { id: string }[], b: { id: string }[]): boolean {
  return a.length === b.length && a.every((s, i) => s.id === b[i].id);
}

/** 옛 후보 응답(AacMatch)을 편집기 후보 모양으로. */
export function fromMatches(matches: { asset_id: string; image_url: string; label: string }[]): PictureCandidate[] {
  return matches.slice(0, 3).map((m) => ({ card_id: m.asset_id, url: m.image_url, label: m.label }));
}

/** 직무 응답에서 가장 늦은 고친 시각(다음 자동 저장의 expected_updated_at). */
export function latestUpdatedAt(task: Pick<EditorTask, "updated_at" | "steps">): string | null {
  let best = task.updated_at ?? null;
  for (const s of task.steps) {
    if (s.task_updated_at && (!best || s.task_updated_at > best)) best = s.task_updated_at;
  }
  return best;
}

/** '~하세요'·'~하십시오'로 끝나는 문장을 '~해요'로(끝 마침표는 둔다). '~으세요'처럼 규칙으로 못 바꾸는 끝은 그대로 둔다. */
export function toHaeyo(sentence: string): string {
  return sentence.replace(/(하세요|하십시오|하시오)([.!]?)\s*$/u, "해요$2");
}
