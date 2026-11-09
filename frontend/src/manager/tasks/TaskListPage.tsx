// 직무 목록(/m/tasks, 명세 5.3, contract §2.1, tasks §3.3).
// - 걸러보기 5개(전체·초안·확인 필요·보냄·보관)와 개수. 걸러보기는 서로 겹친다(서버가 셈, 화면은 그대로 보임).
// - 제목 검색(잠깐 멈추면 찾음). 걸러보기와 검색어는 주소(?filter=&q=)에 남아 뒤로 가기·새로고침에도 그대로다.
// - 열: 대표 그림 32 + 제목, 단계 수, 상태 배지('확인 필요 n'·'고친 내용 안 보냄'), 받은 사람(아바타 3 + '+n'), 고친 날.
// - … 메뉴: 고치기(2b-1 새 편집기 전까지 꺼 둠), 복제해서 고치기, 보관하기 / 보관함에서 꺼내기, 완전히 지우기(보관한 것만).
// - 직무 삭제는 먼저 보관(명세 5.0). 완전히 지우기는 지워지는 것 목록을 보이는 위험 창으로 확인받는다.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Archive, ArchiveRestore, Copy, Ellipsis, ImageOff, PencilLine, Plus, Search, Sparkles, Trash2, X } from "lucide-react";
import {
  AvatarGroup,
  Badge,
  Button,
  Dialog,
  EmptyState,
  IconButton,
  Menu,
  StatusDot,
  Table,
  Tabs,
  buttonClasses,
  iconButtonClasses,
  inputClasses,
  useToast,
  type Column,
  type MenuItem,
  type TabItem,
  type Tone,
} from "../../components/ui";
import { cn } from "../../cn";
import { errors, taskDelete, taskFilter, taskList, taskMenu, taskRow, taskState, taskToast } from "../copy";
import { archiveTask, deleteTask, duplicateTask, listEmployerTasks, unarchiveTask } from "../api/tasks";
import { TASK_FILTERS, type TaskFilter, type TaskListOut, type TaskSummaryOut } from "../api/types";
import { SEARCH_DEBOUNCE_MS, errorMessage } from "./listHelpers";
import { parseServerTime, relativeDate } from "./relativeDate";

const STATE_TONE: Record<TaskSummaryOut["state"], Tone> = {
  draft: "neutral",
  published: "success",
  archived: "neutral",
};

function asFilter(v: string | null): TaskFilter {
  return (TASK_FILTERS as readonly string[]).includes(v ?? "") ? (v as TaskFilter) : "all";
}

type Loaded = { key: string; data: TaskListOut } | { key: string; error: string };

export default function TaskListPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const filter = asFilter(params.get("filter"));
  const q = (params.get("q") ?? "").trim();
  const key = `${filter}\u0000${q}`;

  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [typed, setTyped] = useState(q);
  const [busyIds, setBusyIds] = useState<ReadonlySet<string>>(new Set());
  const [toDelete, setToDelete] = useState<TaskSummaryOut | null>(null);
  const [deleting, setDeleting] = useState(false);
  const seq = useRef(0);

  // 늦게 온 옛 응답이 새 걸러보기 결과를 덮지 않게 마지막 요청만 받는다.
  const fetchList = useCallback((f: TaskFilter, query: string, k: string) => {
    const my = ++seq.current;
    listEmployerTasks(f, query).then(
      (data) => {
        if (my === seq.current) setLoaded({ key: k, data });
      },
      (e: unknown) => {
        if (my === seq.current) setLoaded({ key: k, error: errorMessage(e) });
      },
    );
  }, []);

  useEffect(() => {
    fetchList(filter, q, key);
  }, [fetchList, filter, q, key]);

  const reload = useCallback(() => fetchList(filter, q, key), [fetchList, filter, q, key]);

  // 검색: 적기를 멈추면 주소의 q를 바꾼다(replace — 글자마다 뒤로 가기 기록을 남기지 않음).
  useEffect(() => {
    if (typed.trim() === q) return;
    const t = window.setTimeout(() => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (typed.trim()) next.set("q", typed.trim());
          else next.delete("q");
          return next;
        },
        { replace: true },
      );
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [typed, q, setParams]);

  function selectFilter(f: TaskFilter) {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (f === "all") next.delete("filter");
      else next.set("filter", f);
      return next;
    });
  }

  function clearSearch() {
    setTyped("");
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("q");
        return next;
      },
      { replace: true },
    );
  }

  const current = loaded && loaded.key === key ? loaded : null;
  const data = current && "data" in current ? current.data : null;
  const loadError = current && "error" in current ? current.error : null;
  // 걸러보기를 바꾸는 동안에도 탭 개수는 직전 값을 보인다(숫자가 깜빡이지 않게).
  const counts = data?.counts ?? (loaded && "data" in loaded ? loaded.data.counts : undefined);

  async function run(row: TaskSummaryOut, action: () => Promise<unknown>, done: () => void) {
    if (busyIds.has(row.id)) return;
    setBusyIds((s) => new Set(s).add(row.id));
    try {
      await action();
      done();
    } catch (e) {
      toast.show({ tone: "error", message: errorMessage(e) });
    } finally {
      setBusyIds((s) => {
        const n = new Set(s);
        n.delete(row.id);
        return n;
      });
      reload();
    }
  }

  function archive(row: TaskSummaryOut) {
    void run(row, () => archiveTask(row.id), () =>
      toast.show({
        tone: "success",
        message: taskToast.archived(row.title),
        onUndo: () => {
          unarchiveTask(row.id).then(reload, (e: unknown) => toast.show({ tone: "error", message: errorMessage(e) }));
        },
      }),
    );
  }

  function unarchive(row: TaskSummaryOut) {
    void run(row, () => unarchiveTask(row.id), () =>
      toast.show({
        tone: "success",
        message: taskToast.unarchived(row.title),
        onUndo: () => {
          archiveTask(row.id).then(reload, (e: unknown) => toast.show({ tone: "error", message: errorMessage(e) }));
        },
      }),
    );
  }

  function duplicate(row: TaskSummaryOut) {
    let title = row.title;
    void run(
      row,
      async () => {
        const created = await duplicateTask(row.id);
        title = created.title;
      },
      () => toast.show({ tone: "success", message: taskToast.duplicated(title) }),
    );
  }

  async function confirmDelete() {
    const row = toDelete;
    if (!row) return;
    setDeleting(true);
    try {
      await deleteTask(row.id);
      setToDelete(null);
      toast.show({ tone: "success", message: taskToast.deleted(row.title) });
    } catch (e) {
      setToDelete(null);
      toast.show({ tone: "error", message: errorMessage(e) });
    } finally {
      setDeleting(false);
      reload();
    }
  }

  function menuItems(row: TaskSummaryOut): MenuItem[] {
    const icon = (I: typeof Copy) => <I size={16} strokeWidth={2} aria-hidden="true" />;
    const edit: MenuItem = { id: "edit", label: taskMenu.edit, icon: icon(PencilLine), disabled: true, hint: taskMenu.editLater };
    const dup: MenuItem = { id: "duplicate", label: taskMenu.duplicate, icon: icon(Copy), onSelect: () => duplicate(row) };
    if (row.state === "archived") {
      return [
        { id: "unarchive", label: taskMenu.unarchive, icon: icon(ArchiveRestore), onSelect: () => unarchive(row) },
        dup,
        // 완전히 지우기는 보관 걸러보기에서만(명세 5.0: 먼저 보관, 완전 삭제는 보관함에서만).
        ...(filter === "archived"
          ? [{ id: "delete", label: taskMenu.delete, icon: icon(Trash2), danger: true, onSelect: () => setToDelete(row) }]
          : []),
      ];
    }
    return [edit, dup, { id: "archive", label: taskMenu.archive, icon: icon(Archive), onSelect: () => archive(row) }];
  }

  const columns: Column<TaskSummaryOut>[] = [
    {
      key: "title",
      header: taskList.colTitle,
      sortValue: (r) => r.title,
      className: "max-w-0 w-full",
      cell: (r) => (
        <div className="flex min-w-0 items-center gap-3">
          <Cover url={r.cover_url} />
          <div className="flex min-w-0 flex-col gap-1">
            <span className="truncate font-semibold text-ink-900" title={r.title}>
              {r.title}
            </span>
            {/* 휴대폰(768 미만): 상태 열을 숨기고 제목 아래에 보인다(제목이 잘리지 않게). */}
            <StatusBadges row={r} className="md:hidden" />
          </div>
        </div>
      ),
    },
    {
      key: "steps",
      header: taskList.colSteps,
      align: "right",
      hideBelow: "md",
      sortValue: (r) => r.step_count,
      cell: (r) => <span className="whitespace-nowrap tabular-nums text-ink-700">{taskRow.stepCount(r.step_count)}</span>,
    },
    {
      key: "status",
      header: taskList.colStatus,
      hideBelow: "md",
      sortValue: (r) => r.needs_check_count * 2 + (r.has_unsent_changes ? 1 : 0),
      cell: (r) => <StatusBadges row={r} className="flex-col items-start" />,
    },
    {
      key: "recipients",
      header: taskList.colRecipients,
      hideBelow: "lg",
      sortValue: (r) => r.recipients.length + r.recipients_more,
      cell: (r) => {
        const total = r.recipients.length + r.recipients_more;
        if (total === 0) return <span className="whitespace-nowrap text-ui-sm text-ink-500">{taskRow.noRecipients}</span>;
        return (
          <AvatarGroup
            people={r.recipients.map((p) => ({ id: p.worker_id, initials: p.initials }))}
            more={r.recipients_more}
            label={taskRow.recipientsLabel(total)}
          />
        );
      },
    },
    {
      key: "updated",
      header: taskList.colUpdated,
      hideBelow: "md",
      sortValue: (r) => parseServerTime(r.updated_at) || 0,
      cell: (r) => (
        <time dateTime={r.updated_at} className="whitespace-nowrap text-ui-sm text-ink-700">
          {relativeDate(r.updated_at)}
        </time>
      ),
    },
    {
      key: "menu",
      header: <span className="sr-only">{taskList.colMenu}</span>,
      align: "right",
      cell: (r) => (
        <Menu
          label={taskRow.rowMenu(r.title)}
          items={menuItems(r)}
          trigger={(p) => (
            <button
              {...p}
              type="button"
              aria-label={taskRow.rowMenu(r.title)}
              aria-busy={busyIds.has(r.id) || undefined}
              disabled={busyIds.has(r.id)}
              className={iconButtonClasses("ghost")}
            >
              <Ellipsis size={20} strokeWidth={2} aria-hidden="true" />
            </button>
          )}
        />
      ),
    },
  ];

  const tabs: TabItem<TaskFilter>[] = TASK_FILTERS.map((f) => ({ id: f, label: taskFilter[f], count: counts?.[f] }));
  const nothingAtAll = !!data && data.counts.all === 0 && data.counts.archived === 0 && !q;

  let empty;
  if (nothingAtAll) {
    empty = (
      <EmptyState
        kind="empty"
        title={taskList.emptyTitle}
        description={taskList.emptyBody}
        actions={
          <>
            <Link to="/m/tasks/new" className={buttonClasses("primary", "md")}>
              <Plus size={16} strokeWidth={2} aria-hidden="true" />
              {taskList.emptyCreate}
            </Link>
            <Button icon={<Sparkles size={16} strokeWidth={2} aria-hidden="true" />} onClick={() => navigate("/m/tasks/new?example=1")}>
              {taskList.emptyExample}
            </Button>
          </>
        }
      />
    );
  } else if (q) {
    empty = (
      <EmptyState
        kind="empty"
        title={taskList.searchEmpty(q)}
        actions={<Button onClick={clearSearch}>{taskList.clearSearch}</Button>}
      />
    );
  } else {
    empty = (
      <EmptyState
        kind="empty"
        title={taskList.filteredEmpty(taskFilter[filter])}
        description={filter === "archived" ? taskList.archivedEmptyBody : undefined}
      />
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <header className="flex items-center justify-between gap-3">
        <h1 className="text-ui-xl text-ink-900">{taskList.title}</h1>
        <Link to="/m/tasks/new" className={buttonClasses("primary", "md")}>
          <Plus size={16} strokeWidth={2} aria-hidden="true" />
          {taskList.newTask}
        </Link>
      </header>

      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <Tabs items={tabs} value={filter} onChange={selectFilter} label={taskList.filterLabel} controls="task-list-panel" className="min-w-0" />
        <form
          role="search"
          className="flex flex-col gap-1.5 lg:w-72"
          onSubmit={(e) => {
            e.preventDefault();
            setParams(
              (prev) => {
                const next = new URLSearchParams(prev);
                if (typed.trim()) next.set("q", typed.trim());
                else next.delete("q");
                return next;
              },
              { replace: true },
            );
          }}
        >
          <label htmlFor="task-search" className="text-ui-sm font-semibold text-ink-700">
            {taskList.searchLabel}
          </label>
          <div className="relative">
            <Search size={16} strokeWidth={2} aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-500" />
            <input
              id="task-search"
              type="search"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={taskList.searchPlaceholder}
              autoComplete="off"
              className={cn(inputClasses, "min-h-control pl-9 pr-10 coarse:min-h-control-coarse")}
            />
            {typed && (
              <IconButton
                aria-label={taskList.clearSearch}
                icon={<X size={16} strokeWidth={2} aria-hidden="true" />}
                onClick={clearSearch}
                className="absolute right-0 top-1/2 -translate-y-1/2"
              />
            )}
          </div>
        </form>
      </div>

      <section id="task-list-panel" role="tabpanel" aria-label={taskFilter[filter]}>
        {loadError ? (
          <EmptyState kind="error" title={errors.load} description={loadError === errors.load ? undefined : loadError} onRetry={reload} className="rounded-card border border-paper-200 bg-white" />
        ) : (
          <Table
            columns={columns}
            rows={data?.items ?? []}
            rowKey={(r) => r.id}
            caption={taskList.caption}
            loading={!data}
            empty={empty}
            defaultSort={{ key: "updated", dir: "desc" }}
          />
        )}
      </section>

      <Dialog
        open={!!toDelete}
        onClose={() => setToDelete(null)}
        tone="danger"
        title={toDelete ? taskDelete.title(toDelete.title) : ""}
        description={taskDelete.description}
        items={[...taskDelete.items]}
        confirmLabel={taskDelete.confirm}
        onConfirm={() => void confirmDelete()}
        busy={deleting}
      />
    </div>
  );
}

/** 대표 그림 32. 그림이 없거나 못 불러오면 빈 그림 표시(꾸밈). */
function Cover({ url }: { url: string | null }) {
  const [failed, setFailed] = useState<string | null>(null);
  const ok = !!url && failed !== url;
  return (
    <span className="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-control border border-paper-200 bg-white">
      {ok ? (
        <img src={url} alt="" loading="lazy" className="size-full object-contain" onError={() => setFailed(url)} />
      ) : (
        <ImageOff size={16} strokeWidth={2} aria-hidden="true" className="text-ink-500" />
      )}
    </span>
  );
}

/** 상태 점 + 행 배지('확인 필요 n'·'고친 내용 안 보냄', contract §2.1). 색 + 아이콘 + 글로 보인다. */
function StatusBadges({ row, className }: { row: TaskSummaryOut; className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-center gap-1", className)}>
      <StatusDot tone={STATE_TONE[row.state]}>{taskState[row.state]}</StatusDot>
      {row.needs_check_count > 0 && <Badge tone="warning">{taskRow.needsCheck(row.needs_check_count)}</Badge>}
      {row.has_unsent_changes && <Badge tone="info">{taskRow.unsentChanges}</Badge>}
    </div>
  );
}
