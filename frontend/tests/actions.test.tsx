import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { metaFor, ActionChip, ACTION_META, stepActionChip, WorkerActionChip } from "../src/actions";

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

// 근로자 화면 꼬리표: 계열 이름이 아니라 문장 서술어의 동사로 만든다(상자를 접는 단계에 "담기"가 붙던 문제).
describe("stepActionChip — 근로자 화면 동작 꼬리표", () => {
  it("문장의 동사 그대로 꼬리표를 만든다", () => {
    expect(stepActionChip("박스 바닥 덮개를 접으세요")).toEqual({ label: "접기", action: "pack" });
    expect(stepActionChip("상자 수량을 확인하세요")).toEqual({ label: "확인하기", action: "observe" });
    expect(stepActionChip("밀대로 바닥을 닦으세요.")).toEqual({ label: "닦기", action: "clean" });
  });

  it("꾸미는 말이 아니라 마지막 서술어를 본다", () => {
    expect(stepActionChip("포장된 상자를 카트에 놓으세요. 큰 상자는 아래쪽에, 작은 상자는 위쪽에 놓으세요"))
      .toEqual({ label: "놓기", action: "move" });
  });

  it("보조 용언은 앞의 본동사로 읽는다(띄어 쓴 것·붙여 쓴 것)", () => {
    expect(stepActionChip("바닥을 닦아 주세요")?.label).toBe("닦기");
    expect(stepActionChip("상자를 옮겨주세요")?.label).toBe("옮기기");
    expect(stepActionChip("컵을 선반에 올려 놓으세요")?.label).toBe("올리기");
    expect(stepActionChip("화면을 확인해 보세요")?.label).toBe("확인하기");
  });

  it("명사 조각을 동사로 읽지 않는다('입력'의 '입' ≠ 입다)", () => {
    expect(stepActionChip("주문을 입력하세요")?.label).toBe("입력하기");
  });

  it("사전에 없거나 모호한 동사면 꼬리표를 만들지 않는다", () => {
    expect(stepActionChip("손님께 인사하세요")).toBeNull();
    expect(stepActionChip("모자를 쓰세요")).toBeNull(); // 쓰다(착용)·쓸다(청소) 모호
    expect(stepActionChip("손님께 드리세요")).toBeNull(); // 보조 용언만 있다
    expect(stepActionChip("")).toBeNull();
  });

  // 보조 용언(두세요·보세요·놓으세요) 앞의 본동사가 사전에 없으면 보조 용언을 꼬리표로 쓰지 않는다 —
  // "모아 두세요"에 '두기', "밀어 보세요"에 '보기'가 붙던 문제(평가 문장에서 실제로 나왔다).
  it("보조 용언 앞 본동사를 모르면 꼬리표를 숨긴다", () => {
    expect(stepActionChip("빈 박스는 납작하게 접어서 모아 두세요")).toBeNull();
    expect(stepActionChip("우유팩은 씻어서 따로 모아 두세요")).toBeNull();
    expect(stepActionChip("배터리를 충전기에 꽂아 두세요")).toBeNull();
    expect(stepActionChip("인두를 거치대에 꽂아 두세요")).toBeNull();
    expect(stepActionChip("시든 상추는 골라서 따로 빼 두세요")).toBeNull();
    expect(stepActionChip("냉동고 문이 안 닫히면 손으로 밀어 보세요")).toBeNull();
  });

  it("조사 뒤의 두세요·보세요·놓으세요는 본동사로 읽는다", () => {
    expect(stepActionChip("상자를 바닥에 두세요")?.label).toBe("두기");
    expect(stepActionChip("선반을 보세요")?.label).toBe("보기");
    expect(stepActionChip("컵을 쟁반에 놓으세요")?.label).toBe("놓기");
  });

  it("가다·오다가 붙은 이동 동사를 앞 동사로 읽지 않는다(내려가다 ≠ 내리다)", () => {
    expect(stepActionChip("계단 난간을 걸레로 닦으며 내려가세요")).toBeNull();
    expect(stepActionChip("창고로 들어가세요")).toBeNull();
    expect(stepActionChip("계단을 내려 가세요")).toBeNull();
  });

  it("내려놓다는 내리기가 아니라 내려놓기다(붙여 쓴 것·띄어 쓴 것)", () => {
    expect(stepActionChip("택배를 내려놓으세요")?.label).toBe("내려놓기");
    expect(stepActionChip("트레이를 내려 놓으세요")?.label).toBe("내려놓기");
  });

  // 한 단계가 서로 다른 동작 둘을 시키면 마지막 동사만 보여 주는 꼬리표는 틀린 꼬리표다
  // (ai_service decompose._guess_action도 이때 other를 돌려준다).
  it("서로 다른 동작 둘을 시키는 문장에는 꼬리표를 붙이지 않는다", () => {
    expect(stepActionChip("손을 씻고 장갑을 끼세요")).toBeNull();
    expect(stepActionChip("그릇을 세제로 씻으세요. 그 다음 헹구세요")).toBeNull();
    expect(stepActionChip("상자를 접은 뒤 테이프를 붙이세요")).toBeNull();
    expect(stepActionChip("상자를 접어서 카트에 실으세요")).toBeNull();
    expect(stepActionChip("바닥을 닦으며 쓰레기를 치우세요")).toBeNull();
  });

  it("같은 동작을 되풀이하는 문장은 그 동작 꼬리표를 붙인다", () => {
    expect(stepActionChip("포장된 상자를 카트에 놓으세요. 큰 상자는 아래쪽에, 작은 상자는 위쪽에 놓으세요")?.label)
      .toBe("놓기");
    // '창고'·'냉장고'처럼 '-고'로 끝나는 명사는 연결형 동사가 아니다.
    expect(stepActionChip("냉장고 문을 열어 보세요")?.label).toBe("열기");
  });

  it("WorkerActionChip은 확실하지 않으면 아무것도 그리지 않는다", () => {
    const { container } = render(<WorkerActionChip sentence="손님께 인사하세요" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("WorkerActionChip은 저장된 계열 이름이 아니라 문장의 동사를 보여 준다", () => {
    render(<WorkerActionChip sentence="박스 바닥 덮개를 접으세요" />);
    expect(screen.getByTestId("action-chip")).toHaveTextContent("접기");
  });

  it("분류 체계의 모든 계열에 꼬리표 메타가 있다(wear·operate·assemble이 '작업하기'로 뭉개지지 않는다)", () => {
    for (const k of ["wear", "operate", "assemble"]) expect(metaFor(k).label).not.toBe("작업하기");
    expect(metaFor("pack").label).not.toBe("담기");
  });
});
