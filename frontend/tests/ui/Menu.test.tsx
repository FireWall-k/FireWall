import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IconButton, Menu, Tooltip, Kbd, Badge, StatusDot, Avatar, AvatarGroup, EmptyState, Button } from "../../src/components/ui";

function RowMenu({ onArchive = vi.fn(), onDuplicate = vi.fn() }) {
  return (
    <Menu
      label="컵 씻기 메뉴"
      items={[
        { id: "edit", label: "고치기", disabled: true, hint: "새 편집기에서 열려요" },
        { id: "dup", label: "복제해서 고치기", onSelect: onDuplicate },
        { id: "archive", label: "보관하기", onSelect: onArchive },
      ]}
      trigger={(p) => <IconButton {...p} aria-label="컵 씻기 메뉴" icon="…" />}
    />
  );
}

describe("Menu(… 메뉴)", () => {
  it("열면 첫 항목에 초점, ↓/↑로 옮기고(맨 끝에서 처음으로) Enter로 고른다", async () => {
    const user = userEvent.setup();
    const onArchive = vi.fn();
    render(<RowMenu onArchive={onArchive} />);
    const trigger = screen.getByRole("button", { name: "컵 씻기 메뉴" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu", { name: "컵 씻기 메뉴" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /^고치기/ })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: /복제해서 고치기/ })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: /보관하기/ })).toHaveFocus();
    await user.keyboard("{ArrowDown}"); // 끝에서 처음으로
    expect(screen.getByRole("menuitem", { name: /^고치기/ })).toHaveFocus();
    await user.keyboard("{ArrowUp}{Enter}");
    expect(onArchive).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("꺼 둔 항목도 키보드 초점을 받아 이유를 읽을 수 있고, Enter·Space로는 아무 일도 없다(WAI-ARIA APG)", async () => {
    const user = userEvent.setup();
    const onArchive = vi.fn();
    const onDuplicate = vi.fn();
    render(<RowMenu onArchive={onArchive} onDuplicate={onDuplicate} />);
    const trigger = screen.getByRole("button", { name: "컵 씻기 메뉴" });
    trigger.focus();
    await user.keyboard("{ArrowUp}"); // 위로 열면 마지막 항목
    expect(screen.getByRole("menuitem", { name: /보관하기/ })).toHaveFocus();
    await user.keyboard("{Home}");
    const edit = screen.getByRole("menuitem", { name: "고치기 새 편집기에서 열려요" });
    expect(edit).toHaveFocus();
    await user.keyboard("{Enter}");
    await user.keyboard(" ");
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(edit).toHaveFocus();
    expect(onArchive).not.toHaveBeenCalled();
    expect(onDuplicate).not.toHaveBeenCalled();
    await user.keyboard("{End}");
    expect(screen.getByRole("menuitem", { name: /보관하기/ })).toHaveFocus();
  });

  it("쓸 수 없는 항목은 aria-disabled와 이유를 보이고, 눌러도 아무 일도 없다", async () => {
    const user = userEvent.setup();
    render(<RowMenu />);
    await user.click(screen.getByRole("button", { name: "컵 씻기 메뉴" }));
    // 보이는 글이 모두 이름에 든다(라벨 + 이유, WCAG 2.5.3)
    const edit = screen.getByRole("menuitem", { name: "고치기 새 편집기에서 열려요" });
    expect(edit).toHaveAttribute("aria-disabled", "true");
    await user.click(edit);
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("Esc로 닫히고 단추로 초점이 돌아간다", async () => {
    const user = userEvent.setup();
    render(<RowMenu />);
    const trigger = screen.getByRole("button", { name: "컵 씻기 메뉴" });
    await user.click(trigger);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("바깥을 누르면 닫힌다", async () => {
    const user = userEvent.setup();
    render(
      <>
        <RowMenu />
        <p>바깥</p>
      </>,
    );
    await user.click(screen.getByRole("button", { name: "컵 씻기 메뉴" }));
    await user.click(screen.getByText("바깥"));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});

describe("Tooltip·Kbd·Badge·Avatar·EmptyState", () => {
  it("Tooltip: 초점이 가면 보이고 설명으로 읽히며 Esc로 숨는다", async () => {
    const user = userEvent.setup();
    render(
      <Tooltip content="확인할 것 3개가 남았어요. 확인하면 보낼 수 있어요">
        <Button aria-disabled="true">보내기</Button>
      </Tooltip>,
    );
    const btn = screen.getByRole("button", { name: "보내기" });
    expect(screen.getByRole("tooltip", { hidden: true })).not.toBeVisible();
    await user.tab();
    expect(btn).toHaveFocus();
    expect(screen.getByRole("tooltip")).toBeVisible();
    expect(btn).toHaveAccessibleDescription("확인할 것 3개가 남았어요. 확인하면 보낼 수 있어요");
    await user.keyboard("{Escape}");
    expect(screen.getByRole("tooltip", { hidden: true })).not.toBeVisible();
  });

  it("Kbd는 kbd 요소", () => {
    render(<Kbd>Ctrl</Kbd>);
    expect(screen.getByText("Ctrl").tagName).toBe("KBD");
  });

  it("Badge는 색 + 아이콘 + 글, auto는 ✦", () => {
    const { container } = render(
      <>
        <Badge tone="warning">확인 필요 3</Badge>
        <Badge tone="auto">자동</Badge>
        <StatusDot tone="success">다 함</StatusDot>
      </>,
    );
    const warn = screen.getByText("확인 필요 3");
    expect(warn.querySelector("svg")).not.toBeNull();
    expect(screen.getByText("자동")).toHaveTextContent("✦ 자동".replace(" ", ""));
    expect(container).toHaveTextContent("다 함");
  });

  it("AvatarGroup: 3명까지 보이고 나머지는 +n", () => {
    render(
      <AvatarGroup
        label="받은 사람 5명"
        people={[
          { id: "1", initials: "김" },
          { id: "2", initials: "이" },
          { id: "3", initials: "박" },
        ]}
        more={2}
      />,
    );
    expect(screen.getByRole("group", { name: "받은 사람 5명" })).toHaveTextContent("김이박+2");
    render(<Avatar initials="김" label="김민지 님" />);
    expect(screen.getByRole("img", { name: "김민지 님" })).toBeInTheDocument();
  });

  it("EmptyState는 불러오는 중·비어 있음·오류를 모양으로 구분한다", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const { rerender, container } = render(<EmptyState kind="loading" />);
    expect(screen.getByRole("status")).toHaveTextContent("불러오는 중이에요");
    expect(container.firstElementChild).toHaveAttribute("data-state", "loading");

    rerender(<EmptyState kind="empty" title="아직 만든 직무가 없어요" actions={<Button>새 직무 만들기</Button>} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText("아직 만든 직무가 없어요")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "새 직무 만들기" })).toBeInTheDocument();

    rerender(<EmptyState kind="error" onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("불러오지 못했어요");
    await user.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(onRetry).toHaveBeenCalled();
  });
});
