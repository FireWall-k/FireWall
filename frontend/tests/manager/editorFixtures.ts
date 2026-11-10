// 편집기 시험용 단계·직무 모양(contract §3.3 EditorStepOut, §1.4 TaskOut).
import type { EditorStep, EditorTask, PictureState } from "../../src/manager/api/types";

export const T0 = "2026-11-10T01:00:00.000000";

export function step(id: string, order: number, sentence: string, state: PictureState, over: Partial<EditorStep> = {}): EditorStep {
  const url = state === "none" ? null : `http://x/api/aac/images/cafe/${id}.webp`;
  return {
    id,
    order,
    sentence,
    action_type: "other",
    symbol_url: url,
    symbol_source: state === "none" ? "fallback" : "LOCAL_AAC",
    needs_fallback: state === "choose" || state === "none",
    tts_audio_url: null,
    picture_state: state,
    safety_flag: false,
    picture: url ? { card_id: id, url, label: `${sentence} 그림`, source: "auto" } : null,
    candidates: [],
    split: { source: "", needs_review: false, original_span: "" },
    lint: [],
    safety: { flag: false, source: "", note: "" },
    group_break: false,
    task_updated_at: T0,
    ...over,
  };
}

export function task(steps: EditorStep[], over: Partial<EditorTask> = {}): EditorTask {
  return {
    id: "task-1",
    title: "상자 정리",
    status: "draft",
    steps,
    version: null,
    in_progress_count: 0,
    recipients_count: 0,
    updated_at: T0,
    ...over,
  };
}

/** 고정 문장(p2/b1_fixed_sentence.txt) 6단계, 모두 ✦ 자동(auto_high), 1단계는 '칼'로 자동 조심. */
export function sixAutoHigh(): EditorTask {
  const s = [
    "커터칼로 상자를 열어요.",
    "상품을 선반에 놓아요.",
    "같은 상품끼리 모아요.",
    "테이블을 행주로 닦아요.",
    "바닥을 빗자루로 쓸어요.",
    "손을 씻어요.",
  ].map((t, i) =>
    step(`s${i + 1}`, i + 1, t, "auto_high", i === 0 ? { safety_flag: true, safety: { flag: true, source: "auto", note: "" } } : {}),
  );
  return task(s);
}

export function candidatesFor(t: EditorTask) {
  return {
    steps: t.steps.map((s) => ({
      step_id: s.id,
      candidates: [1, 2, 3].map((k) => ({ card_id: `${s.id}-c${k}`, url: `http://x/api/aac/images/cafe/${s.id}-c${k}.webp`, label: `후보${k}` })),
    })),
  };
}
