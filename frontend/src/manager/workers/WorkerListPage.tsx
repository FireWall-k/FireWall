// 근로자 목록(/manager/workers, 명세 5.7, contract §6.2).
// - 열: 이름, 오늘 상태 배지, 최근 7일 완료(작은 막대 + 숫자), 도움 요청 수, 동의 상태, 접속 코드(●●●● + 눈 5초), … 메뉴.
// - 휴대폰(768 미만)은 이름 아래에 오늘 배지·동의를 한 줄로 보이고 나머지 열은 숨긴다(가로 스크롤 없음).
// - [근로자 추가하기] → 이름·메모 → 4자리 번호를 크게, [복사하기]·[인쇄용 카드 만들기].
// - 지우기는 이름을 다시 적는 위험 창. 지운 뒤 초점은 [근로자 추가하기]로(사라진 행에 남지 않게).
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Ellipsis, Eye, Trash2, UserPlus } from "lucide-react";
import { Button, EmptyState, Menu, Table, iconButtonClasses, type Column, type MenuItem } from "../../components/ui";
import { workerList } from "../copy";
import { getWorkplace, listWorkers } from "../api/workers";
import type { WorkerRow, WorkerWithCode, WorkplaceSettings } from "../api/workerTypes";
import { errorMessage } from "../tasks/listHelpers";
import AccessCodeReveal from "./AccessCodeReveal";
import AddWorkerDialog from "./AddWorkerDialog";
import DeleteWorkerDialog from "./DeleteWorkerDialog";
import PrintCardDialog from "./PrintCardDialog";
import { ConsentBadge, Done7, TodayBadgeView } from "./badges";

export default function WorkerListPage() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<WorkerRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [toDelete, setToDelete] = useState<WorkerRow | null>(null);
  const [printFor, setPrintFor] = useState<WorkerWithCode | null>(null);
  const [workplace, setWorkplace] = useState<WorkplaceSettings | null>(null);
  const addRef = useRef<HTMLButtonElement>(null);

  const load = useCallback(() => {
    listWorkers()
      .then(setRows)
      .catch((e) => setError(errorMessage(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function openPrint(w: WorkerWithCode) {
    setPrintFor(w);
    if (!workplace) getWorkplace().then(setWorkplace).catch(() => undefined);
  }

  function menuItems(r: WorkerRow): MenuItem[] {
    const icon = (I: typeof Eye) => <I size={16} strokeWidth={2} aria-hidden="true" />;
    return [
      { id: "open", label: workerList.open, icon: icon(Eye), onSelect: () => navigate(`/manager/workers/${encodeURIComponent(r.id)}`) },
      { id: "delete", label: workerList.delete, icon: icon(Trash2), danger: true, onSelect: () => setToDelete(r) },
    ];
  }

  const columns: Column<WorkerRow>[] = [
    {
      key: "name",
      header: workerList.colName,
      sortValue: (r) => r.display_name,
      className: "max-w-0 w-full",
      cell: (r) => (
        <div className="flex min-w-0 flex-col gap-1">
          <Link
            to={`/manager/workers/${encodeURIComponent(r.id)}`}
            className="truncate font-semibold text-ink-900 underline-offset-2 hover:underline"
            title={r.display_name}
          >
            {r.display_name}
          </Link>
          <span className="flex flex-wrap items-center gap-1 md:hidden">
            <TodayBadgeView value={r.today_badge} />
            {r.consent_state !== "complete" && <ConsentBadge value={r.consent_state} />}
          </span>
        </div>
      ),
    },
    {
      key: "today",
      header: workerList.colToday,
      hideBelow: "md",
      cell: (r) => <TodayBadgeView value={r.today_badge} />,
    },
    {
      key: "done7",
      header: workerList.colDone7,
      hideBelow: "lg",
      sortValue: (r) => r.done_7d.reduce((a, b) => a + b, 0),
      cell: (r) => <Done7 values={r.done_7d} />,
    },
    {
      key: "help",
      header: workerList.colHelp,
      align: "right",
      hideBelow: "lg",
      sortValue: (r) => r.help_7d,
      cell: (r) => <span className="whitespace-nowrap tabular-nums text-ink-700">{workerList.times(r.help_7d)}</span>,
    },
    {
      key: "consent",
      header: workerList.colConsent,
      hideBelow: "md",
      cell: (r) => <ConsentBadge value={r.consent_state} />,
    },
    {
      key: "code",
      header: workerList.colCode,
      cell: (r) => <AccessCodeReveal workerId={r.id} name={r.display_name} length={r.code_length || r.access_code_length} />,
    },
    {
      key: "menu",
      header: <span className="sr-only">{workerList.colMenu}</span>,
      align: "right",
      cell: (r) => (
        <Menu
          label={workerList.rowMenu(r.display_name)}
          items={menuItems(r)}
          trigger={(p) => (
            <button {...p} type="button" aria-label={workerList.rowMenu(r.display_name)} className={iconButtonClasses("ghost")}>
              <Ellipsis size={20} strokeWidth={2} aria-hidden="true" />
            </button>
          )}
        />
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-ui-xl text-ink-900">{workerList.title}</h1>
        <Button
          ref={addRef}
          variant="primary"
          icon={<UserPlus size={16} strokeWidth={2} aria-hidden="true" />}
          onClick={() => setAdding(true)}
        >
          {workerList.add}
        </Button>
      </div>

      {error ? (
        <EmptyState kind="error" description={error} onRetry={() => {
            setError(null);
            load();
          }} />
      ) : (
        <Table
          caption={workerList.caption}
          columns={columns}
          rows={rows ?? []}
          rowKey={(r) => r.id}
          loading={rows === null}
          empty={<EmptyState kind="empty" title={workerList.emptyTitle} description={workerList.emptyBody} />}
        />
      )}

      <AddWorkerDialog
        open={adding}
        onClose={() => setAdding(false)}
        onCreated={(w) => setRows((prev) => [...(prev ?? []), w])}
        onPrint={openPrint}
      />
      <PrintCardDialog
        open={printFor !== null}
        onClose={() => setPrintFor(null)}
        worker={printFor ? { name: printFor.display_name, code: printFor.access_code } : undefined}
        orgName={workplace?.org_name ?? ""}
        workplaceCode={workplace?.workplace_code ?? ""}
        deviceLink={workplace?.device_link ?? ""}
      />
      <DeleteWorkerDialog
        worker={toDelete}
        onClose={() => setToDelete(null)}
        onDeleted={(id) => {
          setToDelete(null);
          setRows((prev) => (prev ?? []).filter((w) => w.id !== id));
          requestAnimationFrame(() => addRef.current?.focus());
        }}
      />
    </div>
  );
}
