import { beforeEach, describe, expect, it } from "vitest";
import { cachedJobs, localDay, noteSentInTodayCache, TODAY_CACHE_PREFIX } from "../../src/worker/todayCache";
import { normalizeJob, type TodayJob } from "../../src/worker/workerApi";

// 1차 검증: 보낸 기록이 기기의 오늘 할 일에 적히지 않아, 끊긴 채 새로고침하면 다 한 단계가 '안 함'으로 돌아갔다.
const step = (id: string) => ({ id, order: 0, sentence: id, action_type: "other", symbol_url: null } as unknown as TodayJob["steps"][number]);
const job = (aid: string, ids: string[], done: string[] = []): TodayJob =>
  normalizeJob({ assignment_id: aid, task_id: "t", task_title: "컵 씻기", steps: ids.map(step), done_step_ids: done });

beforeEach(() => localStorage.clear());

function seed(jobs: TodayJob[], day = localDay()) {
  localStorage.setItem(`${TODAY_CACHE_PREFIX}w1`, JSON.stringify({ day, jobs }));
}

describe("noteSentInTodayCache", () => {
  it("보낸 단계를 done_step_ids에 더하고, 모든 단계를 덮으면 done", () => {
    seed([job("a1", ["s1", "s2", "s3"]), job("a2", ["x1"])]);
    noteSentInTodayCache("w1", "a1", "s1");
    expect(cachedJobs("w1")![0]).toMatchObject({ done_step_ids: ["s1"], status: "in_progress" });
    noteSentInTodayCache("w1", "a1", "s2");
    noteSentInTodayCache("w1", "a1", "s3");
    noteSentInTodayCache("w1", "a1", "s3"); // 두 번 보내도 한 번
    const [a1, a2] = cachedJobs("w1")!;
    expect(a1.done_step_ids).toEqual(["s1", "s2", "s3"]);
    expect(a1.status).toBe("done");
    expect(a2.done_step_ids).toEqual([]);
  });

  it("모르는 단계·다른 날 저장본은 건드리지 않는다", () => {
    seed([job("a1", ["s1"])]);
    noteSentInTodayCache("w1", "a1", "nope");
    expect(cachedJobs("w1")![0].done_step_ids).toEqual([]);
    seed([job("a1", ["s1"])], "2000-1-1");
    noteSentInTodayCache("w1", "a1", "s1");
    expect(JSON.parse(localStorage.getItem(`${TODAY_CACHE_PREFIX}w1`)!).jobs[0].done_step_ids).toEqual([]);
  });

  it("저장본이 없으면 아무 일도 하지 않는다", () => {
    noteSentInTodayCache("w1", "a1", "s1");
    expect(localStorage.getItem(`${TODAY_CACHE_PREFIX}w1`)).toBeNull();
  });
});
