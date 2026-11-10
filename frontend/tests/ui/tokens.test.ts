import { describe, expect, it } from "vitest";
import tailwindConfig from "../../tailwind.config.js";

// 사업주 글자 조합이 모두 4.5:1 이상인지 토큰 값으로 직접 계산한다(명세 6.1, R1).
// 토큰 값을 바꾸다 대비가 무너지면 여기서 실패한다.
type Palette = Record<string, Record<string, string> | string>;
// (2d 팔레트 잠금) 색은 theme.extend가 아니라 theme.colors에 있다(기본 팔레트를 덮어씀).
const colors = (tailwindConfig.theme!.colors ?? {}) as Palette;

function hex(name: string): string {
  if (name === "white") return "#FFFFFF";
  const [group, shade] = name.split(/-(.+)/);
  const g = colors[group];
  const v = typeof g === "string" ? g : g?.[shade];
  if (!v) throw new Error(`토큰 없음: ${name}`);
  return v;
}

function luminance(h: string): number {
  const n = h.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

export function contrast(fg: string, bg: string): number {
  const [a, b] = [luminance(hex(fg)), luminance(hex(bg))].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}

// [글자, 바탕]: 새 사업주 부품이 실제로 쓰는 조합.
const PAIRS: [string, string][] = [
  ["ink-900", "paper-50"],
  ["ink-900", "paper-100"],
  ["ink-900", "white"],
  ["ink-700", "paper-50"],
  ["ink-700", "paper-100"],
  ["ink-700", "white"],
  ["ink-500", "paper-50"],
  ["ink-500", "paper-100"],
  ["ink-500", "white"],
  ["white", "moss-600"],
  ["white", "moss-700"],
  ["moss-600", "white"],
  ["moss-600", "paper-100"],
  ["white", "danger-700"],
  ["white", "danger-800"],
  ["white", "ink-900"],
  ["ok-700", "ok-50"],
  ["warn-700", "warn-50"],
  ["danger-700", "danger-50"],
  ["danger-700", "white"],
  ["info-700", "white"],
  ["auto-700", "auto-50"],
  ["auto-700", "white"],
];

describe("사업주 토큰 대비(4.5:1 이상)", () => {
  it.each(PAIRS)("%s 글자 / %s 바탕", (fg, bg) => {
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(4.5);
  });

  it("입력칸 테두리 line-strong은 흰 바탕 위 3:1 이상(비글자 대비)", () => {
    expect(contrast("line-strong", "white")).toBeGreaterThanOrEqual(3);
  });

  it("명세 값 그대로: ink-500 #5B675F, moss-600 #48613F, 근로자 primary #1F6340", () => {
    expect(hex("ink-500")).toBe("#5B675F");
    expect(hex("moss-600")).toBe("#48613F");
    expect(hex("worker-primary")).toBe("#1F6340");
  });
});

describe("사업주 크기 토큰(명세 6.2·6.3)", () => {
  const ext = tailwindConfig.theme!.extend! as Record<string, Record<string, unknown>>;
  it("글자 xs12~kpi32, 10~11px 없음", () => {
    const fs = ext.fontSize as Record<string, [string, unknown]>;
    const px = (k: string) => parseFloat(fs[k][0]) * 16;
    expect([px("ui-xs"), px("ui-sm"), px("ui-base"), px("ui-md"), px("ui-lg"), px("ui-xl"), px("ui-kpi")]).toEqual([
      12, 13, 14, 16, 20, 24, 32,
    ]);
    for (const [k] of Object.entries(fs)) expect(px(k), k).toBeGreaterThanOrEqual(12);
  });
  it("모서리 6/10/14, 컨트롤 36(coarse 44), 표 행 56, 목록 행 88", () => {
    expect(ext.borderRadius).toMatchObject({ control: "6px", card: "10px", overlay: "14px" });
    expect(ext.minHeight).toMatchObject({ control: "36px", "control-coarse": "44px", "table-row": "56px", "list-row": "88px" });
  });
});
