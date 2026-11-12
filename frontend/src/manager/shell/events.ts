// 사업주 측정 이벤트 보내기 도우미(contract §5.2, 명세 8.4). 이름·문장 같은 개인정보는 싣지 않는다.
// - track()은 대기열에 넣기만 하고 바로 돌아온다. 2초 동안 모았다가 한 번에(최대 50건) 보낸다.
// - 탭이 숨으면 남은 것을 바로 보낸다(keepalive라 화면을 닫아도 간다).
// - 실패는 화면에 아무것도 띄우지 않고 버린다(다시 보내지 않음).
import { postEvents } from "../api/live";
import type { ClientEvent, EmployerEventName } from "../api/types";

export const EVENT_FLUSH_MS = 2_000;
export const EVENT_BATCH_MAX = 50;

let queue: ClientEvent[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;
let listening = false;

function nowIso(): string {
  return new Date().toISOString();
}

/** 모은 이벤트를 지금 보낸다(50건씩). */
export function flushEvents(): void {
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  while (queue.length > 0) {
    const batch = queue.slice(0, EVENT_BATCH_MAX);
    queue = queue.slice(EVENT_BATCH_MAX);
    postEvents(batch).catch(() => {
      /* 측정 이벤트 실패는 조용히 버린다 */
    });
  }
}

function listen() {
  if (listening || typeof document === "undefined") return;
  listening = true;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushEvents();
  });
}

export function track(
  name: EmployerEventName,
  extra: { task_id?: string | null; step_id?: string | null; value_num?: number | null } = {},
): void {
  listen();
  queue.push({ name, ...extra, at: nowIso() });
  if (queue.length >= EVENT_BATCH_MAX) {
    flushEvents();
    return;
  }
  if (!timer) timer = setTimeout(flushEvents, EVENT_FLUSH_MS);
}

/** 시험용: 대기열을 비운다. */
export function resetEventsForTest(): void {
  queue = [];
  if (timer) clearTimeout(timer);
  timer = null;
}
