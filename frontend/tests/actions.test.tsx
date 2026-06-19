import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { metaFor, ActionChip, ACTION_META } from "../src/actions";

describe("동작 시각화 메타 (기능 4)", () => {
  it("모든 동작 타입에 라벨과 색 클래스가 있다", () => {
    for (const k of ["observe", "move", "stack", "sort", "pack", "clean", "other"]) {
      expect(ACTION_META[k].label.length).toBeGreaterThan(0);
      expect(ACTION_META[k].chip).toMatch(/bg-/);
    }
  });

  it("알 수 없는 동작은 '작업하기'로 폴백한다", () => {
    expect(metaFor("nonsense").label).toBe("작업하기");
  });

  it("ActionChip이 라벨을 렌더한다", () => {
    render(<ActionChip action="move" />);
    expect(screen.getByText("옮기기")).toBeInTheDocument();
  });

  it("서로 다른 동작은 서로 다른 라벨로 구분된다", () => {
    expect(metaFor("observe").label).toBe("확인하기");
    expect(metaFor("stack").label).toBe("쌓기");
    expect(metaFor("sort").label).toBe("분류하기");
  });
});
