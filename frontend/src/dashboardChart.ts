/** 대시보드 "단계별 소요 시간" 막대 색. 가장 오래 걸린 단계 하나를 빨간색으로 강조한다. */
export const BAR_COLOR = "#5C7A52";
export const SLOWEST_BAR_COLOR = "#C24B3F";

/**
 * 가장 오래 걸린 단계의 위치. 0초보다 긴 단계가 없으면 -1(강조 없음).
 *
 * 처음 화면(목 데이터)은 "최댓값과 같은 막대"를 모두 빨갛게 칠했다 — 아직 아무도 완료하지 않아
 * 전부 0초면 모든 막대가 빨개진다. 0초는 제외하고, 동점이면 앞 단계 하나만 강조한다.
 */
export function slowestIndex(durations: number[]): number {
  let best = -1;
  durations.forEach((d, i) => {
    if (d > 0 && (best === -1 || d > durations[best])) best = i;
  });
  return best;
}
