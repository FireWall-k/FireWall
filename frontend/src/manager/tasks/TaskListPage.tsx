// 직무 목록(/manager/tasks, 명세 5.3, contract §2.1, tasks §3.3).
// - 걸러보기 5개(전체·초안·확인 필요·보냄·보관)와 개수. 걸러보기는 서로 겹친다(서버가 셈, 화면은 그대로 보임).
// - 제목 검색(잠깐 멈추면 찾음). 걸러보기와 검색어는 주소(?filter=&q=)에 남아 뒤로 가기·새로고침에도 그대로다.
// - 열: 대표 그림 32 + 제목, 단계 수, 상태 배지('확인 필요 n'·'고친 내용 안 보냄'), 받은 사람(아바타 3 + '+n'), 고친 날.
// - … 메뉴: 고치기(편집기), 다시 보내기(보낸 직무: 확인할 것이 남으면 그 편집기의 첫 확인 단계로, 아니면 보내기 시트 —
//   클릭 3번: … → [다시 보내기] → [n명에게 보내기]), 복제해서 고치기, 보관하기 / 보관함에서 꺼내기, 완전히 지우기(보관한 것만).
// - 직무 삭제는 먼저 보관(명세 5.0). 완전히 지우기는 지워지는 것 목록을 보이는 위험 창으로 확인받는다.
// - 행이 사라지는 일(보관·꺼내기·완전히 지우기·실행 취소) 뒤에는 키보드 초점을 그 자리 행의 … 단추로 옮긴다
//   (다음 행, 없으면 이전 행, 없으면 목록 칸). 초점이 문서 처음으로 사라지지 않게(WCAG 2.4.3).
// - 행동 뒤 다시 받기(reload)는 늘 '지금' 걸러보기·검색어로 부른다(그사이 탭을 바꿔도 옛 탭 목록을 부르지 않게).
// - 걸러보기·검색어를 바꾼 뒤에는 결과 개수(또는 '없어요')를 화면 읽기 프로그램에 알린다(WCAG 4.1.3).
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Archive, ArchiveRestore, Copy, Ellipsis, ImageOff, Lightbulb, PencilLine, Plus, Search, Send, Trash2, X } from "lucide-react";
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
import { errors, sendSheet, taskDelete, taskFilter, taskList, taskMenu, taskRow, taskState, taskToast } from "../copy";
import { archiveTask, deleteTask, duplicateTask, listEmployerTasks, unarchiveTask } from "../api/tasks";
import { TASK_FILTERS, type SendResult, type TaskFilter, type TaskListOut, type TaskSummaryOut } from "../api/types";
import SendSheet from "./editor/SendSheet";
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

/** 행 행동 뒤 초점을 둘 자리: 그 직무(남아 있으면) 또는 같은 순번의 행. */
type FocusTarget = { id: string; index: number };

const MENU_SELECTOR = "button[data-task-menu]";

export default function TaskListPage() {
  const [params, setParams] = useSearchParams();
  const toast = useToast();
  const filter = asFilter(params.get("filter"));
  const q = (params.get("q") ?? "").trim();
  const key = `${filter}\u0000${q}`;

  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [typed, setTyped] = useState(q);
  // 주소의 q가 이 화면 밖에서 바뀌면(사이드바 '직무' 링크, 뒤로 가기) 검색칸 글도 따라간다.
  // 이 화면이 적어 넣은 q는 typed와 같으므로 건드리지 않는다(렌더 중 맞추기, React 문서 'props가 바뀔 때 state 맞추기').
  const [seenQ, setSeenQ] = useState(q);
  if (seenQ !== q) {
    setSeenQ(q);
    if (typed.trim() !== q) setTyped(q);
  }
  const [busyIds, setBusyIds] = useState<ReadonlySet<string>>(new Set());
  const [toDelete, setToDelete] = useState<TaskSummaryOut | null>(null);
  const [sendFor, setSendFor] = useState<TaskSummaryOut | null>(null);
  const navigate = useNavigate();
  const [deleting, setDeleting] = useState(false);
  const seq = useRef(0);
  const panelRef = useRef<HTMLElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const focusAfter = useRef<FocusTarget | null>(null);

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

  // 행동(보관·실행 취소 등)이 끝난 뒤에 부르는 다시 받기는, 행동을 시작한 렌더의 값이 아니라 지금 주소의 값을 쓴다.
  // 옛 값으로 부르면 seq가 올라가 지금 탭의 응답이 버려지고, 옛 탭 응답은 key가 달라 쓰이지 않아 스켈레톤에 멈춘다.
  const latest = useRef({ filter, q, key });
  useEffect(() => {
    latest.current = { filter, q, key };
  }, [filter, q, key]);
  const reload = useCallback(() => {
    const cur = latest.current;
    fetchList(cur.filter, cur.q, cur.key);
  }, [fetchList]);

  // 첫 진입 뒤 걸러보기·검색어가 한 번이라도 바뀌었는지(처음 열 때는 결과 수를 읽지 않는다 — 말이 너무 많아지지 않게).
  const [firstKey] = useState(key);
  const [keyChanged, setKeyChanged] = useState(false);
  if (!keyChanged && key !== firstKey) setKeyChanged(true);
  // 마지막으로 알린 걸러보기·검색어와 그 글. 같은 key 안에서 행동 뒤 다시 받기로 개수가 바뀌어도 새로 알리지 않는다
  // (보관 같은 행동은 토스트가 이미 알리므로 두 번 읽히지 않게).
  const [announced, setAnnounced] = useState<{ key: string; text: string } | null>(null);

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
    // [X]·[검색 지우기] 단추는 지우면 사라지므로 초점을 검색칸으로 옮긴다.
    searchRef.current?.focus();
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

  /** 이 직무 행이 지금 목록에서 몇 번째인지(보이는 순서). */
  function rowIndex(id: string): number {
    const buttons = Array.from(panelRef.current?.querySelectorAll<HTMLElement>(MENU_SELECTOR) ?? []);
    return Math.max(0, buttons.findIndex((b) => b.dataset.taskMenu === id));
  }
  function keepFocusNear(row: TaskSummaryOut) {
    focusAfter.current = { id: row.id, index: rowIndex(row.id) };
  }

  // 목록을 다시 받은 뒤: 초점이 사라졌으면(body) 정해 둔 자리로 옮긴다. 사용자가 그새 다른 곳으로 옮겼으면 두고 본다.
  useEffect(() => {
    const target = focusAfter.current;
    if (!target || !data) return;
    focusAfter.current = null;
    const active = document.activeElement;
    if (active && active !== document.body && active.isConnected) return;
    const buttons = Array.from(panelRef.current?.querySelectorAll<HTMLElement>(MENU_SELECTOR) ?? []);
    const same = buttons.find((b) => b.dataset.taskMenu === target.id);
    const near = same ?? buttons[Math.min(target.index, buttons.length - 1)];
    (near ?? panelRef.current)?.focus();
  }, [data]);

  // [실행 취소]가 실패해도 다시 받는다. 눌린 [실행 취소]는 토스트와 함께 사라지므로, 다시 받기가 끝나야
  // 위의 초점 자리 effect가 돌아 초점을 행의 … 단추로 옮긴다(안 그러면 body에 남음, WCAG 2.4.3).
  function undoFailed(e: unknown) {
    toast.show({ tone: "error", message: errorMessage(e) });
    reload();
  }

  async function run(row: TaskSummaryOut, action: () => Promise<unknown>, done: () => void) {
    if (busyIds.has(row.id)) return;
    keepFocusNear(row);
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
          keepFocusNear(row);
          unarchiveTask(row.id).then(reload, undoFailed);
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
          keepFocusNear(row);
          archiveTask(row.id).then(reload, undoFailed);
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
    keepFocusNear(row);
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
    const editPath = `/manager/tasks/${encodeURIComponent(row.id)}`;
    const edit: MenuItem = { id: "edit", label: taskMenu.edit, icon: icon(PencilLine), onSelect: () => navigate(editPath) };
    // 다시 보내기(contract §3.6): 확인할 것이 남았으면 보내기 대신 그 직무 편집기의 첫 확인 단계로 간다.
    const resend: MenuItem | null = row.current_version_no
      ? row.needs_check_count > 0
        ? {
            id: "resend", label: taskMenu.resend, icon: icon(Send), hint: taskMenu.resendBlocked(row.needs_check_count),
            onSelect: () => navigate(`${editPath}?review=1`),
          }
        : { id: "resend", label: taskMenu.resend, icon: icon(Send), onSelect: () => setSendFor(row) }
      : null;
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
    return [
      ...(resend ? [resend] : []),
      edit,
      dup,
      { id: "archive", label: taskMenu.archive, icon: icon(Archive), onSelect: () => archive(row) },
    ];
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
            {r.state === "archived" ? (
              <span className="truncate font-semibold text-ink-900" title={r.title}>
                {r.title}
              </span>
            ) : (
              <Link
                to={`/manager/tasks/${encodeURIComponent(r.id)}`}
                className="truncate font-semibold text-ink-900 underline-offset-2 hover:underline"
                title={r.title}
              >
                {r.title}
              </Link>
            )}
            {/* 휴대폰(768 미만): 상태·단계 수·받은 사람·고친 날 열을 숨기고 제목 아래 두 줄로 보인다(제목이 잘리지 않게). */}
            <StatusBadges row={r} className="md:hidden" />
            <MobileMeta row={r} />
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
              data-task-menu={r.id}
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

  // 빈 상태 제목과 같은 글을 두 번 두지 않으려고 따로 짧은 문구를 쓴다(빈 상태 제목은 표 안에 보인다).
  // 걸러보기·검색어가 바뀌어 처음 받은 결과만 알린다(렌더 중 맞추기). 받는 중에는 비워 둔다.
  if (keyChanged && data && announced?.key !== key) setAnnounced({ key, text: taskList.resultCount(data.items.length) });
  const announce = data && announced?.key === key ? announced.text : "";

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
            <Link to="/manager/tasks/new" className={buttonClasses("primary", "md")}>
              <Plus size={16} strokeWidth={2} aria-hidden="true" />
              {taskList.emptyCreate}
            </Link>
            {/* [예시로 만들어 보기]: 새 직무 화면을 예시 지시문으로 채워 연다(옛 ManagerPage가 ?example=1을 읽음).
                아이콘은 '✦ 자동'과 헷갈리는 반짝이(Sparkles) 말고 Lightbulb. */}
            <Link to="/manager/tasks/new?example=1" className={buttonClasses("secondary", "md")}>
              <Lightbulb size={16} strokeWidth={2} aria-hidden="true" />
              {taskList.emptyExample}
            </Link>
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
        <Link to="/manager/tasks/new" className={buttonClasses("primary", "md")}>
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
              ref={searchRef}
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

      {/* 걸러보기·검색 결과 알림(화면에는 숨김). 표의 '불러오는 중이에요'와 따로 둔다. */}
      <p role="status" className="sr-only" data-testid="task-result-status">
        {announce}
      </p>

      <section ref={panelRef} id="task-list-panel" role="tabpanel" aria-label={taskFilter[filter]} tabIndex={-1}>
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

      <SendSheet
        open={!!sendFor}
        onClose={() => setSendFor(null)}
        taskId={sendFor?.id ?? ""}
        hasUnsentChanges={!!sendFor?.has_unsent_changes}
        versionNo={sendFor?.current_version_no ?? null}
        onGoToStep={(stepId) => {
          const id = sendFor?.id;
          setSendFor(null);
          if (id) navigate(`/manager/tasks/${encodeURIComponent(id)}?step=${encodeURIComponent(stepId)}`);
        }}
        onSent={(result: SendResult) => {
          setSendFor(null);
          toast.show({
            tone: "success",
            message: sendSheet.sentMessage(result.results.length),
            action: { label: sendSheet.viewStatus, onClick: () => navigate("/manager") },
          });
          reload();
        }}
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

/** 휴대폰 행 둘째 줄: '4단계 · 3분 전 · 받은 사람 5명'(또는 '아직 안 보냄'). md 이상에서는 열로 보인다. */
function MobileMeta({ row }: { row: TaskSummaryOut }) {
  const total = row.recipients.length + row.recipients_more;
  return (
    <span className="truncate text-ui-sm text-ink-700 md:hidden" data-testid="task-row-meta">
      {taskRow.stepCount(row.step_count)}
      {" · "}
      <time dateTime={row.updated_at}>{relativeDate(row.updated_at)}</time>
      {" · "}
      {total === 0 ? taskRow.noRecipients : taskRow.recipientsLabel(total)}
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
