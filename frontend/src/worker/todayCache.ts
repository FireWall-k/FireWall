// 근로자 기기에 둔 마지막 응답(오프라인용): 내 정보와 오늘 할 일. 같은 날·같은 로그인일 때만 쓴다.
import { normalizePrefs, type TodayJob, type WorkerMe } from "./workerApi";

export const ME_CACHE_KEY = "jobcard_worker_me_v1";
export const TODAY_CACHE_PREFIX = "jobcard_today_v1:";

export function localDay(d = new Date()): string {
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

export function readJson<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export function writeJson(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* 저장 못 하면 오프라인에서 새로 받을 수 없을 뿐 */
  }
}

export function cachedMe(token: string | undefined): WorkerMe | null {
  const c = readJson<{ token: string; me: WorkerMe }>(ME_CACHE_KEY);
  return c && token && c.token === token ? { ...c.me, a11y_prefs: normalizePrefs(c.me.a11y_prefs) } : null;
}

export function cachedJobs(workerId: string): TodayJob[] | null {
  const c = readJson<{ day: string; jobs: TodayJob[] }>(`${TODAY_CACHE_PREFIX}${workerId}`);
  return c && c.day === localDay() && Array.isArray(c.jobs) ? c.jobs : null;
}

/**
 * 서버가 받은 완료 기록을 기기에 둔 오늘 할 일에도 적는다. 대기열은 보내면 바로 지우는데 오늘 할 일은 30초마다만
 * 다시 받으므로, 그 사이 인터넷이 끊긴 채 새로고침하면 보낸 단계가 '안 함'으로 돌아가 1단계부터 다시 하게 됐다
 * (1차 검증). 모든 단계를 덮으면 status도 done으로.
 */
export function noteSentInTodayCache(workerId: string, assignmentId: string, stepId: string) {
  const key = `${TODAY_CACHE_PREFIX}${workerId}`;
  const c = readJson<{ day: string; jobs: TodayJob[] }>(key);
  if (!c || c.day !== localDay() || !Array.isArray(c.jobs)) return;
  let changed = false;
  const jobs = c.jobs.map((j) => {
    if (j.assignment_id !== assignmentId || !j.steps.some((st) => st.id === stepId)) return j;
    const done = j.done_step_ids ?? [];
    if (done.includes(stepId)) return j;
    changed = true;
    const ids = [...done, stepId];
    const all = j.steps.every((st) => ids.includes(st.id));
    return { ...j, done_step_ids: ids, status: all ? "done" : "in_progress" } satisfies TodayJob;
  });
  if (changed) writeJson(key, { day: c.day, jobs });
}

/**
 * 새로 받은 오늘 할 일을 기기에 둔다. 이미 둔 목록에 적힌 끝낸 단계(같은 배정·지금도 있는 단계)는 지우지 않고 합친다.
 * 2차 검증: 완료 기록보다 먼저 서버가 답한 느린 GET이 기록 전송 뒤에 도착하면, noteSentInTodayCache가 적어 둔 단계를
 * 덮어써 지웠다(대기열에서도 이미 지워진 뒤라, 끊긴 채 새로고침하면 끝낸 단계부터 다시 했다). 끝낸 단계는 서버에서도
 * '안 함'으로 돌아가지 않으므로 합쳐도 된다. 합친 목록을 돌려준다(화면도 같은 것을 쓴다).
 */
export function writeTodayCache(workerId: string, list: TodayJob[]): TodayJob[] {
  const key = `${TODAY_CACHE_PREFIX}${workerId}`;
  const day = localDay();
  const prev = readJson<{ day: string; jobs: TodayJob[] }>(key);
  const known = new Map<string, string[]>();
  if (prev && prev.day === day && Array.isArray(prev.jobs)) {
    for (const j of prev.jobs) known.set(j.assignment_id, j.done_step_ids ?? []);
  }
  const jobs = list.map((j) => {
    const old = known.get(j.assignment_id);
    if (!old || old.length === 0) return j;
    const ids = [...(j.done_step_ids ?? [])];
    for (const id of old) if (!ids.includes(id) && j.steps.some((st) => st.id === id)) ids.push(id);
    if (ids.length === (j.done_step_ids ?? []).length) return j;
    const all = j.steps.length > 0 && j.steps.every((st) => ids.includes(st.id));
    return { ...j, done_step_ids: ids, status: all ? "done" : "in_progress" } satisfies TodayJob;
  });
  writeJson(key, { day, jobs });
  return jobs;
}
