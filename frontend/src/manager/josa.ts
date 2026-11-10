// 조사 고르기(명세 6.7: 짧고 자연스러운 '~해요' 존댓말). "'컵 씻기'을(를)" 같은 기계식 표기 대신
// 마지막 글자의 받침을 보고 을/를, 으로/로를 고른다. 끝의 괄호·따옴표·빈칸은 건너뛰고 본다('… (복사본)' → '본').
// 마지막 글자가 한글도 숫자도 아니면(영어 등) 받침을 알 수 없으므로 지금처럼 괄호 표기를 쓴다.

type Batchim = "none" | "rieul" | "other" | "unknown";

// 숫자를 읽을 때의 받침: 0 영, 1 일, 2 이, 3 삼, 4 사, 5 오, 6 육, 7 칠, 8 팔, 9 구.
const DIGIT: Record<string, Batchim> = {
  "0": "other", "1": "rieul", "2": "none", "3": "other", "4": "none",
  "5": "none", "6": "other", "7": "rieul", "8": "rieul", "9": "none",
};

function lastBatchim(word: string): Batchim {
  const trimmed = String(word).replace(/[\s)\]}'"’”」』.,!?·…-]+$/u, "");
  const ch = trimmed.slice(-1);
  if (!ch) return "unknown";
  if (ch in DIGIT) return DIGIT[ch];
  const code = ch.charCodeAt(0);
  if (code < 0xac00 || code > 0xd7a3) return "unknown";
  const jong = (code - 0xac00) % 28;
  if (jong === 0) return "none";
  return jong === 8 ? "rieul" : "other";
}

/** 목적격: '컵 씻기를', '정리를', '상자 옮김을'. 알 수 없으면 '을(를)'. */
export function eulReul(word: string): string {
  const b = lastBatchim(word);
  if (b === "unknown") return "을(를)";
  return b === "none" ? "를" : "을";
}

/** 방향·수단: '컵으로', '상자로', '물로'(ㄹ 받침은 '로'). 알 수 없으면 '(으)로'. */
export function euroRo(word: string): string {
  const b = lastBatchim(word);
  if (b === "unknown") return "(으)로";
  return b === "other" ? "으로" : "로";
}
