// 단축키 안내 창(2b-2, 명세 5.5 '머리의 ? 버튼에서 안내'). 알림 창([닫기]만).
import { Fragment } from "react";
import { Dialog, Kbd } from "../../../components/ui";
import { shortcuts as copy } from "../../copy";

export default function ShortcutHelpDialog({ open, onClose, showPreview = true }: { open: boolean; onClose: () => void; showPreview?: boolean }) {
  const rows = copy.rows.filter((r) => showPreview || r.keys[0] !== "P");
  return (
    <Dialog open={open} onClose={onClose} title={copy.help} description={copy.helpBody}>
      <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2" data-testid="shortcut-help">
        {rows.map((r) => (
          <Fragment key={r.label}>
            <dt className="flex flex-wrap items-center gap-1">
              {r.keys.map((k) => (
                <Kbd key={k}>{k}</Kbd>
              ))}
              {"alt" in r && r.alt && (
                <>
                  <span className="text-ui-xs text-ink-700">{copy.or}</span>
                  {r.alt.map((k) => (
                    <Kbd key={k}>{k}</Kbd>
                  ))}
                </>
              )}
            </dt>
            <dd className="text-ui-base text-ink-900">{r.label}</dd>
          </Fragment>
        ))}
      </dl>
    </Dialog>
  );
}
