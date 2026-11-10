// 근로자 상세 '동의·개인정보'(옛 WorkersPage 로직을 옮김). window.confirm 대신 Dialog로 묻는다.
// - 개인정보 수집·이용 동의 / 자동 처리·국외 이전 동의: 받음·아직 없음 배지, [당사자에게 받았어요]·[보호자에게 받았어요], [철회 기록하기].
// - 특성 메모 + [메모 저장하기], '자동 코칭에 메모 쓰기' 스위치(자동 처리 동의가 없으면 보내지 않는다는 안내).
// - [기록 내려받기](열람 요구), [이 근로자 지우기](이름 다시 적기).
import { useState } from "react";
import { Download, Trash2 } from "lucide-react";
import { Badge, Button, Card, Dialog, Field, Switch, Textarea, useToast } from "../../components/ui";
import { consent as copy } from "../copy";
import { exportWorker, grantConsent, listConsents, revokeConsent, updateWorker } from "../api/workers";
import type { ConsentSubject, ConsentType, WorkerRow } from "../api/workerTypes";
import { errorMessage } from "../tasks/listHelpers";
import { downloadJson } from "./helpers";

type Ask =
  | { kind: "grant"; type: ConsentType; subject: ConsentSubject }
  | { kind: "revoke"; type: ConsentType };

const LABEL: Record<ConsentType, string> = { personal_info: copy.personal, ai_processing: copy.automated };
const FIELD: Record<ConsentType, "personal_info_consent" | "ai_consent"> = {
  personal_info: "personal_info_consent",
  ai_processing: "ai_consent",
};
const WHO: Record<ConsentSubject, string> = { self: copy.self, guardian: copy.guardian };

export default function ConsentTab({
  worker,
  onChange,
  onDelete,
}: {
  worker: WorkerRow;
  onChange: (w: WorkerRow) => void;
  onDelete: () => void;
}) {
  const toast = useToast();
  const [ask, setAsk] = useState<Ask | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function run() {
    if (!ask) return;
    setBusy(true);
    const label = LABEL[ask.type];
    try {
      if (ask.kind === "grant") {
        await grantConsent(worker.id, ask.type, ask.subject);
        onChange(withConsent(worker, ask.type, true));
        toast.show({ tone: "success", message: copy.recorded(label) });
      } else {
        const list = await listConsents(worker.id);
        await Promise.all(list.filter((c) => c.consent_type === ask.type && !c.revoked_at).map((c) => revokeConsent(worker.id, c.id)));
        onChange(withConsent(worker, ask.type, false));
        toast.show({ tone: "success", message: copy.revoked(label) });
      }
      setAsk(null);
    } catch (e) {
      toast.show({ tone: "error", message: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  }

  async function saveNote() {
    if (note === null) return;
    try {
      onChange(await updateWorker(worker.id, { note }));
      setNote(null);
      toast.show({ tone: "success", message: copy.noteSaved });
    } catch (e) {
      toast.show({ tone: "error", message: errorMessage(e) });
    }
  }

  async function toggleNote(allowed: boolean) {
    try {
      onChange(await updateWorker(worker.id, { ai_note_allowed: allowed }));
    } catch (e) {
      toast.show({ tone: "error", message: errorMessage(e) });
    }
  }

  async function download() {
    try {
      downloadJson(`worker-${worker.id.slice(0, 8)}.json`, await exportWorker(worker.id));
      toast.show({ tone: "success", message: copy.exported });
    } catch (e) {
      toast.show({ tone: "error", message: errorMessage(e) });
    }
  }

  const dialog = ask && {
    title: ask.kind === "grant" ? copy.grantTitle(LABEL[ask.type]) : copy.revokeTitle(LABEL[ask.type]),
    description:
      ask.kind === "grant"
        ? `${copy.grantBody(WHO[ask.subject], worker.display_name)}${ask.type === "ai_processing" ? ` ${copy.automatedBody}` : ""}`
        : ask.type === "ai_processing"
          ? copy.automatedRevokeBody
          : copy.personalRevokeBody,
  };

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-ui-lg font-bold text-ink-900">{copy.heading}</h2>
      {(["personal_info", "ai_processing"] as const).map((type) => {
        const on = !!worker[FIELD[type]];
        return (
          <Card key={type} className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-ui-base font-semibold text-ink-900">{LABEL[type]}</h3>
              {type === "ai_processing" ? (
                <Badge tone={on ? "success" : "warning"}>{`${copy.automatedBadge} ${on ? copy.received : copy.notReceived}`}</Badge>
              ) : (
                <Badge tone={on ? "success" : "warning"}>{on ? copy.received : copy.notReceived}</Badge>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              {on ? (
                <Button size="sm" onClick={() => setAsk({ kind: "revoke", type })}>
                  {copy.revoke}
                </Button>
              ) : (
                (["self", "guardian"] as const).map((subject) => (
                  <Button key={subject} size="sm" onClick={() => setAsk({ kind: "grant", type, subject })}>
                    {copy.recordFrom(WHO[subject])}
                  </Button>
                ))
              )}
            </div>
          </Card>
        );
      })}

      <Card className="flex flex-col gap-3">
        <Field label={copy.note} hint={copy.noteHint}>
          <Textarea value={note ?? worker.note ?? ""} onChange={(e) => setNote(e.target.value)} maxLength={300} rows={3} />
        </Field>
        <div className="flex justify-end">
          <Button size="sm" disabled={note === null} onClick={() => void saveNote()}>
            {copy.noteSave}
          </Button>
        </div>
        <Switch
          label={copy.noteForCoaching}
          hint={worker.ai_note_allowed && !worker.ai_consent ? copy.noteNeedsConsent : undefined}
          checked={worker.ai_note_allowed}
          onChange={(v) => void toggleNote(v)}
        />
      </Card>

      <Card className="flex flex-col gap-2">
        <p className="text-ui-sm text-ink-700">{copy.exportHint}</p>
        <div>
          <Button size="sm" icon={<Download size={16} strokeWidth={2} aria-hidden="true" />} onClick={() => void download()}>
            {copy.export}
          </Button>
        </div>
      </Card>

      <Card className="flex flex-col gap-2 border-danger-700/20">
        <h3 className="text-ui-base font-semibold text-danger-700">{copy.deleteHeading}</h3>
        <div>
          <Button variant="danger" size="sm" icon={<Trash2 size={16} strokeWidth={2} aria-hidden="true" />} onClick={onDelete}>
            {copy.deleteButton}
          </Button>
        </div>
      </Card>

      <Dialog
        open={!!ask}
        onClose={() => setAsk(null)}
        title={dialog?.title ?? ""}
        description={dialog?.description}
        onConfirm={() => void run()}
        busy={busy}
      />
    </div>
  );
}

function withConsent(w: WorkerRow, type: ConsentType, on: boolean): WorkerRow {
  const next = { ...w, [FIELD[type]]: on };
  next.consent_state = !next.personal_info_consent ? "missing" : next.ai_consent ? "complete" : "ai_missing";
  return next;
}
