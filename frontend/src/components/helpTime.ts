// 사업주 화면 도움 요청 시각 표시("방금"·"5분 전"). HelpAlertStrip과 테스트가 함께 쓴다.

/** 서버 시각은 타임존 표시 없는 UTC ISO다(contract 공통 규칙). */
function parseUtc(iso: string): number {
  return Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
}

export function relativeTime(iso: string, now = Date.now()): string {
  const t = parseUtc(iso);
  if (Number.isNaN(t)) return "";
  const min = Math.floor((now - t) / 60_000);
  if (min < 1) return "방금";
  if (min < 60) return `${min}분 전`;
  const h = Math.floor(min / 60);
  return `${h}시간 전`;
}
