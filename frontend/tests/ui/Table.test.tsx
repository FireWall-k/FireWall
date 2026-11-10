import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EmptyState, Table, type Column } from "../../src/components/ui";

interface Row {
  id: string;
  title: string;
  steps: number;
}

const rows: Row[] = [
  { id: "a", title: "컵 씻기", steps: 6 },
  { id: "b", title: "출근 준비", steps: 3 },
  { id: "c", title: "바닥 닦기", steps: 9 },
];

const columns: Column<Row>[] = [
  { key: "title", header: "제목", cell: (r) => r.title, sortValue: (r) => r.title },
  { key: "steps", header: "단계 수", cell: (r) => `${r.steps}단계`, sortValue: (r) => r.steps, align: "right" },
  { key: "memo", header: "메모", cell: () => "-", hideBelow: "md" },
];

function titles() {
  return screen
    .getAllByRole("row")
    .slice(1)
    .map((tr) => within(tr).getAllByRole("cell")[0].textContent);
}

describe("Table", () => {
  it("머리는 고정(sticky)되고 표 이름(caption)이 있다", () => {
    render(<Table caption="직무 목록" columns={columns} rows={rows} rowKey={(r) => r.id} />);
    expect(screen.getByRole("table", { name: "직무 목록" })).toBeInTheDocument();
    for (const th of screen.getAllByRole("columnheader")) expect(th).toHaveClass("sticky");
  });

  it("정렬 머리를 누르면 오름차순 → 내림차순, aria-sort가 바뀐다", async () => {
    const user = userEvent.setup();
    render(<Table caption="직무 목록" columns={columns} rows={rows} rowKey={(r) => r.id} />);
    const stepsHeader = screen.getByRole("columnheader", { name: /단계 수/ });
    expect(stepsHeader).toHaveAttribute("aria-sort", "none");
    await user.click(within(stepsHeader).getByRole("button"));
    expect(stepsHeader).toHaveAttribute("aria-sort", "ascending");
    expect(titles()).toEqual(["출근 준비", "컵 씻기", "바닥 닦기"]);
    await user.click(within(stepsHeader).getByRole("button"));
    expect(stepsHeader).toHaveAttribute("aria-sort", "descending");
    expect(titles()).toEqual(["바닥 닦기", "컵 씻기", "출근 준비"]);
    // 한국어 가나다 정렬
    await user.click(within(screen.getByRole("columnheader", { name: /제목/ })).getByRole("button"));
    expect(titles()).toEqual(["바닥 닦기", "출근 준비", "컵 씻기"]);
  });

  it("정렬을 밖에서 다루면(sort+onSortChange) 행 순서를 건드리지 않고 알리기만 한다", async () => {
    const user = userEvent.setup();
    const onSortChange = vi.fn();
    render(
      <Table caption="직무" columns={columns} rows={rows} rowKey={(r) => r.id} sort={null} onSortChange={onSortChange} />,
    );
    await user.click(within(screen.getByRole("columnheader", { name: /단계 수/ })).getByRole("button"));
    expect(onSortChange).toHaveBeenCalledWith({ key: "steps", dir: "asc" });
    expect(titles()).toEqual(["컵 씻기", "출근 준비", "바닥 닦기"]);
  });

  it("행이 없으면 빈 상태 칸을 표 폭 전체로 보인다", () => {
    render(
      <Table
        caption="직무"
        columns={columns}
        rows={[]}
        rowKey={(r) => r.id}
        empty={<EmptyState kind="empty" title="아직 만든 직무가 없어요" />}
      />,
    );
    const cell = screen.getByText("아직 만든 직무가 없어요").closest("td");
    expect(cell).toHaveAttribute("colspan", "3");
  });

  it("불러오는 중에는 스켈레톤 행 3개와 '불러오는 중이에요'(role=status)", () => {
    const { container } = render(<Table caption="직무" columns={columns} rows={[]} rowKey={(r) => r.id} loading />);
    expect(container.querySelectorAll("tr[data-skeleton]")).toHaveLength(3);
    expect(screen.getByRole("status")).toHaveTextContent("불러오는 중이에요");
    expect(screen.queryByText("아직 아무것도 없어요")).not.toBeInTheDocument();
  });

  it("hideBelow 열은 좁은 화면에서 숨는 클래스를 갖는다(가로 스크롤 대신)", () => {
    render(<Table caption="직무" columns={columns} rows={rows} rowKey={(r) => r.id} />);
    expect(screen.getByRole("columnheader", { name: "메모" })).toHaveClass("hidden", "md:table-cell");
  });

  it("행을 누르면 onRowClick", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    render(<Table caption="직무" columns={columns} rows={rows} rowKey={(r) => r.id} onRowClick={onRowClick} />);
    await user.click(screen.getByText("출근 준비"));
    expect(onRowClick).toHaveBeenCalledWith(rows[1]);
  });
});

describe("Table 빈 상태 머리 줄(2회차 검증)", () => {
  it("행이 없으면 머리 줄을 숨기고, 불러오는 중이거나 행이 있으면 보인다", () => {
    const cols = [{ key: "a", header: "제목", cell: (r: { id: string }) => r.id, sortValue: (r: { id: string }) => r.id }];
    const { container, rerender } = render(<Table caption="빈 표" columns={cols} rows={[]} rowKey={(r) => r.id} />);
    expect(container.querySelector("thead")).toHaveClass("hidden");
    rerender(<Table caption="빈 표" columns={cols} rows={[]} rowKey={(r) => r.id} loading />);
    expect(container.querySelector("thead")).not.toHaveClass("hidden");
    rerender(<Table caption="빈 표" columns={cols} rows={[{ id: "x" }]} rowKey={(r) => r.id} />);
    expect(container.querySelector("thead")).not.toHaveClass("hidden");
  });
});
