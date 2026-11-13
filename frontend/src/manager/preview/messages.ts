// (2b-2) 편집기(바깥)와 미리보기 iframe(/manager/preview/:taskId) 사이 메시지. 같은 출처만 받는다.
import type { PreviewWarning } from "./warnings";

export const PREVIEW_MSG = "jobcard-preview";

export type PreviewCommand = "prev" | "next" | "restart" | "reload";

/** 바깥 → iframe. */
export interface PreviewCommandMessage {
  source: typeof PREVIEW_MSG;
  cmd: PreviewCommand;
}

/** iframe → 바깥. 지금 단계와 그 단계 경고. */
export interface PreviewStateMessage {
  source: typeof PREVIEW_MSG;
  status: "loading" | "ready" | "error" | "empty";
  index: number;
  total: number;
  warnings: PreviewWarning[];
}

export function isPreviewMessage<T extends { source: string }>(e: MessageEvent): e is MessageEvent<T> {
  return (
    e.origin === window.location.origin &&
    typeof e.data === "object" &&
    e.data !== null &&
    (e.data as { source?: unknown }).source === PREVIEW_MSG
  );
}
