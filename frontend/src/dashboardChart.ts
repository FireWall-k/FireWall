/** 대시보드 "단계별 소요 시간" 막대 색. 막힘 기록이 있는 단계는 빨간색으로 강조한다. */
export const BAR_COLOR = "#5C7A52";
export const STUCK_BAR_COLOR = "#C24B3F";

/** 막힘 기록이 있는 모든 단계의 위치를 반환한다. */
export function stuckIndices(stuckFlags: boolean[]): number[] {
  return stuckFlags.flatMap((stuck, i) => stuck ? [i] : []);
}
