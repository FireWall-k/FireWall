// (2b-2) 편집기 휴대폰 미리보기 칸(명세 5.6): /manager/preview/:taskId를 iframe(폭 360, 0.82 틀)으로 띄우고,
// 아래에 [‹ 이전][다음 ›][처음부터 재생]과 지금 단계 경고 배지를 둔다. 단계 이동은 iframe과 메시지로 주고받는다.
// 편집하면(version이 바뀌면) iframe에 다시 불러오라고 알린다.
import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { Badge, Button } from "../../components/ui";
import { preview as copy } from "../copy";
import { isPreviewMessage, PREVIEW_MSG, type PreviewCommand, type PreviewStateMessage } from "./messages";
import type { PreviewWarning } from "./warnings";

export const PREVIEW_WIDTH = 360;
export const PREVIEW_HEIGHT = 740;
export const PREVIEW_SCALE = 0.82;

export interface PreviewPanelProps {
  taskId: string;
  /** 직무 updated_at 등. 바뀌면 미리보기를 다시 불러온다. */
  version?: string | null;
  onClose: () => void;
  /** 편집기 미리보기 서랍(PreviewDrawer) 안에 넣을 때: 서랍이 제목·닫기를 가지므로 틀만 그린다. */
  bare?: boolean;
}

type PanelState = Omit<PreviewStateMessage, "source">;

export default function PreviewPanel({ taskId, version, onClose, bare = false }: PreviewPanelProps) {
  const frame = useRef<HTMLIFrameElement | null>(null);
  const [state, setState] = useState<PanelState>({ status: "loading", index: 0, total: 0, warnings: [] });

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.source !== frame.current?.contentWindow || !isPreviewMessage<PreviewStateMessage>(e)) return;
      const { status, index, total, warnings } = e.data;
      setState({ status, index, total, warnings });
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  const send = (cmd: PreviewCommand) =>
    frame.current?.contentWindow?.postMessage({ source: PREVIEW_MSG, cmd }, window.location.origin);

  const seen = useRef(version);
  useEffect(() => {
    if (seen.current === version) return;
    seen.current = version;
    frame.current?.contentWindow?.postMessage({ source: PREVIEW_MSG, cmd: "reload" }, window.location.origin);
  }, [version]);

  const ready = state.status === "ready";
  return (
    <section
      aria-labelledby="phone-preview-title"
      data-testid="phone-preview"
      className={bare ? "flex w-fit max-w-full flex-col gap-3" : "flex w-fit flex-col gap-3 rounded-card border border-paper-200 bg-white p-4 shadow-ui-sm"}
    >
      <div className={bare ? "hidden" : "flex items-center justify-between gap-2"}>
        <h2 id="phone-preview-title" className="text-base font-bold text-ink-900">
          {copy.heading}
        </h2>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label={copy.close} icon={<X size={16} strokeWidth={2} aria-hidden="true" />} />
      </div>
      <p className="max-w-[296px] text-sm text-ink-700">{copy.noLog}</p>
      <div
        className="overflow-hidden rounded-[24px] border-4 border-ink-900 bg-ink-900"
        style={{ width: PREVIEW_WIDTH * PREVIEW_SCALE + 8, height: PREVIEW_HEIGHT * PREVIEW_SCALE + 8 }}
      >
        <iframe
          ref={frame}
          title={copy.frameTitle}
          src={`/manager/preview/${encodeURIComponent(taskId)}`}
          data-testid="phone-preview-frame"
          width={PREVIEW_WIDTH}
          height={PREVIEW_HEIGHT}
          style={{ transform: `scale(${PREVIEW_SCALE})`, transformOrigin: "top left", border: 0, display: "block" }}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => send("prev")} disabled={!ready || state.index <= 0} data-testid="preview-prev">
          {copy.prev}
        </Button>
        <span className="min-w-14 text-center text-sm tabular-nums text-ink-900" aria-live="polite" data-testid="preview-position">
          {ready ? copy.position(state.index + 1, state.total) : ""}
        </span>
        <Button size="sm" onClick={() => send("next")} disabled={!ready || state.index >= state.total - 1} data-testid="preview-next">
          {copy.next}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => send("restart")} disabled={!ready} data-testid="preview-restart">
          {copy.restart}
        </Button>
      </div>
      {ready && <PreviewWarnings warnings={state.warnings} />}
    </section>
  );
}

export function PreviewWarnings({ warnings }: { warnings: readonly PreviewWarning[] }) {
  return (
    <ul aria-label={copy.warningsLabel} className="flex max-w-[296px] flex-wrap gap-1.5" data-testid="preview-warnings">
      {warnings.length === 0 ? (
        <li>
          <Badge tone="success">{copy.noWarn}</Badge>
        </li>
      ) : (
        warnings.map((w) => (
          <li key={w} data-warning={w}>
            <Badge tone="warning">{copy.warn[w]}</Badge>
          </li>
        ))
      )}
    </ul>
  );
}
