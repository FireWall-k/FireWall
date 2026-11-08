// 이어서 하기(명세 3.5, 7.1 useResume). 어디까지 했는지는 세 곳을 합쳐 정한다:
// 서버의 done_step_ids(다른 기기에서 한 것 포함) + 아직 못 보낸 대기열 + 이 화면에서 방금 끝낸 것.
// 주소의 단계 번호(:n)가 있으면 그 자리를 지킨다(새로고침해도 같은 단계). 범위 밖이면 이어서 할 단계로.
import type { Step } from "../api";

export type JobProgressStatus = "new" | "in_progress" | "done";

export interface JobProgress {
  doneIds: ReadonlySet<string>;
  /** 지금 직무에 있는 단계 중 끝낸 수. */
  doneCount: number;
  /** 0부터. 끝내지 않은 첫 단계. 모두 했으면 steps.length. */
  resumeIndex: number;
  status: JobProgressStatus;
}

/** 여러 출처의 끝낸 단계 id를 합친다. 지금 직무에 없는 단계(그사이 지워진 것)는 뺀다. */
export function mergeDoneIds(steps: readonly Step[], ...sources: Iterable<string>[]): Set<string> {
  const ids = new Set(steps.map((s) => s.id));
  const out = new Set<string>();
  for (const src of sources) for (const id of src) if (ids.has(id)) out.add(id);
  return out;
}

export function jobProgress(steps: readonly Step[], doneIds: ReadonlySet<string>, serverDone = false): JobProgress {
  let doneCount = 0;
  let resumeIndex = -1;
  steps.forEach((s, i) => {
    if (doneIds.has(s.id)) doneCount += 1;
    else if (resumeIndex < 0) resumeIndex = i;
  });
  if (resumeIndex < 0) resumeIndex = steps.length;
  const allDone = steps.length > 0 && doneCount === steps.length;
  const status: JobProgressStatus = serverDone || allDone ? "done" : doneCount > 0 ? "in_progress" : "new";
  return { doneIds, doneCount, resumeIndex, status };
}

/**
 * 단계 화면이 보여 줄 단계(0부터)를 정한다. 주소의 n(1부터)이 범위 안이면 그대로 쓴다([이전]으로 돌아간
 * 자리도 새로고침 뒤 지킨다). 숫자가 아니거나 범위 밖이면 이어서 할 단계로. 모두 했으면 null(완료 화면으로).
 */
export function resolveStepIndex(
  steps: readonly Step[],
  urlN: string | number | undefined,
  doneIds: ReadonlySet<string>,
): number | null {
  const raw = typeof urlN === "number" ? String(urlN) : (urlN ?? "").trim();
  if (/^\d+$/.test(raw)) {
    const n = Number(raw);
    if (n >= 1 && n <= steps.length) return n - 1;
  }
  const { resumeIndex } = jobProgress(steps, doneIds);
  return resumeIndex >= steps.length ? null : resumeIndex;
}
