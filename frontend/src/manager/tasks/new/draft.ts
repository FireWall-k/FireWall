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
  } catch {
    /* 무시 */
  }
}

export function isEmptyDraft(d: NewTaskDraft): boolean {
  return !d.rawInput.trim() && !d.businessType.trim() && !d.workEnvironment.trim() && !d.workerNote.trim();
}
