import { describe, expect, it } from "vitest";
import { COPY, FORBIDDEN_PATTERNS, josa, toWorkerMessage } from "../src/worker/copy";
import { ApiError, AuthError, NetworkError } from "../src/apiErrors";

// 함수형 문구의 예시 인자(경로별). 새 함수 문구를 더하면 여기에도 더한다 — 없으면 아래 테스트가 알려 준다.
const SAMPLE_ARGS: Record<string, unknown[]> = {
  "COPY.home.greeting": ["민수"],
  "COPY.home.todayCount": [3],
  "COPY.card.resume": [3],
  "COPY.start.title": ["컵 씻기"],
  "COPY.start.stepCount": [6],
  "COPY.step.srProgress": [3, 6],
  "COPY.done.title": ["바닥 닦기"],
  "COPY.done.nextPreview": ["컵 씻기"],
  "COPY.history.date": [new Date(2026, 10, 6)],
};

// 문구 사전의 모든 문자열을 꺼낸다. 함수형 문구는 예시 인자로 불러 결과를 검사한다.
function allStrings(node: unknown, path = "COPY"): [string, string][] {
  if (typeof node === "string") return [[path, node]];
  if (typeof node === "function") {
    const args = SAMPLE_ARGS[path];
    if (!args) throw new Error(`${path}의 예시 인자가 SAMPLE_ARGS에 없다`);
    return [[`${path}()`, String((node as (...a: unknown[]) => unknown)(...args))]];
  }
  if (node && typeof node === "object") {
    return Object.entries(node).flatMap(([k, v]) => allStrings(v, `${path}.${k}`));
  }
  return [];
}

describe("근로자 문구 사전(명세 4.14)", () => {
  const strings = allStrings(COPY);

  it("문구가 비어 있지 않다(대조군)", () => {
    expect(strings.length).toBeGreaterThan(80);
  });

  it("모든 문구에 금지 표현이 없다(영어·사업주·접속 코드·오류·분수·~합니다·~하세요)", () => {
    const bad = strings.flatMap(([path, text]) =>
      FORBIDDEN_PATTERNS.filter((re) => re.test(text)).map((re) => `${path}: "${text}" ← ${re}`),
    );
    expect(bad).toEqual([]);
  });

  it("금지 목록이 실제로 잡는다(대조군)", () => {
    for (const sample of ["Failed to fetch", "사업주에게", "접속 코드", "로그아웃", "오류", "1 / 4", "확인합니다", "확인하세요", "JOB CARD"]) {
      expect(FORBIDDEN_PATTERNS.some((re) => re.test(sample)), sample).toBe(true);
    }
    // 인사 '안녕하세요'는 허용한다.
    expect(FORBIDDEN_PATTERNS.some((re) => re.test("민수 님, 안녕하세요"))).toBe(false);
  });

  it("사업주는 근로자에게 '선생님'이다(창업자 결정 1)", () => {
    expect(COPY.help.sent).toBe("선생님을 불렀어요. 여기서 기다려요.");
    expect(COPY.status.unpaired.body).toBe("선생님께 말해 주세요.");
    expect(COPY.btn.teacherSetup).toBe("선생님용: 기기 연결하기");
  });

  it("함수형 문구", () => {
    expect(COPY.home.greeting("민수")).toBe("민수 님, 안녕하세요");
    expect(COPY.home.todayCount(3)).toBe("오늘 할 일 3개");
    expect(COPY.card.resume(3)).toBe("3단계부터 이어서 해요");
    expect(COPY.start.title("컵 씻기")).toBe("컵 씻기를 시작해요");
    expect(COPY.done.title("바닥 청소")).toBe("바닥 청소를 다 했어요");
    expect(COPY.done.title("컵 정리")).toBe("컵 정리를 다 했어요");
    expect(COPY.done.title("상자 옮김")).toBe("상자 옮김을 다 했어요");
    expect(COPY.step.srProgress(3, 6)).toBe("6단계 중 3단계");
    expect(COPY.history.date(new Date(2026, 10, 6))).toBe("11월 6일 금요일");
  });
});

describe("josa(받침에 맞는 조사)", () => {
  it.each([
    ["컵", "을/를", "컵을"],
    ["접시", "을/를", "접시를"],
    ["물", "이/가", "물이"],
    ["바닥", "은/는", "바닥은"],
    ["걸레", "은/는", "걸레는"],
    ["1번 상자", "을/를", "1번 상자를"],
    ["상자 3", "을/를", "상자 3을"],
    ["상자 2", "을/를", "상자 2를"],
    ["칼", "으로/로", "칼로"],
    ["솔", "으로/로", "솔로"],
    ["손", "으로/로", "손으로"],
    ["행주", "으로/로", "행주로"],
  ] as const)("%s + %s → %s", (word, pair, out) => {
    expect(josa(word, pair)).toBe(out);
  });
});

describe("toWorkerMessage(오류 → 근로자 화면 종류)", () => {
  it.each([
    [new NetworkError(), "offline"],
    [new TypeError("Failed to fetch"), "offline"],
    [new AuthError(), "expired"],
    [new ApiError(401, "사업장 코드 또는 접속 코드가 올바르지 않습니다."), "wrong_code"],
    [new ApiError(429, "로그인 시도가 너무 많습니다."), "too_many"],
    [new ApiError(404, "배정을 찾을 수 없습니다."), "gone"],
    [new ApiError(400, "이 배정에 속하지 않는 단계입니다."), "gone"],
    [new ApiError(500, null), "error"],
    [new ApiError(503, null), "error"],
    [new Error("Something odd"), "error"],
    ["문자열", "error"],
    [undefined, "error"],
  ] as const)("%s → %s", (err, kind) => {
    expect(toWorkerMessage(err)).toBe(kind);
  });
});
