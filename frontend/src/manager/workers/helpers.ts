// 근로자·설정 화면 도우미(화면 파일은 부품만 내보내야 해서 따로 둔다 — react-refresh).
import { maskedCode } from "../../workerCodes";

/** 번호를 보인 뒤 다시 가리기까지(명세 5.7: 눈을 누르면 5초). */
export const REVEAL_MS = 5_000;

export { maskedCode };

/** 글자를 클립보드에 넣는다. 못 넣으면 false(권한·http). */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* 아래로 */
  }
  return false;
}

/** 내보낸 JSON을 파일로 저장한다. 파일 이름에 근로자 이름을 넣지 않는다(다운로드 기록에 남는다). */
export function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** 'YYYY-MM-DD' → [월, 일]. */
export function monthDay(day: string): [number, number] {
  const [, m, d] = day.split("-").map((x) => Number(x));
  return [m || 0, d || 0];
}

/** 호칭 규칙(서버와 같음): 한글 음절 1~6자. */
export function isValidTitle(v: string): boolean {
  return /^[가-힣]{1,6}$/.test(v);
}
