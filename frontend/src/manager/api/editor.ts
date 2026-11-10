// 2b-1 새 직무·편집기 API 호출(contract §3.4). 화면 시험은 이 모듈을 통째로 목으로 바꾼다(vi.mock).
// 오류는 req가 던지는 ApiError·NetworkError·AuthError 그대로다(message = 서버의 한국어 detail).
// 옛 호출(api.ts)과 주소가 같은 것은 api를 그대로 부르되, 편집기 모양(EditorTask·EditorStep)으로 받는다.
import {
  api,
  req,
  type AacSearchResult,
  type ConfirmedStep,
  type CreateTaskOptions,
  type SplitPreview,
  type SplitPreviewStep,
  type StepSymbolCandidates,
  type TaskContext,
  type Worker,
} from "../../api";
import type {
  ConfirmedStepExtra,
  EditorStep,
  EditorTask,
  PictureApplyRequest,
  StepPatchRequest,
  StepTtsOut,
  TaskCandidates,
} from "./types";

const enc = encodeURIComponent;

/** 예전 서버·목이 빠뜨린 편집 칸을 채운다(화면이 칸 없음으로 깨지지 않게). 서버 값은 그대로 둔다. */
export function normalizeStep(s: Partial<EditorStep> & Pick<EditorStep, "id" | "sentence">): EditorStep {
  const state = s.picture_state ?? (s.symbol_url ? "auto_high" : "none");
  return {
    order: 0, action_type: "other", symbol_url: null, symbol_source: "fallback", needs_fallback: false, tts_audio_url: null,
    ...s,
    picture_state: state,
    safety_flag: s.safety_flag ?? false,
    picture: s.picture ?? null,
    candidates: s.candidates ?? [],
    split: { source: "", needs_review: false, original_span: "", ...(s.split ?? {}) },
    lint: s.lint ?? [],
    safety: { flag: s.safety_flag ?? false, source: "", note: "", ...(s.safety ?? {}) },
    group_break: s.group_break ?? false,
    task_updated_at: s.task_updated_at ?? null,
  } as EditorStep;
}

export function normalizeTask<T extends { steps: unknown[] }>(t: T): T & EditorTask {
  const x = t as unknown as Partial<EditorTask> & { steps: (Partial<EditorStep> & Pick<EditorStep, "id" | "sentence">)[] };
  return {
    version: null, in_progress_count: 0, recipients_count: 0, updated_at: null,
    ...x,
    steps: x.steps.map(normalizeStep),
  } as unknown as T & EditorTask;
}

const task_ = <T extends { steps: unknown[] }>(p: Promise<T>) => p.then(normalizeTask);
const step_ = (p: Promise<EditorStep>) => p.then(normalizeStep);
const task = (id: string) => `/api/tasks/${enc(id)}`;
const step = (id: string, sid: string) => `${task(id)}/steps/${enc(sid)}`;

/** 나누기 미리보기 한 줄(2b-1: '✦ 자동 제안' 조심 표시가 더해짐). */
export type EditorSplitStep = SplitPreviewStep & { safety_flag?: boolean };
export type EditorSplitPreview = Omit<SplitPreview, "steps"> & { steps: EditorSplitStep[] };

/** [이대로 그림 고르기]가 보내는 확인한 단계(나눈 방법·원문 조각·조심 표시 포함). */
export type CreateStep = ConfirmedStep & ConfirmedStepExtra;

/** 편집기 문장 저장(rewrite) 결과. 동작이 둘이라 나눴으면 split_step_ids에 새 단계 id가 온다(되돌리기용). */
export interface EditorRewriteResult {
  task: EditorTask;
  split_step_ids: string[];
  sentence: string;
}

export const editorApi = {
  getTask: (id: string) => task_(req<EditorTask>(task(id))),

  splitPreview: (raw: string, context: TaskContext = {}) =>
    api.splitPreview(raw, context) as Promise<EditorSplitPreview>,

  createTask: (raw: string, opts: Omit<CreateTaskOptions, "steps"> & { steps: CreateStep[] }) =>
    task_(req<EditorTask>("/api/tasks", { method: "POST", body: JSON.stringify({ raw_input: raw, ...opts }) })),

  /** 단계 고치기(문장 자동 저장·조심 스위치·묶음 경계). expected_updated_at이 다르면 409(다른 창에서 먼저 고침). */
  patchStep: (id: string, sid: string, body: StepPatchRequest) =>
    step_(req<EditorStep>(step(id, sid), { method: "PATCH", body: JSON.stringify(body) })),

  /** 칸을 벗어날 때: 음성·나누기 검사를 마무리한다. 동작이 둘이면 서버가 두 단계로 나눈다. */
  /** expectedUpdatedAt: 이 창이 본 직무 updated_at(자동 저장과 같은 다른 창 검사, 다르면 409). */
  rewriteStep: (id: string, sid: string, sentence: string, expectedUpdatedAt?: string | null) =>
    req<EditorRewriteResult>(`${step(id, sid)}/rewrite`, {
      method: "POST",
      body: JSON.stringify(expectedUpdatedAt ? { sentence, expected_updated_at: expectedUpdatedAt } : { sentence }),
    }).then((r) => ({
      ...r,
      task: normalizeTask(r.task),
    })),

  mergeSteps: (id: string, stepIds: string[], sentence: string, actionType?: string) =>
    task_(
      req<EditorTask>(`${task(id)}/steps/merge`, {
        method: "POST",
        body: JSON.stringify({ step_ids: stepIds, sentence, action_type: actionType }),
      }),
    ),

  addStep: (id: string, sentence: string) =>
    task_(
      req<EditorTask & { split_step_ids?: string[]; sentence?: string }>(`${task(id)}/steps`, {
        method: "POST",
        body: JSON.stringify({ sentence }),
      }),
    ),

  deleteStep: (id: string, sid: string) => task_(req<EditorTask>(step(id, sid), { method: "DELETE" })),

  reorderSteps: (id: string, stepIds: string[]) =>
    task_(req<EditorTask>(`${task(id)}/steps/reorder`, { method: "PATCH", body: JSON.stringify({ step_ids: stepIds }) })),

  /** 한 단계 [이 그림이 맞아요]. */
  confirmPicture: (id: string, sid: string) => step_(req<EditorStep>(`${step(id, sid)}/picture/confirm`, { method: "POST" })),

  /** [보이는 자동 그림 모두 맞아요]. 확인할 수 없는 단계가 섞이면 422이고 하나도 바꾸지 않는다. */
  confirmPictures: (id: string, stepIds: string[]) =>
    req<EditorStep[]>(`${task(id)}/pictures/confirm`, { method: "POST", body: JSON.stringify({ step_ids: stepIds }) }).then((l) =>
      l.map(normalizeStep),
    ),

  /** 후보·검색 결과 적용 → 확인함. */
  applyPicture: (id: string, sid: string, body: PictureApplyRequest) =>
    step_(req<EditorStep>(`${step(id, sid)}/picture`, { method: "POST", body: JSON.stringify(body) })),

  /** 모든 단계 후보(최대 3장씩). 유료 모델 없이 찾는다. */
  candidates: (id: string) => req<TaskCandidates>(`${task(id)}/candidates`),

  /** 한 단계 후보(문장을 고친 뒤 그 단계만 다시 찾을 때). */
  stepCandidates: (id: string, sid: string) =>
    req<StepSymbolCandidates>(`${step(id, sid)}/symbol-candidates`),

  /** [목소리 듣기]: 음성이 없거나 옛 문장이면 그때 만든다. 못 만들었으면 tts_url이 null. */
  stepTts: (id: string, sid: string) => req<StepTtsOut>(`${step(id, sid)}/tts`, { method: "POST" }),

  uploadPhoto: (id: string, sid: string, file: File) => step_(api.uploadStepPhoto(id, sid, file) as Promise<EditorStep>),
  removePhoto: (id: string, sid: string) => step_(api.removeStepPhoto(id, sid) as Promise<EditorStep>),

  searchPictures: (query: string, job?: string, limit = 9): Promise<AacSearchResult> => api.searchAac(query, job, limit),

  listWorkers: (): Promise<Worker[]> => api.listWorkers(),
};
