import { describe, it, expect } from "vitest";
import { stuckIndices } from "../src/dashboardChart";

describe("대시보드 소요 시간 막대 — 막힘 기록 단계 강조", () => {
  it("막힘 기록이 있는 단계를 모두 고른다", () => {
    expect(stuckIndices([false, true, true, false])).toEqual([1, 2]);
  });

  it("막힘 기록이 없으면 강조하지 않는다", () => {
    expect(stuckIndices([false, false])).toEqual([]);
    expect(stuckIndices([])).toEqual([]);
  });
});
