import { describe, it, expect } from "vitest";
import { slowestIndex } from "../src/dashboardChart";

describe("대시보드 소요 시간 막대 — 가장 오래 걸린 단계 강조", () => {
  it("가장 긴 단계 하나를 고른다", () => {
    expect(slowestIndex([12, 40, 7])).toBe(1);
  });

  it("아무도 완료하지 않아 전부 0초면 강조하지 않는다(전부 빨개지던 문제)", () => {
    expect(slowestIndex([0, 0, 0])).toBe(-1);
    expect(slowestIndex([])).toBe(-1);
  });

  it("동점이면 앞 단계 하나만 강조한다", () => {
    expect(slowestIndex([30, 30, 5])).toBe(0);
  });
});
