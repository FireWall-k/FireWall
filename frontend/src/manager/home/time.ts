// 홈 화면 시각 표시. 서버 시각은 타임존 표시 없는 UTC ISO다(contract 공통 규칙).
import { relative } from "../copy";

export function parseUtc(iso: string | null | undefined): number {
  if (!iso) return Number.NaN;
  return Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
}

/** '방금' · '5분 전' · '2시간 전'. now는 서버 시계로 맞춘 지금(ms). */
export function agoText(iso: string | null | undefined, now: number): string {
  const t = parseUtc(iso);
  if (Number.isNaN(t)) return "";
  const min = Math.floor((now - t) / 60_000);
  if (min < 1) return relative.justNow;
  if (min < 60) return relative.minutes(min);
  return relative.hours(Math.floor(min / 60));
}

/** 지난 분(0 이상). */
export function minutesSince(iso: string | null | undefined, now: number): number {
  const t = parseUtc(iso);
  if (Number.isNaN(t)) return 0;
  return Math.max(0, Math.floor((now - t) / 60_000));
}

/** 편집기 딥링크: 그 단계로 바로(R48 '도움→단계 편집 1번'). fix는 코칭 제안(사진·나누기·쉬운 말). */
export function editorLink(taskId: string, sourceStepId: string | null | undefined, fix?: string): string {
  const q = new URLSearchParams();
  if (sourceStepId) q.set("step", sourceStepId);
  if (fix) q.set("fix", fix);
  const s = q.toString();
  return `/m/tasks/${encodeURIComponent(taskId)}${s ? `?${s}` : ""}`;
}
