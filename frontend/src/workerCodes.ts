// 사업장 코드(기기 저장)와 접속 코드 표시 도우미.
// api.ts와 분리한 이유: 화면 테스트들이 "../src/api"를 통째로 목으로 바꾸므로, 여기 있는
// 순수 함수·기기 저장 로직까지 사라지지 않게 따로 둔다.

// 근로자 로그인은 "사업장 코드 + 접속 코드"다. 같은 작업장 기기는 늘 같은 사업장이므로
// 사업장 코드는 기기에 한 번 저장해 두고 근로자는 자기 접속 코드만 누른다
// (발달장애 근로자에게 코드 두 개를 매번 입력하게 하면 로그인 자체가 장벽이 된다).
// 로그아웃(clearAuth)해도 지우지 않는다 — 다음 근로자가 같은 기기를 쓴다.
const WORKPLACE_KEY = "jobcard_workplace_code";

/** 서버와 같은 정규화: 공백·하이픈 제거 + 대문자. ' demo-01 '도 DEMO01로 본다. */
export function normalizeWorkplaceCode(raw: string): string {
  return raw.replace(/[\s-]+/g, "").toUpperCase();
}

// localStorage는 사생활 보호 모드·차단 설정에서 예외를 던질 수 있다. 그때는 저장 없이
// 매번 입력하게 될 뿐 로그인 자체는 되어야 한다.
export function getSavedWorkplaceCode(): string | null {
  try {
    return localStorage.getItem(WORKPLACE_KEY) || null;
  } catch {
    return null;
  }
}

export function saveWorkplaceCode(code: string) {
  try {
    localStorage.setItem(WORKPLACE_KEY, normalizeWorkplaceCode(code));
  } catch {
    /* 저장 실패는 무시한다(위 주석) */
  }
}

export function clearSavedWorkplaceCode() {
  try {
    localStorage.removeItem(WORKPLACE_KEY);
  } catch {
    /* 무시 */
  }
}

/** 서버는 평문 접속 코드를 돌려주지 않는다(해시만 저장). 목록에는 뒤 2자리 힌트만 보인다. */
export function maskedAccessCode(hint: string): string {
  return `••${hint}`;
}
