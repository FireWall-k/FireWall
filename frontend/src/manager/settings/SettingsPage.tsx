// 설정(/manager/settings, 명세 5.8, contract §6.2).
// - 사업장: 이름(저장), 사업장 코드 + [코드 복사하기].
// - 기기 연결: QR, /worker?site=… 주소 + [주소 복사하기], [인쇄용 카드 만들기].
// - 근로자 화면 기본값(명세 4.12, 새 근로자에게만), 호칭(한글 1~6자, 근로자 화면 미리보기).
// - 알림: '도움 알림 받기'(웹 푸시는 2c에서 연결). 계정: 이름·로그아웃. 선생님 모드 PIN은 3차라 숨긴다.
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Copy, LogOut, Printer } from "lucide-react";
import type { A11yPrefs } from "../../api";
import { Button, Card, EmptyState, Field, Input, Switch, useToast } from "../../components/ui";
import { teacherCopy } from "../../worker/copy";
import { prefs as prefsCopy, settings as copy } from "../copy";
import { getWorkplace, updateWorkplace } from "../api/workers";
import type { WorkplaceSettings } from "../api/workerTypes";
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
        <Switch label={copy.notifyLabel} hint={`${copy.notifyHint} ${copy.notifyLater}`} checked={false} disabled onChange={() => undefined} />
      </Section>

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
