// 근로자 지우기(contract §6.2): 이름을 그대로 다시 적어야 [지우기]가 눌린다(Dialog confirmName).
// 서버도 이름을 다시 비교한다(앞뒤·겹친 공백은 같은 이름). 지운 뒤 이름이 남은 직무가 있으면 알린다.
import { useState } from "react";
import { Dialog, useToast } from "../../components/ui";
import { workerDelete } from "../copy";
import { deleteWorker } from "../api/workers";
import { errorMessage } from "../tasks/listHelpers";

export interface DeleteWorkerDialogProps {
  worker: { id: string; display_name: string } | null;
  onClose: () => void;
  onDeleted: (id: string) => void;
}

export default function DeleteWorkerDialog({ worker, onClose, onDeleted }: DeleteWorkerDialogProps) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (!worker) return null;
  const target = worker;

  async function doDelete() {
    if (busy) return;
    setBusy(true);
    try {
      const r = await deleteWorker(target.id, target.display_name);
      const mentions = r.name_mentions?.length ?? 0;
      const done = workerDelete.done(target.display_name);
      toast.show({ tone: "success", message: mentions > 0 ? `${done} · ${workerDelete.mentions(mentions)}` : done });
      setBusy(false);
      onDeleted(target.id);
    } catch (e) {
      toast.show({ tone: "error", message: errorMessage(e) });
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      tone="danger"
      onClose={onClose}
      title={workerDelete.title(target.display_name)}
      description={workerDelete.description}
      items={[...workerDelete.items]}
      confirmName={target.display_name}
      onConfirm={() => void doDelete()}
      busy={busy}
    />
  );
}
