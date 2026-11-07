// className 조합 도우미. 조건부 클래스를 문자열 이어붙이기("a " + (c ? "b" : "c"))로 만들면
// eslint-plugin-tailwindcss가 그 안의 클래스 이름을 검사하지 못한다 — 정의되지 않은 클래스(min-h-touch가
// 정의 없이 쓰였던 Phase 0.4 사고)가 이어붙인 쪽에 숨으면 린트를 그대로 통과한다.
// cn(...) 호출은 eslint.config.js의 callees 설정으로 플러그인이 인자(문자열·삼항·&&)를 모두 검사한다.
// clsx를 새로 들이지 않은 이유: 필요한 기능이 falsy 걸러 내고 공백으로 잇기뿐이라 의존성을 늘릴 만큼이 아니다.
export type ClassValue = string | false | null | undefined;

export function cn(...parts: ClassValue[]): string {
  return parts.filter(Boolean).join(" ");
}
