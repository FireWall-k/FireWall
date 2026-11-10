// 표(명세 7.3): 머리 고정(상단 바 56 아래에 붙음), 정렬, 빈 상태 칸, 불러오는 중 스켈레톤 행. 행 높이 56.
// 좁은 화면에서는 hideBelow로 덜 중요한 열을 숨겨 가로 스크롤을 만들지 않는다(390 폭 가로 스크롤 0).
import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { cn } from "../../cn";
import { ui as copy } from "../../manager/copy";
import Skeleton from "./Skeleton";

export type SortDir = "asc" | "desc";
export interface SortState {
  key: string;
  dir: SortDir;
}

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** 있으면 머리 칸이 정렬 버튼이 된다. 값이 같으면 원래 순서를 지킨다. */
  sortValue?: (row: T) => string | number;
  align?: "left" | "right" | "center";
  /** 이 폭보다 좁으면 열을 숨긴다(md 768, lg 1024). */
  hideBelow?: "md" | "lg";
  className?: string;
}

export interface TableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** 표 이름(화면 읽기 프로그램용 caption, 화면에는 숨김). */
  caption: string;
  loading?: boolean;
  /** 행이 없을 때 표 안에 보일 내용(EmptyState). */
  empty?: ReactNode;
  /** 정렬을 밖에서 다룰 때(서버 정렬 등). 없으면 표가 스스로 정렬한다. */
  sort?: SortState | null;
  onSortChange?: (s: SortState) => void;
  defaultSort?: SortState;
  onRowClick?: (row: T) => void;
  className?: string;
}

const HIDE: Record<NonNullable<Column<unknown>["hideBelow"]>, string> = {
  md: cn("hidden md:table-cell"),
  lg: cn("hidden lg:table-cell"),
};

function alignClass(a: Column<unknown>["align"]) {
  return a === "right" ? "text-right" : a === "center" ? "text-center" : "text-left";
}

export default function Table<T>({
  columns,
  rows,
  rowKey,
  caption,
  loading = false,
  empty,
  sort: controlledSort,
  onSortChange,
  defaultSort,
  onRowClick,
  className,
}: TableProps<T>) {
  const [ownSort, setOwnSort] = useState<SortState | null>(defaultSort ?? null);
  const sort = controlledSort !== undefined ? controlledSort : ownSort;

  const sorted = useMemo(() => {
    if (!sort || controlledSort !== undefined) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sortValue) return rows;
    const get = col.sortValue;
    const sign = sort.dir === "asc" ? 1 : -1;
    return rows
      .map((r, i) => ({ r, i, v: get(r) }))
      .sort((a, b) => {
        const c = typeof a.v === "number" && typeof b.v === "number" ? a.v - b.v : String(a.v).localeCompare(String(b.v), "ko");
        return c !== 0 ? c * sign : a.i - b.i;
      })
      .map((x) => x.r);
  }, [rows, columns, sort, controlledSort]);

  function toggle(key: string) {
    const next: SortState = sort?.key === key && sort.dir === "asc" ? { key, dir: "desc" } : { key, dir: "asc" };
    if (controlledSort === undefined) setOwnSort(next);
    onSortChange?.(next);
  }

  return (
    <div className={cn("overflow-x-clip rounded-card border border-paper-200 bg-white", className)}>
      <table className="w-full border-collapse text-ui-base text-ink-900" aria-busy={loading || undefined}>
        <caption className="sr-only">{caption}</caption>
        {/* 행이 없을 때(불러오는 중이 아님)는 머리 줄을 숨긴다 — 빈 칸 위에 열 머리가 고르지 않게 퍼지고
            누를 것 없는 정렬 단추가 남지 않게(명세 5.3 빈 상태). */}
        <thead className={cn(!loading && sorted.length === 0 && "hidden")}>
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key;
              const ariaSort = c.sortValue ? (active ? (sort!.dir === "asc" ? "ascending" : "descending") : "none") : undefined;
              return (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={ariaSort}
                  className={cn(
                    "sticky top-topbar z-10 h-10 whitespace-nowrap border-b border-paper-200 bg-paper-50 px-4 text-ui-xs font-semibold text-ink-700",
                    alignClass(c.align),
                    c.hideBelow && HIDE[c.hideBelow],
                  )}
                >
                  {c.sortValue ? (
                    <button
                      type="button"
                      onClick={() => toggle(c.key)}
                      className="inline-flex min-h-8 items-center gap-1 rounded-control px-1 -mx-1 hover:bg-paper-100 hover:text-ink-900 coarse:min-h-control-coarse"
                    >
                      {c.header}
                      {active ? (
                        sort!.dir === "asc" ? (
                          <ArrowUp size={14} strokeWidth={2} aria-hidden="true" />
                        ) : (
                          <ArrowDown size={14} strokeWidth={2} aria-hidden="true" />
                        )
                      ) : (
                        <ArrowUpDown size={14} strokeWidth={2} aria-hidden="true" className="text-ink-500" />
                      )}
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            [0, 1, 2].map((i) => (
              <tr key={`sk${i}`} data-skeleton="true" className="h-table-row border-b border-paper-200 last:border-b-0">
                {columns.map((c) => (
                  <td key={c.key} className={cn("px-4", c.hideBelow && HIDE[c.hideBelow])}>
                    <Skeleton className="h-4 w-3/4" />
                  </td>
                ))}
              </tr>
            ))
          ) : sorted.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="p-0">
                {empty ?? <p className="px-4 py-10 text-center text-ui-base text-ink-500">{copy.empty}</p>}
              </td>
            </tr>
          ) : (
            sorted.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={cn(
                  "h-table-row border-b border-paper-200 last:border-b-0",
                  onRowClick && "cursor-pointer hover:bg-paper-50",
                )}
              >
                {columns.map((c) => (
                  <td key={c.key} className={cn("px-4 py-2 align-middle", alignClass(c.align), c.hideBelow && HIDE[c.hideBelow], c.className)}>
                    {c.cell(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
      {loading && <span role="status" className="sr-only">{copy.loading}</span>}
    </div>
  );
}
