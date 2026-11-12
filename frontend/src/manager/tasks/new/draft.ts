// 새 직무 화면의 임시 저장(tasks §4.3 NewTaskPage). 원문과 '더 알려 주기'만 이 기기에 둔다 — 새로고침해도 적던 글이 남게.
// localStorage는 막혀 있을 수 있다(사생활 보호 창 등). 읽기·쓰기 모두 실패해도 화면은 그대로 돈다.
export const NEW_TASK_DRAFT_KEY = "jobcard_new_task_draft_v1";

export interface NewTaskDraft {
  rawInput: string;
  businessType: string;
  workEnvironment: string;
  workerNote: string;
  noteWorkerId: string;
}

export const EMPTY_DRAFT: NewTaskDraft = {
  rawInput: "",
  businessType: "",
  workEnvironment: "",
  workerNote: "",
  noteWorkerId: "",
};

export function readDraft(): NewTaskDraft | null {
  try {
    const raw = localStorage.getItem(NEW_TASK_DRAFT_KEY);
    if (!raw) return null;
    const v = JSON.parse(raw) as Partial<NewTaskDraft>;
    const str = (x: unknown) => (typeof x === "string" ? x : "");
    const d: NewTaskDraft = {
      rawInput: str(v.rawInput),
      businessType: str(v.businessType),
      workEnvironment: str(v.workEnvironment),
      workerNote: str(v.workerNote),
      noteWorkerId: str(v.noteWorkerId),
    };
    return isEmptyDraft(d) ? null : d;
  } catch {
    return null;
  }
}

export function writeDraft(d: NewTaskDraft) {
  try {
    if (isEmptyDraft(d)) localStorage.removeItem(NEW_TASK_DRAFT_KEY);
    else localStorage.setItem(NEW_TASK_DRAFT_KEY, JSON.stringify(d));
  } catch {
    /* 저장하지 못해도 적는 데는 지장이 없다 */
  }
}

export function clearDraft() {
  try {
    localStorage.removeItem(NEW_TASK_DRAFT_KEY);
    localStorage.removeItem(NEW_TASK_PREVIEW_KEY);
  } catch {
    /* 무시 */
  }
}

export function isEmptyDraft(d: NewTaskDraft): boolean {
  return !d.rawInput.trim() && !d.businessType.trim() && !d.workEnvironment.trim() && !d.workerNote.trim();
}

// (2b-1, 2회차 검증) 나눈 단계 목록(고친 줄 포함)도 이 기기에 둔다 — 브라우저·휴대폰 [뒤로]는 '적던 내용이 사라져요'를
// 묻지 못해서(popstate), 돌아왔을 때 나눈 결과가 남아 있게 한다. 모양은 부르는 쪽(NewTaskPage)이 정한다.
export const NEW_TASK_PREVIEW_KEY = "jobcard_new_task_preview_v1";

export function readSavedPreview<T>(isValid: (v: unknown) => v is T): T | null {
  try {
    const raw = localStorage.getItem(NEW_TASK_PREVIEW_KEY);
    if (!raw) return null;
    const v: unknown = JSON.parse(raw);
    return isValid(v) ? v : null;
  } catch {
    return null;
  }
}

export function writeSavedPreview(v: unknown | null) {
  try {
    if (v == null) localStorage.removeItem(NEW_TASK_PREVIEW_KEY);
    else localStorage.setItem(NEW_TASK_PREVIEW_KEY, JSON.stringify(v));
  } catch {
    /* 저장하지 못해도 나누기는 그대로 돈다 */
  }
}
