// 설정(/manager/settings, 명세 5.8, contract §6.2).
// - 사업장: 이름(저장), 사업장 코드 + [코드 복사하기].
// - 기기 연결: QR, /worker?site=… 주소 + [주소 복사하기], [인쇄용 카드 만들기].
// - 근로자 화면 기본값(명세 4.12, 새 근로자에게만), 호칭(한글 1~6자, 근로자 화면 미리보기).
// - 알림: '도움 알림 받기' — 상단 바 메뉴와 같은 웹 푸시 스위치(usePushToggle, 3-0 M11). 서버에 키가 없거나
//   브라우저가 웹 푸시를 못 하면 꺼진 채 '켤 수 없어요'를 보인다. 계정: 이름·로그아웃. 선생님 모드 PIN은 3차라 숨긴다.
// - 자동 처리 사용량(이번 달, 읽기만): 사용 횟수·어림 요금($·원)·알림 기준을 넘으면 경고 줄. 따로 불러와서
//   실패해도 설정 화면 나머지는 그대로 보인다.
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Copy, LogOut, Printer, TriangleAlert } from "lucide-react";
import type { A11yPrefs } from "../../api";
import { Button, Card, EmptyState, Field, Input, Switch, useToast } from "../../components/ui";
import { teacherCopy } from "../../worker/copy";
import { prefs as prefsCopy, settings as copy } from "../copy";
import { getAiUsage, getWorkplace, updateWorkplace } from "../api/workers";
import type { AiUsage, WorkplaceSettings } from "../api/workerTypes";
import { pushToast, usePushToggle } from "../shell/pushToggle";
import { errorMessage } from "../tasks/listHelpers";
import PrefsForm from "../workers/PrefsForm";
import PrintCardDialog from "../workers/PrintCardDialog";
import QrCode from "../workers/QrCode";
import { copyText, isValidTitle } from "../workers/helpers";

export interface SettingsPageProps {
  displayName: string;
  onLogout: () => void;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card padding="lg" className="flex flex-col gap-4">
      <h2 className="text-ui-lg font-bold text-ink-900">{title}</h2>
      {children}
    </Card>
  );
}

/** 1달러 ≈ 1,400원(어림). */
const WON_PER_USD = 1400;

/** 1달러가 안 되면 센트 아래 한 자리까지 보인다(작은 요금이 $0.00으로 보이지 않게). */
function formatUsd(usd: number): string {
  return usd >= 1 || usd === 0 ? usd.toFixed(2) : usd.toFixed(3);
}

function formatWon(usd: number): string {
  return Math.round(usd * WON_PER_USD).toLocaleString("ko-KR");
}

function UsageSection() {
  const [usage, setUsage] = useState<AiUsage | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    getAiUsage()
      .then((u) => alive && setUsage(u))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, []);

  let body: ReactNode;
  if (failed || (usage && !usage.available)) {
    body = <p className="text-ui-base text-ink-700">{copy.usageUnavailable}</p>;
  } else if (!usage) {
    body = null;
  } else {
    body = (
      <>
        {!usage.enabled && <p className="text-ui-base text-ink-700">{copy.usageOff}</p>}
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-ui-base">
          <dt className="text-ink-700">{copy.usageCalls}</dt>
          <dd data-testid="usage-calls" className="font-semibold text-ink-900">
            {copy.usageCallsValue(usage.calls)}
          </dd>
          <dt className="text-ink-700">{copy.usageCost}</dt>
          <dd data-testid="usage-cost" className="font-semibold text-ink-900">
            {copy.usageCostValue(formatUsd(usage.usd), formatWon(usage.usd))}
          </dd>
        </dl>
        {usage.over_alert && (
          <p
            role="status"
            className="flex items-start gap-2 rounded-control border border-warn-line/40 bg-warn-50 px-3 py-2 text-ui-base font-semibold text-warn-700"
          >
            <TriangleAlert size={18} strokeWidth={2} aria-hidden="true" className="mt-0.5 shrink-0" />
            {copy.usageOver(String(usage.alert_usd))}
          </p>
        )}
      </>
    );
  }
  return (
    <Section title={copy.usageHeading}>
      <div data-testid="usage-card" className="flex flex-col gap-3">
        {body}
        <p className="text-ui-sm text-ink-500">{copy.usageNote}</p>
      </div>
    </Section>
  );
}

export default function SettingsPage({ displayName, onLogout }: SettingsPageProps) {
  const toast = useToast();
  const [wp, setWp] = useState<WorkplaceSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [orgName, setOrgName] = useState("");
  const [orgError, setOrgError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [titleError, setTitleError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"org" | "title" | null>(null);
  const [printing, setPrinting] = useState(false);
  const push = usePushToggle();

  async function togglePush() {
    toast.show(pushToast(await push.toggle()));
  }

  const load = useCallback(() => {
    getWorkplace()
      .then((w) => {
        setWp(w);
        setOrgName(w.org_name);
        setTitle(w.teacher_title);
      })
      .catch((e) => setError(errorMessage(e)));
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  async function copy_(text: string, ok: string) {
    const done = await copyText(text);
    toast.show(done ? { tone: "success", message: ok } : { tone: "error", message: copy.copyFailed });
  }

  async function saveOrg(e: FormEvent) {
    e.preventDefault();
    setBusy("org");
    setOrgError(null);
    try {
      const w = await updateWorkplace({ org_name: orgName.trim() });
      setWp(w);
      setOrgName(w.org_name);
      toast.show({ tone: "success", message: copy.orgNameSaved });
    } catch (err) {
      setOrgError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function saveTitle(e: FormEvent) {
    e.preventDefault();
    const t = title.trim();
    if (!isValidTitle(t)) {
      setTitleError(copy.titleInvalid);
      return;
    }
    setBusy("title");
    setTitleError(null);
    try {
      const w = await updateWorkplace({ teacher_title: t });
      setWp(w);
      setTitle(w.teacher_title);
      toast.show({ tone: "success", message: copy.titleSaved });
    } catch (err) {
      setTitleError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function saveDefaults(patch: Partial<A11yPrefs>) {
    if (!wp) return;
    const before = wp;
    setWp({ ...wp, worker_defaults: { ...wp.worker_defaults, ...patch } });
    try {
      setWp(await updateWorkplace({ worker_defaults: patch }));
      toast.show({ tone: "success", message: prefsCopy.saved });
    } catch (err) {
      setWp(before);
      toast.show({ tone: "error", message: errorMessage(err) });
    }
  }

  if (error) return <EmptyState kind="error" description={error} onRetry={() => {
            setError(null);
            load();
          }} />;
  if (!wp) return <EmptyState kind="loading" />;

  const previewTitle = isValidTitle(title.trim()) ? title.trim() : wp.teacher_title;
  const preview = teacherCopy(previewTitle);

  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <h1 className="text-ui-xl text-ink-900">{copy.title}</h1>

      <Section title={copy.workplaceHeading}>
        <form onSubmit={saveOrg} className="flex flex-col gap-2" noValidate>
          <Field label={copy.orgName} error={orgError ?? undefined}>
            <Input value={orgName} onChange={(e) => setOrgName(e.target.value)} maxLength={40} autoComplete="organization" />
          </Field>
          <div>
            <Button type="submit" size="sm" loading={busy === "org"} disabled={orgName.trim() === wp.org_name}>
              {copy.orgNameSave}
            </Button>
          </div>
        </form>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-ui-base font-semibold text-ink-900">{copy.workplaceCode}</span>
          <span data-testid="workplace-code" className="text-ui-lg font-bold tracking-[0.2em] text-ink-900">
            {wp.workplace_code}
          </span>
          <Button
            size="sm"
            icon={<Copy size={16} strokeWidth={2} aria-hidden="true" />}
            onClick={() => void copy_(wp.workplace_code, copy.codeCopied)}
          >
            {copy.copyCode}
          </Button>
        </div>
      </Section>

      <Section title={copy.deviceHeading}>
        <p className="text-ui-base text-ink-700">{copy.deviceBody}</p>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
          <QrCode text={wp.device_link} label={copy.deviceLink} />
          <div className="flex min-w-0 flex-col gap-2">
            <span className="text-ui-base font-semibold text-ink-900">{copy.deviceLink}</span>
            <code data-testid="device-link" className="break-all rounded-control bg-paper-100 px-2 py-1 text-ui-sm text-ink-900">
              {wp.device_link}
            </code>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                icon={<Copy size={16} strokeWidth={2} aria-hidden="true" />}
                onClick={() => void copy_(wp.device_link, copy.linkCopied)}
              >
                {copy.copyLink}
              </Button>
              <Button size="sm" icon={<Printer size={16} strokeWidth={2} aria-hidden="true" />} onClick={() => setPrinting(true)}>
                {copy.printCard}
              </Button>
            </div>
          </div>
        </div>
      </Section>

      <Section title={prefsCopy.defaultsHeading}>
        <p className="-mt-2 text-ui-sm text-ink-500">{prefsCopy.defaultsHint}</p>
        <PrefsForm idPrefix="defaults" value={wp.worker_defaults} onChange={(p) => void saveDefaults(p)} />
      </Section>

      <Section title={copy.titleHeading}>
        <form onSubmit={saveTitle} className="flex flex-col gap-2" noValidate>
          <Field label={copy.titleLabel} hint={copy.titleHint} error={titleError ?? undefined}>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={6} autoComplete="off" />
          </Field>
          <div>
            <Button type="submit" size="sm" loading={busy === "title"} disabled={title.trim() === wp.teacher_title}>
              {copy.titleSave}
            </Button>
          </div>
        </form>
        <div className="flex flex-col gap-2" data-testid="title-preview">
          <span className="text-ui-sm font-semibold text-ink-700">{copy.titlePreview}</span>
          <ul className="flex flex-col gap-2 rounded-card bg-worker-bg p-3 text-ui-base text-worker-ink">
            <li className="rounded-control bg-worker-help px-3 py-2 font-semibold text-worker-help-ink">{preview.help.sent}</li>
            <li className="rounded-control bg-worker-card px-3 py-2">{preview.help.acked}</li>
            <li className="rounded-control bg-worker-card px-3 py-2">{preview.login.askTeacher}</li>
          </ul>
        </div>
      </Section>

      <Section title={copy.notifyHeading}>
        <Switch
          label={copy.notifyLabel}
          hint={push.available ? copy.notifyHint : `${copy.notifyHint} ${copy.notifyUnavailable}`}
          checked={push.on}
          disabled={!push.available || push.busy}
          onChange={() => void togglePush()}
        />
      </Section>

      <UsageSection />

      <Section title={copy.accountHeading}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-ui-base text-ink-900">
            <span className="text-ink-700">{copy.accountName}</span> <strong>{displayName}</strong>
          </span>
          <Button size="sm" icon={<LogOut size={16} strokeWidth={2} aria-hidden="true" />} onClick={onLogout}>
            {copy.logout}
          </Button>
        </div>
      </Section>

      <PrintCardDialog
        open={printing}
        onClose={() => setPrinting(false)}
        orgName={wp.org_name}
        workplaceCode={wp.workplace_code}
        deviceLink={wp.device_link}
      />
    </div>
  );
}
