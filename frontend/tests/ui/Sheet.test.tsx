import { describe, expect, it } from "vitest";
import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Button, Sheet } from "../../src/components/ui";

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        보내기
      </button>
      <Sheet
        open={open}
        onClose={() => setOpen(false)}
        title="보내기 전에 확인해요"
        description="받는 사람을 골라 주세요"
        footer={<Button variant="primary">3명에게 보내기</Button>}
      >
        <label>
          <input type="checkbox" /> 김민지 님
        </label>
      </Sheet>
    </>
  );
}

describe("Sheet(오른쪽 서랍 480)", () => {
  it("열면 이름 있는 dialog가 되고 초점이 안으로 가며, Tab은 안에서만 돈다", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "보내기" }));
    const sheet = screen.getByRole("dialog", { name: "보내기 전에 확인해요" });
    expect(sheet).toHaveClass("max-w-sheet");
    expect(sheet.contains(document.activeElement)).toBe(true);
    for (let i = 0; i < 5; i++) {
      await user.tab();
      expect(sheet.contains(document.activeElement)).toBe(true);
    }
  });

  it("Esc로 닫히고 연 버튼으로 초점이 돌아간다", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "보내기" });
    await user.click(opener);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("[닫기] 아이콘 버튼에 이름이 있고 누르면 닫힌다", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "보내기" }));
    await user.click(screen.getByRole("button", { name: "닫기" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
