// (2d 검증 1회차) 사업주 말투는 '~해요' 체의 짧은 존댓말이다(명세 6.7). 부탁은 '~해 주세요'로 쓰고,
// '~두세요'·'~하세요' 같은 시킴꼴로 끝내지 않는다. 2d가 만든 문구 묶음을 함수 문구까지 펼쳐 본다.
import { describe, expect, it } from "vitest";
import * as copy from "../../src/manager/copy";

const GROUPS = [
  "todayBadge", "consentState", "accessCode", "workerList", "workerAdd", "printCard",
  "workerDelete", "workerDetail", "workerStats", "prefs", "consent", "settings",
] as const;

function strings(v: unknown): string[] {
  if (typeof v === "string") return [v];
  if (typeof v === "function") {
    try {
      return strings((v as (...a: unknown[]) => unknown)("김민지", "김민지", "김민지"));
    } catch {
      return [];
    }
  }
  if (Array.isArray(v)) return v.flatMap(strings);
  if (v && typeof v === "object") return Object.values(v).flatMap(strings);
  return [];
}

describe("2d 사업주 문구 말투", () => {
  for (const g of GROUPS) {
    it(`${g}: 문장이 '~세요'(주세요 제외)로 끝나지 않는다`, () => {
      const all = strings((copy as Record<string, unknown>)[g]);
      expect(all.length).toBeGreaterThan(0);
      const bad = all.flatMap((s) => s.split(/(?<=[.!?])\s+/)).filter((s) => /(?<!주)세요[.!]?$/.test(s.trim()));
      expect(bad).toEqual([]);
    });
  }
});
