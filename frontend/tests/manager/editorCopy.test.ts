import { describe, expect, it } from "vitest";
import * as copy from "../../src/manager/copy";
import { toHaeyo } from "../../src/manager/tasks/editor/review";

// 2b-1 문구(contract §3.7은 글자 그대로, 명세 5.5·5.10). 금지어 검사는 tests/managerCopy.test.ts가 copy.ts 전체를 훑는다.
describe("contract §3.7 고정 문구", () => {
  it("보내기 시트·토스트·덧줄·툴팁·미리 체크 안내", () => {
    expect(copy.sendSheet.title).toBe("보내기 전에 확인해요");
    expect(copy.sendSheet.sentToast(3)).toBe("3명에게 보냈어요 · 현황 보기");
    // 화면은 글과 [현황 보기] 단추로 나눠 그리지만 합치면 같은 문구다.
    expect(`${copy.sendSheet.sentMessage(3)} · ${copy.sendSheet.viewStatus}`).toBe(copy.sendSheet.sentToast(3));
    expect(copy.sendSheet.inProgressNote("김민지")).toBe("김민지 님은 지금 하는 중이라 다음에 보낼 때부터 바뀌어요");
    expect(copy.sendSheet.disabledTooltip(3)).toBe("확인할 것 3개가 남았어요. 확인하면 보낼 수 있어요");
    expect(copy.sendSheet.prefilled).toBe("지난번 받은 사람을 골라 두었어요");
    expect(copy.sendCheck.auto_caution(2)).toBe("✦ 자동으로 켠 조심 표시가 2개 있어요");
  });

  it("VersionNotice", () => {
    expect(copy.versionNotice.working(3, 1)).toBe("이 직무를 받은 3명 중 1명이 지금 하고 있어요");
    expect(copy.versionNotice.nextTime).toBe("다음에 보낼 때부터 바뀌어요");
  });

  it("오늘 상태 문구(contract §3.6)", () => {
    expect(copy.sendSheet.status.done).toBe("오늘 이미 다 했어요 · 한 번 더 보내요");
    expect(copy.sendSheet.status.in_progress).toBe("지금 하는 중이라 다음부터 바뀌어요");
    expect(copy.sendSheet.status.not_started).toBe("아직 시작 전이에요");
  });
});

describe("편집기 문구(명세 5.5)", () => {
  it("그림 4상태와 문장 점검", () => {
    expect(copy.pictureStatus).toEqual({ confirmed: "확인함", auto_high: "✦ 자동 · 확인 필요", choose: "골라 주세요", none: "그림 없음" });
    expect(copy.editor.lint.too_long).toBe("20자가 넘어요");
    expect(copy.editor.lint.hard_word("적재", "쌓기")).toBe("어려운 말: 적재 → 쌓기");
    expect(copy.editor.lint.command_tone).toBe("~해요 체로 바꾸기");
    expect(copy.reviewQueue.remaining(3)).toBe("확인할 것 3개 남음");
    expect(copy.saveState.saved("방금")).toBe("저장됨 · 방금");
    expect(copy.saveState.saving).toBe("저장하는 중…");
    expect(copy.editorProgress.pictures).toBe("그림을 고르고 있어요");
    expect(copy.editorProgress.voice).toBe("목소리를 만들고 있어요");
    expect(copy.overview.confirmAll).toBe("보이는 자동 그림 모두 맞아요");
  });

  it("'동작이 2개' 알림 문구가 편집기 사전에 없다(나누기는 입력 화면에서 끝냄)", () => {
    expect(JSON.stringify(copy)).not.toMatch(/동작이 2개|동작이 둘/);
  });

  it("✦는 확인하지 않은 자동 결과 문구에만 쓴다", () => {
    const withSparkle = [
      copy.pictureStatus.auto_high, copy.editor.source.auto, copy.editor.cautionAuto, copy.sendCheck.auto_caution(1),
    ];
    for (const s of withSparkle) expect(s).toMatch(/^✦ /);
    for (const s of [copy.pictureStatus.confirmed, copy.pictureStatus.choose, copy.pictureStatus.none, copy.editor.source.manual]) {
      expect(s).not.toMatch(/✦/);
    }
  });

  it("'~하세요' 체 문장을 '~해요'로", () => {
    expect(toHaeyo("라벨을 붙이세요")).toBe("라벨을 붙이세요"); // '~이세요'는 규칙으로 못 바꾼다(그대로)
    expect(toHaeyo("바닥을 청소하세요.")).toBe("바닥을 청소해요.");
    expect(toHaeyo("문을 확인하십시오")).toBe("문을 확인해요");
  });
});
