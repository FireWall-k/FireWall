import { describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Dialog } from "../../src/components/ui";

function Harness(props: Partial<Parameters<typeof Dialog>[0]> & { onConfirm?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        열기
      </button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="직무를 보관할까요?"
        description="보관한 직무는 보관함에서 다시 꺼낼 수 있어요."
        onConfirm={props.onConfirm ?? (() => setOpen(false))}
        confirmLabel="보관하기"
        {...props}
      />
    </>
  );
}

describe("Dialog(window.confirm 대신)", () => {
  it("열리면 창 안으로 초점이 가고, Tab은 창 안에서만 돈다", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "열기" }));
    const dialog = screen.getByRole("dialog", { name: "직무를 보관할까요?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleDescription("보관한 직무는 보관함에서 다시 꺼낼 수 있어요.");
    expect(dialog.contains(document.activeElement)).toBe(true);
    for (let i = 0; i < 6; i++) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
    await user.tab({ shift: true });
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("Esc로 닫히고, 닫히면 연 버튼으로 초점이 돌아간다", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "열기" });
    await user.click(opener);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("[보관하기]를 누르면 onConfirm을 부른다", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<Harness onConfirm={onConfirm} />);
    await user.click(screen.getByRole("button", { name: "열기" }));
    await user.click(screen.getByRole("button", { name: "보관하기" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("위험 창: 지워지는 것 목록을 보이고, 처음 초점은 [취소]", async () => {
    const user = userEvent.setup();
    render(
      <Harness
        tone="danger"
        title="완전히 지울까요?"
        confirmLabel="완전히 지우기"
        items={["단계 6개", "그림 6장", "보낸 기록 3건"]}
      />,
    );
    await user.click(screen.getByRole("button", { name: "열기" }));
    const dialog = screen.getByRole("alertdialog", { name: "완전히 지울까요?" });
    expect(dialog).toHaveTextContent("함께 지워지는 것");
    expect(dialog.querySelectorAll("li")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "취소" })).toHaveFocus();
  });

  it("위험 창 이름 다시 적기: 이름이 틀리면 [지우기]가 눌리지 않는다", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(<Harness tone="danger" title="근로자를 지울까요?" confirmLabel="지우기" confirmName="김민지" onConfirm={onConfirm} />);
    await user.click(screen.getByRole("button", { name: "열기" }));
    const del = screen.getByRole("button", { name: "지우기" });
    expect(del).toBeDisabled();
    const input = screen.getByLabelText("지우려면 '김민지'을(를) 똑같이 적어 주세요");
    await user.type(input, "김민");
    expect(del).toBeDisabled();
    await user.type(input, "지");
    expect(del).toBeEnabled();
    await user.click(del);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("처리 중(busy)에는 Esc·[취소]로 닫히지 않는다", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Dialog open onClose={onClose} title="보내는 중" onConfirm={() => {}} busy />);
    await user.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "취소" })).toBeDisabled();
  });
});
