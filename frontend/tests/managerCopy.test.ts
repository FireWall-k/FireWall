import { describe, expect, it } from "vitest";
import * as copy from "../src/manager/copy";

// 사업주 문구 사전 전체를 훑는다(명세 6.7, R7). 함수 문구는 예시 값으로 불러 본다.
function allStrings(v: unknown, path = "copy"): [string, string][] {
  if (typeof v === "string") return [[path, v]];
  if (typeof v === "function") {
    const args = Array.from({ length: v.length }, (_, i) => (i === 0 ? 3 : 5));
    const asNum = (v as (...a: unknown[]) => unknown)(...args);
    const asName = (v as (...a: unknown[]) => unknown)(...args.map(() => "김민지"));
    return [...allStrings(asNum, `${path}()`), ...allStrings(asName, `${path}("김민지")`)];
  }
  if (Array.isArray(v)) return v.flatMap((x, i) => allStrings(x, `${path}[${i}]`));
  if (v && typeof v === "object") return Object.entries(v).flatMap(([k, x]) => allStrings(x, `${path}.${k}`));
  return [];
}

const strings = allStrings(copy);

describe("manager/copy.ts 금지어", () => {
  it("문구가 비어 있지 않다(훑기가 실제로 동작함)", () => {
    expect(strings.length).toBeGreaterThan(60);
  });

  it("'AI'·공급자 이름이 없다", () => {
    const bad = strings.filter(([, s]) => /\bAI\b|GPT|OpenAI|ChatGPT|Claude/i.test(s));
    expect(bad).toEqual([]);
  });

  it("'~하세요' 명령 말투가 없다('~하세요 체'라는 이름을 가리키는 점검표 문구만 예외)", () => {
    const bad = strings.filter(([, s]) => /하세요/.test(s.replace("~하세요 체", "")));
    expect(bad).toEqual([]);
  });

  it("영어 enum(draft·needs_check 같은 영어 낱말)이 화면 문구에 없다", () => {
    const bad = strings.filter(([, s]) => /[A-Za-z]{2,}/.test(s));
    expect(bad).toEqual([]);
  });

  it("사람은 '김민지 님'으로 부른다", () => {
    expect(copy.person("김민지")).toBe("김민지 님");
  });
});

describe("contract §3.7 문구(글자 그대로)", () => {
  it("보내기 점검표 code별 문구", () => {
    expect(copy.sendCheck.no_picture(5, 6)).toBe("모든 단계에 그림이 있어요 5/6");
    expect(copy.sendCheck.unconfirmed_auto(2, 4)).toBe("자동으로 고른 그림을 확인했어요 2/4");
    expect(copy.sendCheck.unreviewed_split(1, 3)).toBe("자동으로 나눈 문장을 확인했어요 1/3");
    expect(copy.sendCheck.too_long(2)).toBe("긴 문장이 2개 있어요");
    expect(copy.sendCheck.command_tone(1)).toBe("~하세요 체 문장이 1개 있어요");
    expect(copy.sendCheck.auto_caution(3)).toBe("✦ 자동으로 켠 조심 표시가 3개 있어요");
  });

  it("sendCheckLabel: code와 숫자로 문장을 만들고, 모르는 code는 영어를 보이지 않는다", () => {
    expect(copy.sendCheckLabel("no_picture", { done: 5, total: 6 })).toBe("모든 단계에 그림이 있어요 5/6");
    expect(copy.sendCheckLabel("too_long", { count: 2 })).toBe("긴 문장이 2개 있어요");
    const unknown = copy.sendCheckLabel("brand_new_code", { count: 2 });
    expect(unknown).not.toMatch(/[A-Za-z]/);
    expect(unknown).toBe("확인할 것이 2개 있어요");
  });

  it("보내기 시트·토스트·덧줄·툴팁·미리 체크·VersionNotice", () => {
    expect(copy.sendSheet.title).toBe("보내기 전에 확인해요");
    expect(copy.sendSheet.sentToast(3)).toBe("3명에게 보냈어요 · 현황 보기");
    expect(copy.sendSheet.inProgressNote("김민지")).toBe("김민지 님은 지금 하는 중이라 다음에 보낼 때부터 바뀌어요");
    expect(copy.sendSheet.disabledTooltip(3)).toBe("확인할 것 3개가 남았어요. 확인하면 보낼 수 있어요");
    expect(copy.sendSheet.prefilled).toBe("지난번 받은 사람을 골라 두었어요");
    expect(copy.versionNotice.working(5, 2)).toBe("이 직무를 받은 5명 중 2명이 지금 하고 있어요");
    expect(copy.versionNotice.nextTime).toBe("다음에 보낼 때부터 바뀌어요");
  });

  it("직무 상태·걸러보기·행 배지(contract §2.1)", () => {
    expect(copy.taskState).toEqual({ draft: "초안", published: "보냄", archived: "보관" });
    expect(Object.values(copy.taskFilter)).toEqual(["전체", "초안", "확인 필요", "보냄", "보관"]);
    expect(copy.taskRow.needsCheck(3)).toBe("확인 필요 3");
    expect(copy.taskRow.unsentChanges).toBe("고친 내용 안 보냄");
    expect(copy.taskMenu.editLater).toBe("새 편집기에서 열려요");
  });
});

describe("조사 고르기(명세 6.7: '을(를)' 같은 기계식 표기 대신 자연스러운 말)", () => {
  it("받침을 보고 을/를을 고른다", () => {
    expect(copy.taskToast.archived("컵 씻기")).toBe("'컵 씻기'를 보관함으로 옮겼어요");
    expect(copy.taskDelete.title("옛 창고 정리")).toBe("'옛 창고 정리'를 완전히 지울까요?");
    expect(copy.taskToast.deleted("상자 옮김")).toBe("'상자 옮김'을 완전히 지웠어요");
    expect(copy.dashboardArchive.confirm("분류 작업")).toMatch(/^'분류 작업'을 보관함으로/);
    expect(copy.ui.confirmNameLabel("김민지")).toBe("지우려면 '김민지'를 똑같이 적어 주세요");
  });

  it("끝의 괄호는 건너뛰고, 숫자는 읽는 소리로 본다", () => {
    expect(copy.taskToast.duplicated("앞치마 입기 (복사본)")).toBe("'앞치마 입기 (복사본)'을 새 초안으로 만들었어요");
    expect(copy.taskToast.archived("포장 3")).toBe("'포장 3'을 보관함으로 옮겼어요");
    expect(copy.taskToast.archived("포장 2")).toBe("'포장 2'를 보관함으로 옮겼어요");
  });

  it("(으)로: ㄹ 받침과 받침 없음은 '로', 그 밖의 받침은 '으로'", () => {
    expect(copy.taskList.searchEmpty("컵")).toBe("'컵'으로 찾은 직무가 없어요");
    expect(copy.taskList.searchEmpty("상자")).toBe("'상자'로 찾은 직무가 없어요");
    expect(copy.taskList.searchEmpty("물")).toBe("'물'로 찾은 직무가 없어요");
    expect(copy.taskList.searchEmpty("7")).toBe("'7'로 찾은 직무가 없어요");
  });

  it("한글·숫자로 끝나지 않으면(영어 등) 받침을 모르므로 괄호 표기를 쓴다", () => {
    expect(copy.taskToast.archived("Box")).toBe("'Box'을(를) 보관함으로 옮겼어요");
    expect(copy.taskList.searchEmpty("abc")).toBe("'abc'(으)로 찾은 직무가 없어요");
  });
});
