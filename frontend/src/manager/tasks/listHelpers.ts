// 직무 목록 화면 도우미(화면 파일은 부품만 내보내야 해서 따로 둔다 — react-refresh).
import { ApiError, AuthError, NetworkError } from "../../apiErrors";
import { errors } from "../copy";

/** 검색칸에 적고 이만큼 멈추면 찾는다. */
export const SEARCH_DEBOUNCE_MS = 300;

/** 오류 → 사업주에게 보일 문장(무엇이 안 됐는지 + 다음 할 일). 서버 detail은 이미 한국어 문장이다. */
export function errorMessage(e: unknown): string {
  if (e instanceof NetworkError) return errors.network;
  if (e instanceof AuthError) return errors.session;
  if (e instanceof ApiError && e.detail) return e.detail;
  return errors.generic;
}
