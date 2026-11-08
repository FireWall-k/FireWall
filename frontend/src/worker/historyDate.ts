// 했던 일 날짜 묶음 제목(명세 4.8). ISO 날짜는 근로자 화면에 쓰지 않는다.
import { COPY } from "./copy";

/** "YYYY-MM-DD"(근로자 현지 날짜) → '오늘' / '어제' / '11월 6일 목요일'. */
export function historyDateLabel(ymd: string, now = new Date()): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd);
  if (!m) return "";
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diff = Math.round((today.getTime() - d.getTime()) / 86_400_000);
  if (diff === 0) return COPY.history.today;
  if (diff === 1) return COPY.history.yesterday;
  return COPY.history.date(d);
}
