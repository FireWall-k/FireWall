// 고친 날(명세 5.3 '상대 시간'). 서버 시각은 타임존 표시 없는 UTC ISO다(contract §0).
// 하루 안: '방금'·'n분 전'·'n시간 전', 그 뒤는 달력 날로 '어제'·'n일 전'(6일까지), 그 뒤는 날짜.
import { relative } from "../copy";

export function parseServerTime(iso: string): number {
  return Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
}

/** 그 시각이 든 날의 0시(기기 시간대). */
function midnight(t: number): number {
  const d = new Date(t);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

export function relativeDate(iso: string, now = Date.now()): string {
  const t = parseServerTime(iso);
  if (Number.isNaN(t)) return "";
  const min = Math.floor((now - t) / 60_000);
  if (min < 1) return relative.justNow;
  if (min < 60) return relative.minutes(min);
  const days = Math.round((midnight(now) - midnight(t)) / 86_400_000);
  if (days <= 0) return relative.hours(Math.floor(min / 60));
  if (days === 1) return relative.yesterday;
  if (days < 7) return relative.days(days);
  const d = new Date(t);
  const n = new Date(now);
  return d.getFullYear() === n.getFullYear()
    ? relative.date(d.getMonth() + 1, d.getDate())
    : relative.dateWithYear(d.getFullYear(), d.getMonth() + 1, d.getDate());
}
