import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { StatusScreen, LOADING_RETRY_MS, LOADING_SLOW_MS, type StatusKind } from "../src/worker/ui/StatusScreen";
import { ConfirmScreen } from "../src/worker/ui/ConfirmScreen";
import { PrimaryAction, SecondaryAction, TAP_DEBOUNCE_MS } from "../src/worker/ui/WorkerButton";
import { FORBIDDEN_PATTERNS } from "../src/worker/copy";
import { IconHelp } from "../src/ui/icons";

// 근로자 공통 부품(FOUNDATION): 상태 화면 6종(명세 4.9), 확인 화면(4.10), 버튼 두 가지(7.1).
beforeEach(() => {
  (window.speechSynthesis.speak as ReturnType<typeof vi.fn>).mockClear();
});
afterEach(() => {
  vi.useRealTimers();
});

function expectNoForbidden(el: HTMLElement) {
  const text = el.textContent ?? "";
  for (const re of FORBIDDEN_PATTERNS) expect(text, `${re}`).not.toMatch(re);
}

describe("StatusScreen", () => {
  it.each([
    ["empty", "아직 받은 일이 없어요", "선생님이 일을 보내면 여기에 나와요.", "새로 보기", "status"],
    ["offline", "인터넷이 안 돼요", "와이파이를 확인해 주세요.", "다시 해 보기", "alert"],
    ["error", "잠깐 문제가 생겼어요", "조금 뒤에 다시 해 봐요.", "다시 해 보기", "alert"],
    ["expired", "다시 들어와 주세요", null, "번호 다시 넣기", "alert"],
  ] as const)("%s: 제목·본문·주 버튼·역할", (kind, title, body, action, role) => {
    const onAction = vi.fn();
    render(<StatusScreen kind={kind as StatusKind} onAction={onAction} />);
    const live = screen.getByRole(role);
    expect(live).toHaveTextContent(title);
    if (body) expect(live).toHaveTextContent(body);
    fireEvent.click(screen.getByRole("button", { name: action }));
    expect(onAction).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(title);
    expectNoForbidden(screen.getByTestId("status-screen"));
  });

  it("offline: 받아 둔 일이 있으면 덧붙인다", () => {
    render(<StatusScreen kind="offline" hasCachedWork onAction={() => {}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("받아 둔 일은 할 수 있어요.");
  });

  it("unpaired: 주 버튼 없이 작은 [선생님용: 기기 연결하기]만", () => {
    const onSecondary = vi.fn();
    render(<StatusScreen kind="unpaired" onAction={() => {}} onSecondary={onSecondary} />);
    expect(screen.getByRole("status")).toHaveTextContent("이 기기를 아직 연결하지 않았어요");
    expect(screen.getAllByRole("button")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "선생님용: 기기 연결하기" }));
    expect(onSecondary).toHaveBeenCalled();
  });

  it("loading: 8초 뒤 '조금 오래 걸려요', 20초 뒤 [다시 해 보기]", () => {
    vi.useFakeTimers();
    render(<StatusScreen kind="loading" onAction={() => {}} />);
    expect(screen.getByRole("status")).toHaveTextContent("일을 가져오고 있어요");
    expect(screen.queryByText("조금 오래 걸려요. 기다려 주세요.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(LOADING_SLOW_MS); });
    expect(screen.getByText("조금 오래 걸려요. 기다려 주세요.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(LOADING_RETRY_MS - LOADING_SLOW_MS); });
    expect(screen.getByRole("button", { name: "다시 해 보기" })).toBeInTheDocument();
  });

  it("speak면 제목을 소리로 읽는다(속도는 근로자 설정)", () => {
    render(<StatusScreen kind="empty" speak ttsRate={0.8} onAction={() => {}} />);
    const speak = window.speechSynthesis.speak as ReturnType<typeof vi.fn>;
    expect(speak).toHaveBeenCalledTimes(1);
    expect(speak.mock.calls[0][0]).toMatchObject({ text: "아직 받은 일이 없어요", lang: "ko-KR", rate: 0.8 });
  });

  it("그림은 이모지가 아닌 SVG이고 화면 읽기에서 숨는다", () => {
    const { container } = render(<StatusScreen kind="error" onAction={() => {}} />);
    const svg = container.querySelector("svg[data-illustration]");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(container.textContent).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});

describe("ConfirmScreen", () => {
  it("나가기: 제목·본문, 위가 [계속할래요](초점), 아래가 [멈출래요]", () => {
    const onStay = vi.fn();
    const onLeave = vi.fn();
    render(<ConfirmScreen kind="exit" onStay={onStay} onLeave={onLeave} />);
    expect(screen.getByRole("dialog", { name: "일을 멈출까요?" })).toHaveTextContent("나중에 이어서 할 수 있어요.");
    const [first, second] = screen.getAllByRole("button");
    expect(first).toHaveTextContent("계속할래요");
    expect(second).toHaveTextContent("멈출래요");
    expect(first).toHaveFocus();
    fireEvent.click(first);
    expect(onStay).toHaveBeenCalled();
    fireEvent.click(second);
    expect(onLeave).toHaveBeenCalled();
  });

  it("끝내기: [아니요, 계속할래요] / [네, 끝낼래요]", () => {
    render(<ConfirmScreen kind="end" onStay={() => {}} onLeave={() => {}} />);
    expect(screen.getByRole("dialog", { name: "오늘 일을 끝낼까요?" })).toBeInTheDocument();
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["아니요, 계속할래요", "네, 끝낼래요"]);
  });
});

describe("PrimaryAction / SecondaryAction", () => {
  it("600ms 안의 두 번째 누름은 무시한다(손 떨림으로 단계를 건너뛰지 않게)", () => {
    vi.useFakeTimers();
    const onPress = vi.fn();
    render(<PrimaryAction onPress={onPress}>다 했어요</PrimaryAction>);
    const b = screen.getByRole("button", { name: "다 했어요" });
    fireEvent.click(b);
    fireEvent.click(b);
    expect(onPress).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(TAP_DEBOUNCE_MS);
    fireEvent.click(b);
    expect(onPress).toHaveBeenCalledTimes(2);
  });

  it("busy면 누름을 막고 aria-busy, pressed면 aria-pressed", () => {
    const onPress = vi.fn();
    render(
      <>
        <PrimaryAction onPress={onPress} busy>들어가기</PrimaryAction>
        <SecondaryAction onPress={() => {}} pressed icon={IconHelp}>불렀어요</SecondaryAction>
      </>,
    );
    const busy = screen.getByRole("button", { name: "들어가기" });
    fireEvent.click(busy);
    expect(onPress).not.toHaveBeenCalled();
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button", { name: "불렀어요" })).toHaveAttribute("aria-pressed", "true");
  });

  it("크기 토큰: 주 88px·28px 글씨, 보조 80px·24px 글씨, 글자 줄바꿈 없음", () => {
    render(
      <>
        <PrimaryAction onPress={() => {}}>다 했어요</PrimaryAction>
        <SecondaryAction onPress={() => {}}>이전</SecondaryAction>
      </>,
    );
    const p = screen.getByRole("button", { name: "다 했어요" });
    const s = screen.getByRole("button", { name: "이전" });
    expect(p).toHaveClass("min-h-touch-lg", "text-worker-title", "bg-worker-primary", "whitespace-nowrap");
    expect(s).toHaveClass("min-h-touch", "text-worker", "border-worker-line", "whitespace-nowrap");
  });
});
