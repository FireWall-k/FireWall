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
    // 호칭도 사업장 설정이라 함께 지운다(다른 가게의 호칭이 남지 않게, 2d).
    localStorage.removeItem(TEACHER_TITLE_KEY);
    localStorage.removeItem(DEVICE_TOKEN_KEY);
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

// 믿는 기기 표시(서버 TokenOut.device_token). 이 기기에서 한 번 맞게 들어오면 받아 두고 다음 로그인 때 보낸다 —
// 누군가 사업장 코드로 일부러 많이 틀려 사업장 공용 잠금이 걸려도, 이미 쓰던 기기의 근로자는 계속 들어간다.
const DEVICE_TOKEN_KEY = "jobcard_worker_device_v1";

export function getDeviceToken(): string | null {
  try {
    return localStorage.getItem(DEVICE_TOKEN_KEY) || null;
  } catch {
    return null;
  }
}

export function saveDeviceToken(token: string) {
  try {
    if (token) localStorage.setItem(DEVICE_TOKEN_KEY, token);
  } catch {
    /* 저장 못 하면 다음에도 처음 쓰는 기기로 셀 뿐 */
  }
}

// (2d) 근로자 화면에서 사업주를 부르는 호칭(사업장 설정, 기본 '선생님'). 로그인하면 /me의 teacher_title을 받아 두고,
// 로그인 전 화면(번호 넣기·기기 연결·연결 안 됨)도 이 값을 쓴다. 저장값이 없거나 규칙(한글 1~6자) 밖이면 '선생님'.
const TEACHER_TITLE_KEY = "jobcard_teacher_title";
export const DEFAULT_TEACHER_TITLE = "선생님";
const TITLE_RE = /^[가-힣]{1,6}$/;

export function isValidTeacherTitle(v: unknown): v is string {
  return typeof v === "string" && TITLE_RE.test(v);
}

export function getSavedTeacherTitle(): string {
  try {
    const v = localStorage.getItem(TEACHER_TITLE_KEY);
    return isValidTeacherTitle(v) ? v : DEFAULT_TEACHER_TITLE;
  } catch {
    return DEFAULT_TEACHER_TITLE;
  }
}

export function saveTeacherTitle(title: unknown) {
  if (!isValidTeacherTitle(title)) return;
  try {
    if (localStorage.getItem(TEACHER_TITLE_KEY) !== title) localStorage.setItem(TEACHER_TITLE_KEY, title);
  } catch {
    /* 저장 못 하면 로그인 전 화면이 '선생님'으로 부를 뿐 */
  }
}

/**
 * (2d) 기기 연결 주소(/worker?site=CODE)로 열렸을 때: 기기 연결 화면(SetupScreen)이 하는 일을 미리 한다.
 * 저장된 코드와 다르면 예전 가게 이름·호칭·기기 표시를 지우고 새 코드를 저장한다. 바꿨으면 true.
 * 근로자 로그인 자체는 바꾸지 않는다(번호 4자리 + 저장된 사업장 코드).
 */
export function applySiteCode(raw: string | null | undefined): boolean {
  const code = normalizeWorkplaceCode(raw ?? "");
  if (!code || code.length > 32) return false;
  const saved = getSavedWorkplaceCode();
  if (saved === code) return false;
  clearSavedWorkplaceCode();
  saveWorkplaceCode(code);
  return true;
}
