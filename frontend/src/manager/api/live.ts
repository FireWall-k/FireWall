// (2c) 오늘 현황·타임라인·코칭 카드·웹 푸시 구독·측정 이벤트 API(contract §5.2).
// 화면 시험은 이 모듈을 통째로 목으로 바꾼다(vi.mock). 오류는 req가 던지는 ApiError·NetworkError 그대로다.
import { req } from "../../api";
import type { ClientEvent, CoachingCard, LiveOut, PushConfig, TimelineOut } from "./types";

/** 모든 근로자 상태 + 도움 요청. 서버가 사업장마다 4초 동안 같은 답을 준다. */
export function getLive(signal?: AbortSignal): Promise<LiveOut> {
  return req<LiveOut>("/api/employer/live", signal ? { signal } : undefined);
}

/** 근로자 한 명의 그날 타임라인. date는 'YYYY-MM-DD'(현지 날짜), 비우면 오늘. */
export function getTimeline(workerId: string, date?: string): Promise<TimelineOut> {
  const q = date ? `?date=${encodeURIComponent(date)}` : "";
  return req<TimelineOut>(`/api/employer/workers/${encodeURIComponent(workerId)}/timeline${q}`);
}

/** 고치면 좋은 단계(최대 6장). 규칙만으로 만든다. */
export function getCoaching(days = 7): Promise<CoachingCard[]> {
  return req<CoachingCard[]>(`/api/employer/coaching?days=${days}`);
}

export function getPushConfig(): Promise<PushConfig> {
  return req<PushConfig>("/api/employer/push-config");
}

export function savePushSubscription(sub: { endpoint: string; keys: { p256dh: string; auth: string } }): Promise<{ ok: boolean }> {
  return req<{ ok: boolean }>("/api/employer/push-subscriptions", { method: "POST", body: JSON.stringify(sub) });
}

export function deletePushSubscription(endpoint: string): Promise<void> {
  return req<void>("/api/employer/push-subscriptions", { method: "DELETE", body: JSON.stringify({ endpoint }) });
}

/** 측정 이벤트 묶음(최대 50건). 실패는 부른 쪽이 조용히 버린다. */
export function postEvents(events: ClientEvent[]): Promise<void> {
  return req<void>("/api/events", { method: "POST", body: JSON.stringify({ events }), keepalive: true });
}
