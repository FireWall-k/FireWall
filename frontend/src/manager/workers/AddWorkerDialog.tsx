// 근로자 추가(명세 5.7): 이름과 특성 메모를 넣는다. 결과 화면에서 4자리 번호를 크게 보이고 [복사하기]와 [인쇄용 카드].
import { useState, type FormEvent } from "react";
import { Copy, Printer } from "lucide-react";
import { Button, Dialog, Field, Input, Textarea, useToast } from "../../components/ui";
import { accessCode, workerAdd } from "../copy";
import { createWorker } from "../api/workers";
import type { WorkerWithCode } from "../api/workerTypes";
import { errorMessage } from "../tasks/listHelpers";
import { copyText } from "./helpers";

export interface AddWorkerDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated: (w: WorkerWithCode) => void;
  onPrint: (w: WorkerWithCode) => void;
}

export default function AddWorkerDialog({ open, onClose, onCreated, onPrint }: AddWorkerDialogProps) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<WorkerWithCode | null>(null);

  function close() {
    if (busy) return;
    setName("");
    setNote("");
    setError(null);
    setCreated(null);
    onClose();
  }

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    if (busy) return;
    if (!name.trim()) {
      setError(workerAdd.nameRequired);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const w = await createWorker(name.trim(), note);
      setCreated(w);
      onCreated(w);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!created) return;
    const ok = await copyText(created.access_code);
    toast.show(ok ? { tone: "success", message: accessCode.copied } : { tone: "error", message: accessCode.copyFailed });
  }

  if (created) {
    return (
      // key: 입력 창과 결과 창을 다른 창으로 다시 열어 초점을 창 안으로 옮긴다(누른 [추가하기]가 사라져 초점이 body로
      // 빠지면 Esc가 먹지 않았다). 처음 초점은 [복사하기].
      <Dialog key="done" open={open} onClose={close} title={workerAdd.doneTitle(created.display_name)} description={workerAdd.doneBody}>
        <div className="flex flex-col items-center gap-1 rounded-card border border-paper-200 bg-paper-50 py-5">
          <span className="text-ui-sm text-ink-700">{workerAdd.codeLabel}</span>
          <span data-testid="new-worker-code" className="text-[3rem] font-bold leading-tight tracking-[0.3em] text-ink-900 tabular-nums">
            {created.access_code}
          </span>
        </div>
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <Button data-autofocus="" icon={<Copy size={16} strokeWidth={2} aria-hidden="true" />} onClick={() => void copy()}>
            {accessCode.copy}
          </Button>
          <Button icon={<Printer size={16} strokeWidth={2} aria-hidden="true" />} onClick={() => {
              // 창을 둘 겹치지 않게 이 창을 닫고 인쇄 카드를 연다(카드에도 번호가 크게 있다).
              const w = created;
              close();
              onPrint(w);
            }}>
            {accessCode.print}
          </Button>
          <Button variant="primary" onClick={close}>
            {workerAdd.close}
          </Button>
        </div>
      </Dialog>
    );
  }

  return (
    <Dialog key="form" open={open} onClose={close} title={workerAdd.title} busy={busy}>
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <Field label={workerAdd.name} error={error ?? undefined} required>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={workerAdd.namePlaceholder}
            maxLength={50}
            autoComplete="off"
          />
        </Field>
        <Field label={workerAdd.note} hint={workerAdd.noteHint}>
          <Textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} rows={3} />
        </Field>
        <div className="flex justify-end">
          <Button type="submit" variant="primary" loading={busy}>
            {workerAdd.submit}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
