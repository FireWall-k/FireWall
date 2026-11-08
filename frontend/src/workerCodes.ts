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
    // 사업장 연결을 끊으면 그 사업장 이름도 지운다(다른 가게 이름이 남아 보이지 않게).
    localStorage.removeItem("jobcard_workplace_name");
  } catch {
    /* 무시 */
  }
}

/** 서버가 전체 코드를 모르는 예전 근로자용 표시(뒤 2자리). */
export function maskedAccessCode(hint: string): string {
  return `••${hint}`;
}

/**
 * 사업주 화면의 접속 코드 표시. 전체 코드가 있으면 그대로(근로자에게 다시 알려 줄 수 있게),
 * 서버도 모르는 예전 근로자면 뒤 2자리로 대신한다(한 번 로그인하거나 재발급하면 전체가 보인다).
 */
export function accessCodeText(w: { access_code?: string | null; access_code_hint: string }): string {
  return w.access_code ?? maskedAccessCode(w.access_code_hint);
}

export const ACCESS_CODE_UNKNOWN_HINT = "근로자가 한 번 로그인하거나 코드를 새로 만들면 전체 번호가 보여요";

// 사업장 이름(예: ○○카페). 근로자 로그인 응답(workplace_name)으로 받아 기기에 저장해 두고,
// 번호 넣기 화면 위 띠에 보인다 — "이 기기가 어느 가게 것인지"를 근로자가 알아보게.
// 로그인 전에 사업장 이름을 알려 주는 공개 API는 없다(사업장 코드가 있는지 엿보는 데 쓰일 수 있어서).
const WORKPLACE_NAME_KEY = "jobcard_workplace_name";

export function getSavedWorkplaceName(): string | null {
  try {
    return localStorage.getItem(WORKPLACE_NAME_KEY) || null;
  } catch {
    return null;
  }
}

export function saveWorkplaceName(name: string) {
  try {
    const trimmed = name.trim();
    if (trimmed) localStorage.setItem(WORKPLACE_NAME_KEY, trimmed);
  } catch {
    /* 저장 실패는 무시한다(화면에 이름이 안 보일 뿐) */
  }
}

/** 번호를 가린 표시(●●●●). 사업주 목록에서 기본으로 보이는 모양 — 어깨 너머로 번호가 새지 않게(명세 5.6). */
export function maskedCode(len: number): string {
  return "●".repeat(Math.max(4, Math.min(len || 4, 12)));
}
