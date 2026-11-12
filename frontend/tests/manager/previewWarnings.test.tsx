import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { estimateLines, stepWarnings } from "../../src/manager/preview/warnings";
import { PreviewWarnings } from "../../src/manager/preview/PreviewPanel";

const base = { sentence: "손을 씻어요.", symbol_url: "https://x/y.webp", picture_state: "confirmed" as const, group_break: false };

describe("미리보기 경고 배지(2b-2)", () => {
  it("짧은 문장·그림 있음·묶음 경계 아님이면 경고 없음", () => {
    expect(stepWarnings(base)).toEqual([]);
  });

  it("휴대폰 폭에서 2줄을 넘는 문장은 long", () => {
    expect(estimateLines("손을 씻어요.")).toBe(1);
    expect(estimateLines("커터칼로 상자를 조심해서 열어요.")).toBe(2);
    const long = "커터칼로 상자 테이프를 위에서 아래로 천천히 조심해서 끝까지 잘라요.";
    expect(estimateLines(long)).toBeGreaterThan(2);
    expect(stepWarnings({ ...base, sentence: long })).toEqual(["long"]);
  });

  it("띄어쓰기 없는 긴 낱말도 글자 단위로 줄을 센다", () => {
    expect(estimateLines("가".repeat(30))).toBe(4);
    expect(estimateLines("")).toBe(0);
  });

  it("그림이 없거나 picture_state가 none이면 no_picture", () => {
    expect(stepWarnings({ ...base, symbol_url: null })).toEqual(["no_picture"]);
    expect(stepWarnings({ ...base, picture_state: "none" })).toEqual(["no_picture"]);
  });

  it("묶음 경계면 group, 여러 경고는 정해진 순서로", () => {
    expect(stepWarnings({ ...base, group_break: true })).toEqual(["group"]);
    const long = "커터칼로 상자 테이프를 위에서 아래로 천천히 조심해서 끝까지 잘라요.";
    expect(stepWarnings({ sentence: long, symbol_url: null, picture_state: "none", group_break: true })).toEqual([
      "long",
      "no_picture",
      "group",
    ]);
  });

  it("배지 문구: 경고마다 한 개, 없으면 '고칠 것이 없어요'", () => {
    const { rerender } = render(<PreviewWarnings warnings={["long", "no_picture", "group"]} />);
    expect(screen.getByText("문장이 2줄을 넘어요")).toBeTruthy();
    expect(screen.getByText("그림이 없어요")).toBeTruthy();
    expect(screen.getByText("여기서 묶음이 나뉘어요")).toBeTruthy();
    rerender(<PreviewWarnings warnings={[]} />);
    expect(screen.getByText("고칠 것이 없어요")).toBeTruthy();
    expect(screen.queryByText(/AI/)).toBeNull();
  });
});
