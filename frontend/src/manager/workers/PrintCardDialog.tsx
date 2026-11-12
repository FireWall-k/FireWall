// 인쇄용 카드(명세 5.7·5.8): 근로자 카드 = 이름·QR·번호, 기기 연결 카드 = 사업장 이름·QR·사업장 코드.
// [인쇄하기]는 브라우저 인쇄를 연다. 인쇄할 때는 data-print-area 안만 보인다(index.css @media print).
import { Printer } from "lucide-react";
import { Button, Dialog } from "../../components/ui";
import { printCard } from "../copy";
import QrCode from "./QrCode";

export interface PrintCardDialogProps {
  open: boolean;
  onClose: () => void;
  /** 근로자 카드면 이름과 번호, 기기 연결 카드면 생략. */
  worker?: { name: string; code: string };
  orgName: string;
  workplaceCode: string;
  deviceLink: string;
}

export default function PrintCardDialog({ open, onClose, worker, orgName, workplaceCode, deviceLink }: PrintCardDialogProps) {
  return (
    <Dialog open={open} onClose={onClose} title={worker ? printCard.title : printCard.deviceHeading}>
      <div data-print-area="" className="flex flex-col items-center gap-3 rounded-card border border-paper-200 bg-white p-5 text-center">
        <p className="text-ui-sm text-ink-700">{orgName}</p>
        {worker && <p className="text-ui-xl font-bold text-ink-900">{printCard.workerHeading(worker.name)}</p>}
        {deviceLink && <QrCode text={deviceLink} size={168} label={printCard.qrLabel} />}
        {worker ? (
          <div className="flex flex-col items-center">
            <span className="text-ui-sm text-ink-700">{printCard.codeLabel}</span>
            <span className="text-[2.5rem] font-bold leading-tight tracking-[0.3em] text-ink-900 tabular-nums" data-testid="print-code">
              {worker.code}
            </span>
          </div>
        ) : (
          <div className="flex flex-col items-center">
            <span className="text-ui-sm text-ink-700">{printCard.siteLabel}</span>
            <span className="text-ui-xl font-bold tracking-[0.2em] text-ink-900">{workplaceCode}</span>
          </div>
        )}
        <p className="text-ui-sm text-ink-700">{printCard.howTo}</p>
      </div>
      <div className="mt-4 flex justify-end">
        <Button variant="primary" icon={<Printer size={16} strokeWidth={2} aria-hidden="true" />} onClick={() => window.print()}>
          {printCard.print}
        </Button>
      </div>
    </Dialog>
  );
}
