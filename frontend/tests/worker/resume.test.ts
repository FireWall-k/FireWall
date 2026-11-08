import { describe, expect, it } from "vitest";
import type { Step } from "../../src/api";
import { historyDateLabel } from "../../src/worker/historyDate";
import { jobProgress, mergeDoneIds, resolveStepIndex } from "../../src/worker/resume";

const steps = ["s1", "s2", "s3", "s4"].map((id, i) => ({ id, order: i + 1 }) as Step);

describe("이어서 하기(useResume)", () => {
  it("서버·대기열·이 화면의 기록을 합치고, 지금 직무에 없는 단계는 뺀다", () => {
    const ids = mergeDoneIds(steps, ["s1", "deleted"], ["s2"], []);
    expect([...ids].sort()).toEqual(["s1", "s2"]);
    const p = jobProgress(steps, ids);
    expect(p).toMatchObject({ doneCount: 2, resumeIndex: 2, status: "in_progress" });
  });

  it("중간을 건너뛰었으면 끝내지 않은 첫 단계부터", () => {
    expect(jobProgress(steps, new Set(["s1", "s3"])).resumeIndex).toBe(1);
  });

  it("상태: 새 일 / 하는 중 / 다 함(서버 done이면 단계 수와 상관없이 다 함)", () => {
    expect(jobProgress(steps, new Set()).status).toBe("new");
    expect(jobProgress(steps, new Set(["s1", "s2", "s3", "s4"])).status).toBe("done");
    expect(jobProgress(steps, new Set(), true).status).toBe("done");
  });

  it("주소의 단계 번호가 범위 안이면 그 자리(새로고침), 밖이면 이어서 할 단계(다른 기기)", () => {
    const done = new Set(["s1", "s2"]);
    expect(resolveStepIndex(steps, "1", done)).toBe(0); // [이전]으로 돌아간 자리도 지킨다
    expect(resolveStepIndex(steps, "4", done)).toBe(3);
    expect(resolveStepIndex(steps, "9", done)).toBe(2);
    expect(resolveStepIndex(steps, "0", done)).toBe(2);
    expect(resolveStepIndex(steps, "abc", done)).toBe(2);
    expect(resolveStepIndex(steps, "2x", done)).toBe(2);
    expect(resolveStepIndex(steps, undefined, done)).toBe(2);
  });

  it("모두 했으면 null(완료 화면으로)", () => {
    expect(resolveStepIndex(steps, "99", new Set(["s1", "s2", "s3", "s4"]))).toBeNull();
  });
});

describe("했던 일 날짜 묶음", () => {
  const now = new Date(2026, 10, 9, 10, 0);
  it("오늘·어제·'11월 6일 목요일'(ISO 날짜를 쓰지 않음)", () => {
    expect(historyDateLabel("2026-11-09", now)).toBe("오늘");
    expect(historyDateLabel("2026-11-08", now)).toBe("어제");
    expect(historyDateLabel("2026-11-06", now)).toBe("11월 6일 금요일");
  });
});
