// 보내기 시트(명세 5.6, contract §3.6·3.7, tasks §4.3 SendSheet). 오른쪽 480(좁은 화면은 꽉 채움).
// - 머리 '보내기 전에 확인해요'. 고친 내용이 있으면 '고친 내용도 함께 보내요 · n번째 버전'.
// - 점검표: 서버가 code와 숫자만 보낸다 → 글은 copy.ts. total=0 줄은 숨긴다. 막힌 줄·경고 줄을 누르면 그 단계로 간다.
//   '✦ 자동으로 켠 조심 표시가 n개 있어요'는 경고만 하고 보내기를 막지 않는다(창업자 결정).
// - 받는 사람: 이름 + 오늘 상태 글. 접속 코드는 이 시트에 싣지 않는다. 미리 체크: 이 직무를 지난번 받은 사람 → 없으면
//   사업장의 가장 최근 묶음 → 근로자가 1명이면 그 사람. 오늘 이미 다 한 사람은 미리 체크하지 않는다.
// - 언제: 오늘(기본)·내일·날짜. [n명에게 보내기]. 성공하면 닫고 부모가 토스트, 실패하면 시트 안에 오류를 남긴다.
import { useEffect, useMemo, useState } from "react";
import { ChevronRight, CircleAlert, CircleCheck, CircleX, Send } from "lucide-react";
import type { Worker } from "../../../api";
import { Button, Checkbox, EmptyState, Field, Input, Sheet } from "../../../components/ui";
import { cn } from "../../../cn";
import { editorApi } from "../../api/editor";
import { sendApi } from "../../api/send";
import type { Recipients, SendBlock, SendCheck, SendDay, SendResult, SendWarning, TodayStatus } from "../../api/types";
import { person, sendCheckLabel, sendSheet as copy, ui } from "../../copy";
import { errorMessage } from "../listHelpers";
import { precheck } from "./sendRules";

export interface SendSheetProps {
  open: boolean;
  onClose: () => void;
  taskId: string;
  /** 보낸 뒤 고친 내용이 있는지(다음 버전 번호를 보인다). */
  hasUnsentChanges: boolean;
  /** 마지막으로 보낸 버전 번호(없으면 null). */
  versionNo: number | null;
  /** 점검표의 실패·경고 줄을 눌렀을 때: 그 단계로 간다(시트는 닫힌다). */
  /** code: 누른 점검표 줄(auto_caution이면 조심 스위치로 초점을 옮긴다). */
  onGoToStep: (stepId: string, code?: string) => void;
  onSent: (result: SendResult) => void;
}

export default function SendSheet(props: SendSheetProps) {
  if (!props.open) return null;
  return <SendSheetBody {...props} />;
}

interface Loaded {
  check: SendCheck;
  recipients: Recipients;
  workers: Worker[];
}

function SendSheetBody({ onClose, taskId, hasUnsentChanges, versionNo, onGoToStep, onSent }: SendSheetProps) {
  const [data, setData] = useState<Loaded | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [fromLast, setFromLast] = useState(false);
  const [query, setQuery] = useState("");
  const [when, setWhen] = useState<"today" | "tomorrow" | "date">("today");
  const [date, setDate] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([sendApi.sendCheck(taskId), sendApi.recipients(taskId), editorApi.listWorkers()])
      .then(([check, recipients, workers]) => {
        if (!alive) return;
        const pre = precheck(recipients, workers);
        setData({ check, recipients, workers });
        setSelected(pre.ids);
        setFromLast(pre.fromLast);
        setLoadError(null);
      })
      .catch((e) => alive && setLoadError(errorMessage(e) || copy.loadFailed));
    return () => {
      alive = false;
    };
  }, [taskId, nonce]);

  const visibleWorkers = useMemo(() => {
    const q = query.trim();
    const all = data?.workers ?? [];
    return q ? all.filter((w) => w.display_name.includes(q)) : all;
  }, [data, query]);

  const n = selected.size;
  const day: SendDay | null = when === "date" ? (date || null) : when;
  const ok = !!data?.check.ok;
  const inProgress = (data?.workers ?? []).filter((w) => selected.has(w.id) && data?.recipients.today_status[w.id] === "in_progress");

  function toggle(id: string, v: boolean) {
    setSelected((cur) => {
      const next = new Set(cur);
      if (v) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  async function submit() {
    if (!data || sending) return;
    if (n === 0) {
      setError(copy.needRecipient);
      return;
    }
    if (!day) {
      setError(copy.needDate);
      return;
    }
    setSending(true);
    setError(null);
    try {
      const result = await sendApi.send(taskId, [...selected], day);
      onSent(result);
    } catch (e) {
      setError(errorMessage(e) || copy.failed);
      // 서버 검사에 막혔으면 점검표를 다시 읽어 막힌 줄을 보인다.
      sendApi.sendCheck(taskId).then((check) => setData((cur) => (cur ? { ...cur, check } : cur)), () => {});
    } finally {
      setSending(false);
    }
  }

  const blocks: SendBlock[] = (data?.check.blocking ?? []).filter((b) => b.total > 0 && b.code !== "archived" && b.code !== "no_steps");
  const special = (data?.check.blocking ?? []).filter((b) => (b.code === "archived" || b.code === "no_steps") && b.done < b.total);
  const warns: SendWarning[] = (data?.check.warnings ?? []).filter((w) => w.count > 0);

  return (
    <Sheet
      open
      onClose={onClose}
      title={copy.title}
      description={hasUnsentChanges && versionNo ? copy.versionLine(versionNo + 1) : undefined}
      footer={
        data ? (
          <>
            <Button variant="secondary" onClick={onClose}>
              {ui.cancel}
            </Button>
            <Button
              variant="primary"
              onClick={() => void submit()}
              loading={sending}
              disabled={!ok || n === 0}
              icon={<Send size={16} strokeWidth={2} aria-hidden="true" />}
              data-testid="send-submit"
            >
              {copy.submit(n)}
            </Button>
          </>
        ) : undefined
      }
    >
      {loadError ? (
        <EmptyState kind="error" title={loadError} onRetry={() => setNonce((x) => x + 1)} />
      ) : !data ? (
        <EmptyState kind="loading" title={copy.loading} />
      ) : (
        <div className="flex flex-col gap-6">
          <section aria-labelledby="send-checks" className="flex flex-col gap-2">
            <h3 id="send-checks" className="text-ui-md font-bold text-ink-900">
              {copy.checksHeading}
            </h3>
            <ul className="flex flex-col gap-1.5" data-testid="send-checklist">
              {special.map((b) => (
                <li key={b.code} className="flex items-center gap-2 text-ui-base font-semibold text-danger-700">
                  <CircleX size={16} strokeWidth={2} aria-hidden="true" />
                  {b.code === "archived" ? copy.archived : copy.noSteps}
                </li>
              ))}
              {blocks.map((b) => {
                const passed = b.done >= b.total;
                const label = sendCheckLabel(b.code, b);
                return (
                  <li key={b.code} data-code={b.code} data-passed={passed}>
                    {passed ? (
                      <span className="flex min-h-8 items-center gap-2 text-ui-base text-ink-900">
                        <CircleCheck size={16} strokeWidth={2} aria-hidden="true" className="text-ok-700" />
                        {label}
                      </span>
                    ) : (
                      <CheckLink tone="danger" label={label} onClick={() => b.step_ids[0] && onGoToStep(b.step_ids[0], b.code)} />
                    )}
                  </li>
                );
              })}
              {warns.map((w) => (
                <li key={w.code} data-code={w.code}>
                  <CheckLink tone="warning" label={sendCheckLabel(w.code, w)} onClick={() => w.step_ids[0] && onGoToStep(w.step_ids[0], w.code)} />
                </li>
              ))}
            </ul>
            {!ok ? (
              <p className="text-ui-sm text-ink-700">{copy.checksHint}</p>
            ) : warns.length > 0 ? (
              <p className="text-ui-sm text-ink-700">{copy.warnsHint}</p>
            ) : null}
          </section>

          <section aria-labelledby="send-recipients" className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 id="send-recipients" className="text-ui-md font-bold text-ink-900">
                {copy.recipientsHeading}
              </h3>
              {data.workers.length > 1 && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    setSelected(n === data.workers.length ? new Set() : new Set(data.workers.map((w) => w.id)))
                  }
                >
                  {n === data.workers.length ? copy.clearAll : copy.selectAll}
                </Button>
              )}
            </div>
            {fromLast && n > 0 && <p className="text-ui-sm text-ink-700">{copy.prefilled}</p>}
            {data.workers.length > 5 && (
              <Field label={copy.searchLabel}>
                <Input value={query} onChange={(e) => setQuery(e.target.value)} />
              </Field>
            )}
            {data.workers.length === 0 ? (
              <p className="text-ui-base text-ink-700">{copy.noWorkers}</p>
            ) : visibleWorkers.length === 0 ? (
              <p className="text-ui-base text-ink-700">{copy.noMatch}</p>
            ) : (
              <ul className="flex flex-col gap-2" data-testid="send-recipients">
                {visibleWorkers.map((w) => {
                  const st: TodayStatus = data.recipients.today_status[w.id] ?? "none";
                  return (
                    <li key={w.id} className="rounded-control border border-paper-200 px-3 py-2">
                      <Checkbox
                        label={person(w.display_name)}
                        hint={copy.status[st] || undefined}
                        checked={selected.has(w.id)}
                        onChange={(v) => toggle(w.id, v)}
                      />
                    </li>
                  );
                })}
              </ul>
            )}
            {inProgress.length > 0 && (
              <ul className="flex flex-col gap-1">
                {inProgress.map((w) => (
                  <li key={w.id} className="text-ui-sm text-warn-700">
                    {copy.inProgressNote(w.display_name)}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-ui-md font-bold text-ink-900">{copy.whenHeading}</legend>
            <div className="flex flex-wrap gap-2">
              {(
                [
                  ["today", copy.today],
                  ["tomorrow", copy.tomorrow],
                  ["date", copy.pickDate],
                ] as const
              ).map(([v, label]) => (
                <label
                  key={v}
                  className={cn(
                    "inline-flex min-h-control cursor-pointer items-center gap-2 rounded-control border px-3 text-ui-base coarse:min-h-control-coarse",
                    when === v ? "border-moss-600 bg-paper-100 font-semibold text-ink-900" : "border-line-strong bg-white text-ink-900",
                  )}
                >
                  <input type="radio" name="send-when" value={v} checked={when === v} onChange={() => setWhen(v)} className="accent-moss-600" />
                  {label}
                </label>
              ))}
            </div>
            {when === "date" && (
              <Field label={copy.dateLabel}>
                <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
              </Field>
            )}
          </fieldset>

          {error && (
            <p role="alert" className="rounded-control bg-danger-50 p-3 text-ui-base font-semibold text-danger-700">
              {error}
            </p>
          )}
        </div>
      )}
    </Sheet>
  );
}

function CheckLink({ tone, label, onClick }: { tone: "danger" | "warning"; label: string; onClick: () => void }) {
  const Icon = tone === "danger" ? CircleX : CircleAlert;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={copy.goToStep(label)}
      className={cn(
        "flex min-h-8 w-full items-center gap-2 rounded-control px-1 text-left text-ui-base font-semibold hover:bg-paper-100 coarse:min-h-control-coarse",
        tone === "danger" ? "text-danger-700" : "text-warn-700",
      )}
    >
      <Icon size={16} strokeWidth={2} aria-hidden="true" className="shrink-0" />
      <span className="min-w-0 flex-1">{label}</span>
      <ChevronRight size={16} strokeWidth={2} aria-hidden="true" className="shrink-0" />
    </button>
  );
}
