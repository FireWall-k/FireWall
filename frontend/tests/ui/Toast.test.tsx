import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { ToastProvider, TOAST_MS, useToast, type ToastInput } from "../../src/components/ui";

function Trigger({ input }: { input: ToastInput }) {
  const toast = useToast();
  return (
    <button type="button" onClick={() => toast.show(input)}>
      띄우기
    </button>
  );
}

function setup(input: ToastInput) {
  render(
    <ToastProvider>
      <Trigger input={input} />
    </ToastProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "띄우기" }));
}

afterEach(() => {
  vi.useRealTimers();
});

describe("Toast(오른쪽 아래, role=status)", () => {
  it("성공 토스트는 role=status이고 5초 뒤 저절로 닫힌다", () => {
    vi.useFakeTimers();
    setup({ message: "보관했어요" });
    expect(screen.getByRole("status")).toHaveTextContent("보관했어요");
    act(() => {
      vi.advanceTimersByTime(TOAST_MS - 100);
    });
    expect(screen.getByRole("status")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("오류 토스트는 10초가 지나도 남아 있고 [닫기]로만 닫힌다", () => {
    vi.useFakeTimers();
    setup({ tone: "error", message: "저장하지 못했어요 · 다시 시도해 주세요" });
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    const t = screen.getByRole("status");
    expect(t).toHaveTextContent("저장하지 못했어요");
    expect(t).toHaveAttribute("data-tone", "error");
    fireEvent.click(screen.getByRole("button", { name: "닫기" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("[실행 취소]를 누르면 되돌리고 토스트를 닫는다", () => {
    const onUndo = vi.fn();
    setup({ message: "보관했어요", onUndo });
    fireEvent.click(screen.getByRole("button", { name: "실행 취소" }));
    expect(onUndo).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("마우스나 초점이 올라가 있으면 닫히지 않고 기다린다", () => {
    vi.useFakeTimers();
    setup({ message: "보관했어요", onUndo: () => {} });
    fireEvent.mouseEnter(screen.getByRole("status"));
    act(() => {
      vi.advanceTimersByTime(TOAST_MS * 3);
    });
    expect(screen.getByRole("status")).toBeInTheDocument();
    fireEvent.mouseLeave(screen.getByRole("status"));
    act(() => {
      vi.advanceTimersByTime(TOAST_MS + 10);
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("행동 버튼('현황 보기')을 누르면 그 행동을 하고 닫힌다", () => {
    const onClick = vi.fn();
    setup({ message: "3명에게 보냈어요", action: { label: "현황 보기", onClick } });
    fireEvent.click(screen.getByRole("button", { name: "현황 보기" }));
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("Provider 밖에서 useToast는 아무 일도 하지 않는다(옛 화면 단독 시험)", () => {
    render(<Trigger input={{ message: "x" }} />);
    fireEvent.click(screen.getByRole("button", { name: "띄우기" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("[닫기](X)로 닫으면 초점이 body로 사라지지 않고 띄우기 직전 자리로 돌아간다", () => {
    render(
      <ToastProvider>
        <Trigger input={{ tone: "error", message: "보관하지 못했어요" }} />
      </ToastProvider>,
    );
    const opener = screen.getByRole("button", { name: "띄우기" });
    opener.focus();
    fireEvent.click(opener);
    const close = screen.getByRole("button", { name: "닫기" });
    close.focus();
    fireEvent.click(close);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(opener);
  });

  it("[닫기](X): 다른 토스트가 있으면 그 단추로, 돌아갈 곳이 없으면 본문(#main)으로 초점을 옮긴다", () => {
    function Two() {
      const toast = useToast();
      return (
        <>
          <main id="main" tabIndex={-1}>
            본문
          </main>
          <button
            type="button"
            onClick={() => {
              toast.show({ tone: "error", message: "첫째" });
              toast.show({ tone: "error", message: "둘째" });
            }}
          >
            둘 띄우기
          </button>
        </>
      );
    }
    render(
      <ToastProvider>
        <Two />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "둘 띄우기" }));
    const [first, second] = screen.getAllByRole("status");
    const close2 = second.querySelector("button")!;
    close2.focus();
    fireEvent.click(close2);
    expect(document.activeElement).not.toBe(document.body);
    expect(first.contains(document.activeElement)).toBe(true);
    const close1 = first.querySelector("button")!;
    close1.focus();
    fireEvent.click(close1);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(document.getElementById("main"));
  });

  it("확인 창이 열려 있는 동안 토스트 층은 창 아래(z-40)로 내려가고 inert가 된다", async () => {
    const { Dialog } = await import("../../src/components/ui");
    function WithDialog({ open }: { open: boolean }) {
      return (
        <ToastProvider>
          <Trigger input={{ message: "보관했어요", onUndo: () => {} }} />
          <Dialog open={open} onClose={() => {}} title="지울까요?" onConfirm={() => {}} />
        </ToastProvider>
      );
    }
    const { rerender, container } = render(<WithDialog open={false} />);
    fireEvent.click(screen.getByRole("button", { name: "띄우기" }));
    const layer = container.querySelector<HTMLElement>("[data-toast-layer]")!;
    expect(layer).toHaveClass("z-[60]");
    expect(layer).not.toHaveAttribute("inert");
    rerender(<WithDialog open />);
    expect(layer).toHaveClass("z-40");
    expect(layer).toHaveAttribute("inert");
    rerender(<WithDialog open={false} />);
    expect(layer).toHaveClass("z-[60]");
    expect(layer).not.toHaveAttribute("inert");
  });
});

describe("토스트 층 위치(2회차 검증)", () => {
  it("휴대폰 아래 자리는 --toast-bottom으로 올릴 수 있다(편집기 아래 고정 줄을 덮지 않게)", () => {
    render(<ToastProvider>{null}</ToastProvider>);
    const layer = document.querySelector("[data-toast-layer]")!;
    expect(layer.className).toMatch(/bottom-\[var\(--toast-bottom,5rem\)\]/);
  });
});

