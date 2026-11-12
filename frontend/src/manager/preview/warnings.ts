// (2b-2) 미리보기 경고 배지(명세 5.6): 2줄을 넘는 문장, 그림 없음, 묶음 경계.
// 문장 줄 수는 근로자 휴대폰(폭 360, 문장 32px)에서 낱말 단위로 줄을 바꾼다고 보고 어림한다.
import type { PreviewStep } from "../api/types";

export type PreviewWarning = "long" | "no_picture" | "group";

/** 미리보기 휴대폰 폭 360에서 문장이 쓰는 폭(좌우 여백 24씩). */
export const PREVIEW_TEXT_WIDTH = 312;
/** 근로자 휴대폰 문장 기본 글자 크기. */
export const PREVIEW_FONT_PX = 32;

/** 글자 하나의 폭(em). 한글·한자 1, 띄어쓰기·문장 부호 0.3, 그 밖(영문·숫자) 0.6. */
function charEm(ch: string): number {
  if (/\s/.test(ch)) return 0.3;
  if (/[.,!?·'"()]/.test(ch)) return 0.3;
  if (/[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3\u4e00-\u9fff]/.test(ch)) return 1;
  return 0.6;
}

/** 낱말 단위로 줄을 바꿀 때 몇 줄이 되는지 어림한다(낱말이 한 줄보다 길면 글자 단위로 끊음). */
export function estimateLines(sentence: string, widthPx = PREVIEW_TEXT_WIDTH, fontPx = PREVIEW_FONT_PX): number {
  const text = sentence.trim();
  if (!text) return 0;
  const lineEm = widthPx / fontPx;
  const space = charEm(" ");
  let lines = 1;
  let used = 0;
  for (const word of text.split(/\s+/)) {
    const w = [...word].reduce((a, c) => a + charEm(c), 0);
    const need = used === 0 ? w : used + space + w;
    if (need <= lineEm + 1e-9) {
      used = need;
      continue;
    }
    if (used > 0) {
      lines += 1;
      used = 0;
    }
    if (w <= lineEm) {
      used = w;
      continue;
    }
    // 한 줄보다 긴 낱말: 글자 단위로 끊는다.
    for (const c of word) {
      const cw = charEm(c);
      if (used + cw > lineEm + 1e-9) {
        lines += 1;
        used = 0;
      }
      used += cw;
    }
  }
  return lines;
}

/** 한 단계의 경고(보이는 순서대로). */
export function stepWarnings(step: Pick<PreviewStep, "sentence" | "symbol_url" | "picture_state" | "group_break">): PreviewWarning[] {
  const out: PreviewWarning[] = [];
  if (estimateLines(step.sentence) > 2) out.push("long");
  if (!step.symbol_url || step.picture_state === "none") out.push("no_picture");
  if (step.group_break) out.push("group");
  return out;
}
