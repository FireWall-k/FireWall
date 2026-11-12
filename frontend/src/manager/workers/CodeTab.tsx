// 근로자 상세 '접속 코드': 지금 번호(●●●● + 눈 5초), [새 번호 만들기](확인 창), [인쇄용 카드 만들기].
// 새 번호를 만들면 그 번호를 결과 창에 크게 보이고 [복사하기]·[인쇄용 카드 만들기]를 둔다. 창을 닫으면 번호는 다시
// 가려진다(명세 5.7 '기본은 가림' — 탭 화면에 전체 번호가 계속 남지 않게). 인쇄 카드는 그 밖에는 번호를 볼 때만(reveal) 만든다.
import { useState } from "react";
import { Copy, KeyRound, Printer } from "lucide-react";
import { Button, Card, Dialog, useToast } from "../../components/ui";
import { accessCode } from "../copy";
import { getWorkplace, reissueAccessCode, revealAccessCode } from "../api/workers";
import type { WorkerRow, WorkplaceSettings } from "../api/workerTypes";
import { errorMessage } from "../tasks/listHelpers";
import AccessCodeReveal from "./AccessCodeReveal";
import PrintCardDialog from "./PrintCardDialog";
import { copyText } from "./helpers";

export default function CodeTab({ worker, onChange }: { worker: WorkerRow; onChange: (w: WorkerRow) => void }) {
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [fresh, setFresh] = useState<string | null>(null);
  const [print, setPrint] = useState<{ code: string; wp: WorkplaceSettings } | null>(null);

  async function reissue() {
    setBusy(true);
    try {
      const w = await reissueAccessCode(worker.id);
      setFresh(w.access_code);
      onChange(w);
      setConfirming(false);
      toast.show({ tone: "success", message: accessCode.reissued(worker.display_name) });
    } catch (e) {
      toast.show({ tone: "error", message: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  }

  async function openPrint(known: string | null = null) {
    try {
      const [code, wp] = await Promise.all([known ? Promise.resolve(known) : revealAccessCode(worker.id).then((r) => r.code), getWorkplace()]);
      setPrint({ code, wp });
    } catch (e) {
      toast.show({ tone: "error", message: errorMessage(e) });
    }
  }

  async function copy(code: string) {
    const ok = await copyText(code);
    toast.show(ok ? { tone: "success", message: accessCode.copied } : { tone: "error", message: accessCode.copyFailed });
  }

  const len = worker.code_length || worker.access_code_length;
  return (
    <div className="flex flex-col gap-4">
      <Card className="flex flex-col gap-3">
        <h2 className="text-ui-lg font-bold text-ink-900">{accessCode.current}</h2>
        <AccessCodeReveal workerId={worker.id} name={worker.display_name} length={len} large />
        {len > 4 && <p className="text-ui-sm text-warn-700">{accessCode.shortCode}</p>}
        <div className="flex flex-wrap gap-2">
          <Button icon={<KeyRound size={16} strokeWidth={2} aria-hidden="true" />} onClick={() => setConfirming(true)}>
            {accessCode.reissue}
          </Button>
          <Button icon={<Printer size={16} strokeWidth={2} aria-hidden="true" />} onClick={() => void openPrint()}>
            {accessCode.print}
          </Button>
        </div>
      </Card>
      {fresh ? (
        // key: 확인 창과 결과 창을 다른 창으로 열어 초점을 창 안으로 옮긴다(AddWorkerDialog와 같은 방식). 처음 초점은 [복사하기].
        <Dialog key="fresh" open onClose={() => setFresh(null)} title={accessCode.freshTitle(worker.display_name)} description={accessCode.freshBody}>
          <div className="flex flex-col items-center gap-1 rounded-card border border-paper-200 bg-paper-50 py-5">
            <span data-testid="fresh-code" className="text-[2.5rem] font-bold leading-tight tracking-[0.3em] text-ink-900 tabular-nums">
              {fresh}
            </span>
          </div>
          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <Button data-autofocus="" icon={<Copy size={16} strokeWidth={2} aria-hidden="true" />} onClick={() => void copy(fresh)}>
              {accessCode.copy}
            </Button>
            <Button
              icon={<Printer size={16} strokeWidth={2} aria-hidden="true" />}
              onClick={() => {
                // 창을 둘 겹치지 않게 이 창을 닫고 인쇄 카드를 연다(카드에도 번호가 크게 있다).
                const code = fresh;
                setFresh(null);
                void openPrint(code);
              }}
            >
              {accessCode.print}
            </Button>
            <Button variant="primary" onClick={() => setFresh(null)}>
              {accessCode.freshClose}
            </Button>
          </div>
        </Dialog>
      ) : (
        <Dialog
          key="confirm"
          open={confirming}
          onClose={() => setConfirming(false)}
          title={accessCode.reissueTitle(worker.display_name)}
          description={accessCode.reissueBody}
          confirmLabel={accessCode.reissue}
          onConfirm={() => void reissue()}
          busy={busy}
        />
      )}
      <PrintCardDialog
        open={print !== null}
        onClose={() => setPrint(null)}
        worker={print ? { name: worker.display_name, code: print.code } : undefined}
        orgName={print?.wp.org_name ?? ""}
        workplaceCode={print?.wp.workplace_code ?? ""}
        deviceLink={print?.wp.device_link ?? ""}
      />
    </div>
  );
}
