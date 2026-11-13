import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { DEFAULT_A11Y_PREFS, type A11yPrefs, type Step } from "../../src/api";
import { FORBIDDEN_PATTERNS } from "../../src/worker/copy";
import type { HelpController } from "../../src/worker/hooks/useHelp";
import { PRAISE_MS, StepPlayer, type StepPlayerProps } from "../../src/worker/StepPlayer";

// 단계 화면(명세 4.4): 그림 1장 + 문장 1개, 버튼 자리 고정, [다 했어요] 늘 있음, [이전] 자리 유지,
// 600ms 안 두 번 누름은 한 번, 소리 자동 재생은 근로자 설정(창업자 결정 4).
const steps: Step[] = [
  { id: "s1", order: 1, sentence: "컵을 물에 넣어요", action_type: "other", symbol_url: "http://x/a.png", symbol_source: "LOCAL_AAC", needs_fallback: false, tts_audio_url: "http://x/a.mp3" },
  { id: "s2", order: 2, sentence: "컵을 닦아요", action_type: "other", symbol_url: "http://x/b.png", symbol_source: "LOCAL_AAC", needs_fallback: false, tts_audio_url: null },
];

const speak = window.speechSynthesis.speak as ReturnType<typeof vi.fn>;
let playSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  speak.mockClear();
  playSpy = vi.spyOn(Audio.prototype, "play");
});
afterEach(() => {
  playSpy.mockRestore();
  vi.useRealTimers();
});

function setup(over: Partial<StepPlayerProps> & { prefs?: Partial<A11yPrefs> } = {}) {
  const props: StepPlayerProps = {
    mode: "live",
    title: "컵 씻기",
    steps,
    index: 0,
    doneIds: new Set(),
    onDone: vi.fn(),
    onPrev: vi.fn(),
    onExit: vi.fn(),
    ...over,
    prefs: { ...DEFAULT_A11Y_PREFS, ...(over.prefs ?? {}) },
  };
  const utils = render(<StepPlayer {...props} />);
  return { ...utils, props };
}

describe("StepPlayer live", () => {
  it("그림은 한 장(alt 비움 + figcaption 문장), 문장은 h1, 화면에 숫자 진행 없음", () => {
    setup();
    const imgs = document.querySelectorAll("img");
    expect(imgs).toHaveLength(1);
    expect(imgs[0]).toHaveAttribute("alt", "");
    const fig = imgs[0].closest("figure")!;
    expect(fig.querySelector("figcaption")).toHaveTextContent("컵을 물에 넣어요");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("컵을 물에 넣어요");
    expect(screen.getByRole("img", { name: "2단계 중 1단계" })).toBeInTheDocument();
    const visible = screen.getByTestId("step-player").textContent!.replace(/컵 씻기, 2단계 중 1단계/, "");
    expect(visible).not.toMatch(/\d+\s*\/\s*\d+/);
    for (const re of FORBIDDEN_PATTERNS) expect(visible).not.toMatch(re);
  });

  it("버튼: [나가기]·[도와주세요]·[듣기]·[이전](1단계에서도 자리 유지, 비활성)·[다 했어요]", () => {
    setup();
    expect(screen.getByRole("button", { name: "나가기" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "도와주세요" })).toBeNull(); // help를 안 넘기면 없음
    expect(screen.getByRole("button", { name: "이전" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "다 했어요" })).toBeEnabled();
    expect(screen.getByTestId("speak-button")).toBeInTheDocument();
  });

  it("[다 했어요] → 0.4초 '잘했어요' → onDone 한 번(600ms 안 두 번째 누름은 무시)", () => {
    vi.useFakeTimers();
    const { props } = setup();
    const done = screen.getByRole("button", { name: "다 했어요" });
    fireEvent.click(done);
    expect(screen.getByRole("button", { name: "잘했어요" })).toBeInTheDocument();
    fireEvent.click(done);
    act(() => {
      vi.advanceTimersByTime(PRAISE_MS);
    });
    expect(props.onDone).toHaveBeenCalledTimes(1);
    expect(props.onDone).toHaveBeenCalledWith(expect.objectContaining({ index: 0, replayCount: 0, stuck: false }));
    // 단계가 바뀐 직후(첫 누름 뒤 600ms 안)의 누름도 무시한다.
    fireEvent.click(screen.getByRole("button", { name: "다 했어요" }));
    act(() => {
      vi.advanceTimersByTime(PRAISE_MS);
    });
    expect(props.onDone).toHaveBeenCalledTimes(1);
    act(() => {
      vi.advanceTimersByTime(700);
    });
    fireEvent.click(screen.getByRole("button", { name: "다 했어요" }));
    act(() => {
      vi.advanceTimersByTime(PRAISE_MS);
    });
    expect(props.onDone).toHaveBeenCalledTimes(2);
  });

  it("소리 자동 재생 켬(기본): 들어가면 1회 재생, 자동 재생은 다시 듣기로 세지 않는다", () => {
    vi.useFakeTimers();
    const { props } = setup();
    expect(playSpy).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId("speak-button")); // 재생 중 → 멈춤
    fireEvent.click(screen.getByTestId("speak-button")); // 사용자 [듣기]
    expect(playSpy).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "다 했어요" }));
    act(() => {
      vi.advanceTimersByTime(PRAISE_MS);
    });
    expect(props.onDone).toHaveBeenCalledWith(expect.objectContaining({ replayCount: 1 }));
  });

  it("소리 자동 재생 끔(근로자 설정): 들어가도 재생하지 않는다", () => {
    setup({ prefs: { autoplay_sound: false } });
    // 이름이 '듣기'↔'멈춤'으로 바뀌므로 aria-pressed는 쓰지 않는다(3차 검증).
    expect(screen.getByTestId("speak-button")).not.toHaveAttribute("aria-pressed");
    expect(screen.getByTestId("speak-button")).toHaveTextContent("듣기");
    expect(playSpy).not.toHaveBeenCalled();
    expect(speak).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("speak-button"));
    expect(playSpy).toHaveBeenCalledTimes(1);
  });

  it("음성 파일이 없는 단계는 브라우저 음성(tts_rate)으로", () => {
    setup({ index: 1, prefs: { tts_rate: 0.8 } });
    expect(speak).toHaveBeenCalledTimes(1);
    expect(speak.mock.calls[0][0]).toMatchObject({ text: "컵을 닦아요", rate: 0.8, lang: "ko-KR" });
  });

  it("자동 재생이 막히면 [듣기]에 테두리 + '눌러서 들어요'", async () => {
    playSpy.mockImplementation(() => Promise.reject(Object.assign(new Error("blocked"), { name: "NotAllowedError" })));
    setup();
    expect(await screen.findByText("눌러서 들어요")).toBeInTheDocument();
  });

  it("[나가기]는 확인 화면을 거친다", () => {
    vi.useFakeTimers();
    const { props } = setup();
    fireEvent.click(screen.getByRole("button", { name: "나가기" }));
    expect(screen.getByText("일을 멈출까요?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "계속할래요" }));
    expect(props.onExit).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(700); // 600ms 안의 두 번째 누름은 무시되므로 기다린다
    });
    fireEvent.click(screen.getByRole("button", { name: "나가기" }));
    fireEvent.click(screen.getByRole("button", { name: "멈출래요" }));
    expect(props.onExit).toHaveBeenCalled();
  });

  it("도움 띠가 뜨면 오프라인 띠 대신 도움 띠, 오프라인은 위 띠 작은 표시로", () => {
    const help: HelpController = { phase: "sent", request: vi.fn(), cancel: vi.fn(), markStepDone: vi.fn() };
    setup({ help, offline: true, band: <div data-testid="offline-band">끊김</div> });
    expect(screen.getByTestId("help-band")).toHaveTextContent("선생님을 불렀어요. 여기서 기다려요.");
    expect(screen.queryByTestId("offline-band")).toBeNull();
    expect(screen.getByText("인터넷 끊김")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "불렀어요" })).toHaveAttribute("aria-pressed", "true");
  });

  it("끝낸 단계는 진행 점에 체크로 보인다", () => {
    setup({ index: 1, doneIds: new Set(["s1"]) });
    const dots = screen.getByTestId("progress-dots").children;
    expect(dots[0]).toHaveAttribute("data-state", "done");
    expect(dots[1]).toHaveAttribute("data-state", "current");
  });
});

describe("StepPlayer review", () => {
  it("도와주세요 없음, [이전][다음], 자동 재생 끔", () => {
    const onNext = vi.fn();
    setup({ mode: "review", onDone: undefined, onNext });
    expect(screen.queryByRole("button", { name: "도와주세요" })).toBeNull();
    expect(screen.queryByRole("button", { name: "다 했어요" })).toBeNull(); // 첫 단계에서는 없다
    expect(playSpy).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    expect(onNext).toHaveBeenCalled();
  });

  it("마지막 단계: 꺼진 [다음] 대신 [다 했어요] — 누르면 했던 일로 돌아간다", () => {
    const onExit = vi.fn();
    setup({ mode: "review", onDone: undefined, index: steps.length - 1, onExit });
    expect(screen.queryByRole("button", { name: "다음" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "다 했어요" }));
    expect(onExit).toHaveBeenCalled();
  });

  it("다시 보기: 하지 않은 단계는 '안 함'(missed), 일하는 중에는 '남음'(todo)", () => {
    const { unmount } = setup({ mode: "review", onDone: undefined, index: 1, doneIds: new Set() });
    expect(screen.getByTestId("progress-dots").children[0]).toHaveAttribute("data-state", "missed");
    expect(screen.getByTestId("progress-dots").children[1]).toHaveAttribute("data-state", "current");
    unmount();
    setup({ index: 0, doneIds: new Set() });
    expect(screen.getByTestId("progress-dots").children[1]).toHaveAttribute("data-state", "todo");
  });
});
