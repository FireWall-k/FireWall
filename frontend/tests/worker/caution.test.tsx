import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DEFAULT_A11Y_PREFS, type Step } from "../../src/api";
import { COPY, FORBIDDEN_PATTERNS } from "../../src/worker/copy";
import { StepPlayer, type StepPlayerProps } from "../../src/worker/StepPlayer";
import { normalizeJob } from "../../src/worker/workerApi";
import { cachedJobs, TODAY_CACHE_PREFIX, writeTodayCache } from "../../src/worker/todayCache";

// 2b-1 근로자 '조심해요' 띠(contract §3.5, 명세 4.4-C): safety_flag=true 단계는 그림 상자 위쪽에 40px 글 띠
// (세모 + '조심해요'). 소리는 바꾸지 않는다 — 문장만 읽는다(명세 4.11, 창업자 결정). 띠가 없는 단계는 예전 그대로.
const base: Omit<Step, "id" | "order" | "sentence"> = {
  action_type: "other",
  symbol_url: null,
  symbol_source: "fallback",
  needs_fallback: false,
  tts_audio_url: null,
};
const steps: Step[] = [
  { ...base, id: "s1", order: 1, sentence: "커터칼로 상자를 열어요", safety_flag: true },
  { ...base, id: "s2", order: 2, sentence: "상품을 선반에 놓아요", safety_flag: false },
  { ...base, id: "s3", order: 3, sentence: "손을 씻어요" }, // 예전 서버·캐시: 칸 없음
];

const speak = window.speechSynthesis.speak as ReturnType<typeof vi.fn>;

function setup(index: number, over: Partial<StepPlayerProps> = {}) {
  const props: StepPlayerProps = {
    mode: "live",
    title: "상자 정리",
    steps,
    index,
    doneIds: new Set(),
    prefs: { ...DEFAULT_A11Y_PREFS },
    onDone: vi.fn(),
    onPrev: vi.fn(),
    onExit: vi.fn(),
    ...over,
  };
  return render(<StepPlayer {...props} />);
}

beforeEach(() => speak.mockClear());
afterEach(() => localStorage.clear());

describe("근로자 조심 띠", () => {
  it("safety_flag=true 단계: 그림 상자 안 위쪽에 '조심해요' 글 띠가 뜬다(그림을 하나 더 넣지 않음)", () => {
    setup(0);
    const band = screen.getByTestId("caution-band");
    expect(band).toHaveTextContent(COPY.step.caution);
    expect(band).toHaveTextContent("조심해요");
    const picture = screen.getByTestId("step-picture");
    expect(picture).toContainElement(band);
    expect(picture).toHaveAttribute("data-caution", "true");
    // 띠는 글이다(그림 img가 아님) — 단계 화면의 그림은 여전히 1장 이하.
    expect(document.querySelectorAll("img").length).toBeLessThanOrEqual(1);
    expect(band.className).toMatch(/bg-worker-caution/);
    expect(band.className).toMatch(/text-worker-caution-ink/);
    expect(band.className).toMatch(/h-\[40px\]/);
  });

  it("safety_flag=false와 칸이 없는 단계(예전 서버)에는 띠가 없고 그림 상자 모양도 예전 그대로다", () => {
    const { unmount } = setup(1);
    expect(screen.queryByTestId("caution-band")).toBeNull();
    const pic = screen.getByTestId("step-picture");
    expect(pic).not.toHaveAttribute("data-caution");
    expect(pic.className).toBe(
      "relative size-[100cqmin] overflow-hidden rounded-worker-pic border-2 border-worker-line-soft bg-white hc:border-black",
    );
    unmount();
    setup(2);
    expect(screen.queryByTestId("caution-band")).toBeNull();
  });

  it("소리는 바꾸지 않는다: 띠가 있어도 문장만 읽는다('조심해요.'를 앞에 붙이지 않음)", async () => {
    setup(0);
    // 음성 파일이 없으면 기기 음성으로 문장을 읽는다(자동 재생 1회).
    await vi.waitFor(() => expect(speak).toHaveBeenCalled());
    const said = speak.mock.calls.map((c) => (c[0] as { text: string }).text);
    expect(said).toEqual(["커터칼로 상자를 열어요"]);
    expect(said.join(" ")).not.toMatch(/조심/);
  });

  it("띠 문구는 근로자 금지어 규칙을 지킨다", () => {
    for (const re of FORBIDDEN_PATTERNS) expect(COPY.step.caution).not.toMatch(re);
  });

  it("오늘 할 일 정리(normalizeJob)와 기기 캐시가 safety_flag를 그대로 통과시킨다", () => {
    const job = normalizeJob({ assignment_id: "a1", task_id: "t1", task_title: "상자 정리", steps });
    expect(job.steps.map((s) => s.safety_flag)).toEqual([true, false, undefined]);
    localStorage.removeItem(`${TODAY_CACHE_PREFIX}w1`);
    writeTodayCache("w1", [job]);
    expect(cachedJobs("w1")?.[0].steps[0].safety_flag).toBe(true);
  });
});
