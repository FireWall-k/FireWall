// 근로자 상세(/manager/workers/:id, 명세 5.7). 탭 4개: 현황 · 화면 설정 · 접속 코드 · 동의·개인정보.
// 고른 탭은 주소(?tab=)에 남아 새로고침·뒤로 가기에도 그대로다. 단건 조회 API가 없어 목록에서 찾는다.
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import type { A11yPrefs } from "../../api";
import { Card, EmptyState, Tabs, useToast, type TabItem } from "../../components/ui";
import { person, prefs as prefsCopy, workerDetail } from "../copy";
import { listWorkers, updateWorker } from "../api/workers";
import type { WorkerRow } from "../api/workerTypes";
import { errorMessage } from "../tasks/listHelpers";
import CodeTab from "./CodeTab";
import ConsentTab from "./ConsentTab";
import DeleteWorkerDialog from "./DeleteWorkerDialog";
import PrefsForm from "./PrefsForm";
import StatsTab from "./StatsTab";
import { ConsentBadge, TodayBadgeView } from "./badges";

type Tab = "stats" | "prefs" | "code" | "consent";
const TABS: Tab[] = ["stats", "prefs", "code", "consent"];
const PANEL_ID = "worker-detail-panel";

export default function WorkerDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const tab: Tab = (TABS as string[]).includes(params.get("tab") ?? "") ? (params.get("tab") as Tab) : "stats";
  const [worker, setWorker] = useState<WorkerRow | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(() => {
    listWorkers()
      .then((list) => setWorker(list.find((w) => w.id === id) ?? null))
      .catch((e) => setError(errorMessage(e)));
  }, [id]);
  useEffect(() => {
    load();
  }, [load]);

  const merge = (w: WorkerRow) => setWorker((prev) => (prev ? { ...prev, ...w, today_badge: prev.today_badge, done_7d: prev.done_7d, help_7d: prev.help_7d } : w));

  async function savePrefs(patch: Partial<A11yPrefs>) {
    if (!worker) return;
    const before = worker;
    // 바로 바꿔 보이고, 실패하면 되돌린다.
    setWorker({ ...worker, a11y_prefs: { ...worker.a11y_prefs, ...patch } });
    try {
      merge(await updateWorker(worker.id, { a11y_prefs: patch }));
      toast.show({ tone: "success", message: prefsCopy.saved });
    } catch (e) {
      setWorker(before);
      toast.show({ tone: "error", message: errorMessage(e) });
    }
  }

  if (error) return <EmptyState kind="error" description={error} onRetry={() => {
            setError(null);
            load();
          }} />;
  if (worker === undefined) return <EmptyState kind="loading" />;
  if (worker === null) {
    return (
      <div className="flex flex-col gap-5">
        <h1 className="text-ui-xl text-ink-900">{workerDetail.notFound}</h1>
        <Link to="/manager/workers" className="text-ui-base font-semibold text-moss-600 underline">
          {workerDetail.back}
        </Link>
      </div>
    );
  }

  const items: TabItem<Tab>[] = [
    { id: "stats", label: workerDetail.tabStats },
    { id: "prefs", label: workerDetail.tabPrefs },
    { id: "code", label: workerDetail.tabCode },
    { id: "consent", label: workerDetail.tabConsent },
  ];

  return (
    <div className="flex flex-col gap-5">
      <Link to="/manager/workers" className="inline-flex w-fit items-center gap-1 text-ui-sm font-semibold text-ink-700 hover:text-ink-900 coarse:min-h-control-coarse">
        <ChevronLeft size={16} strokeWidth={2} aria-hidden="true" />
        {workerDetail.back}
      </Link>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-ui-xl text-ink-900">{person(worker.display_name)}</h1>
        <TodayBadgeView value={worker.today_badge} />
        <ConsentBadge value={worker.consent_state} />
      </div>
      {worker.name_ambiguous && <p className="text-ui-sm text-warn-700">{workerDetail.ambiguousName}</p>}
      <Tabs
        label={workerDetail.tabsLabel}
        items={items}
        value={tab}
        controls={PANEL_ID}
        onChange={(t) => setParams(t === "stats" ? {} : { tab: t }, { replace: true })}
      />
      <div id={PANEL_ID} role="tabpanel" aria-label={items.find((t) => t.id === tab)?.label as string} tabIndex={-1}>
        {tab === "stats" && <StatsTab workerId={worker.id} />}
        {tab === "prefs" && (
          <Card className="flex flex-col gap-4">
            <div>
              <h2 className="text-ui-lg font-bold text-ink-900">{prefsCopy.heading}</h2>
              <p className="text-ui-sm text-ink-500">{prefsCopy.hint}</p>
            </div>
            <PrefsForm idPrefix={`w-${worker.id}`} value={worker.a11y_prefs} onChange={(p) => void savePrefs(p)} />
          </Card>
        )}
        {tab === "code" && <CodeTab worker={worker} onChange={merge} />}
        {tab === "consent" && <ConsentTab worker={worker} onChange={merge} onDelete={() => setDeleting(true)} />}
      </div>
      <DeleteWorkerDialog
        worker={deleting ? worker : null}
        onClose={() => setDeleting(false)}
        onDeleted={() => navigate("/manager/workers", { replace: true })}
      />
    </div>
  );
}
