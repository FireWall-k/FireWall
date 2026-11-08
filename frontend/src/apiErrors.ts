// API 오류 종류. api.ts에서 다시 내보낸다(import는 어느 쪽에서 해도 같은 클래스).
// 따로 둔 이유: 화면 테스트들이 "../src/api"를 통째로 목으로 바꾸는데, 그러면 이 클래스까지 사라져
// copy.ts의 toWorkerMessage(instanceof 판정)가 깨진다. 이 파일은 목 대상이 아니다.

/** 서버가 2xx가 아닌 응답을 줬다. message = 사업주 화면에 그대로 보여 줄 한국어 문장. */
export class ApiError extends Error {
  status: number;
  /** 서버 detail(문자열일 때만). 배열(검증 오류)이면 null. */
  detail: string | null;
  constructor(status: number, detail: string | null, message?: string) {
    super(message ?? detail ?? `요청 실패 (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** 로그인 밖의 401: 저장된 로그인이 만료됐거나 지워졌다(저장된 로그인은 이미 지웠다). */
export class AuthError extends ApiError {
  constructor(message = "로그인이 필요합니다. 다시 로그인해 주세요.") {
    super(401, null, message);
    this.name = "AuthError";
  }
}

/** 서버에 닿지 못했다(오프라인·DNS·CORS). fetch의 TypeError("Failed to fetch")를 감싼다 — 영어 원문을 화면에 내지 않게. */
export class NetworkError extends Error {
  constructor(message = "인터넷 연결을 확인해 주세요.", options?: { cause?: unknown }) {
    super(message, options);
    this.name = "NetworkError";
  }
}
