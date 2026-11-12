// 근로자·사업장 설정 API(contract §6.2). 화면 시험은 이 모듈을 통째로 목으로 바꾼다(vi.mock).
// 오류는 req가 던지는 ApiError·NetworkError·AuthError 그대로다(message = 서버의 한국어 detail).
import { req, type A11yPrefs } from "../../api";
import type {
  Consent,
  ConsentSubject,
  ConsentType,
  DeleteWorkerResult,
  WorkerRow,
  WorkerStats,
  WorkerWithCode,
  WorkplacePatch,
  WorkplaceSettings,
} from "./workerTypes";

const id = (s: string) => encodeURIComponent(s);

export function listWorkers(): Promise<WorkerRow[]> {
  return req<WorkerRow[]>("/api/workers");
}

/** 근로자 추가. 서버가 사업장 안에서 겹치지 않는 4자리 번호를 만들고, 화면 설정은 사업장 기본값을 쓴다. */
export function createWorker(display_name: string, note?: string): Promise<WorkerWithCode> {
  return req<WorkerWithCode>("/api/workers", { method: "POST", body: JSON.stringify({ display_name }) }).then(
    async (w) => {
      // 만들기 요청은 메모를 받지 않으니 바로 이어서 저장한다(실패해도 근로자는 만들어졌다).
      if (note && note.trim()) {
        try {
          const saved = await updateWorker(w.id, { note: note.trim() });
          return { ...w, ...saved, access_code: w.access_code };
        } catch {
          return w;
        }
      }
      return w;
    },
  );
}

/** 번호 보기: 볼 때마다 감사 기록이 남고 사업주마다 분당 10번까지(넘으면 429). */
export function revealAccessCode(workerId: string): Promise<{ code: string }> {
  return req<{ code: string }>(`/api/workers/${id(workerId)}/access-code/reveal`, { method: "POST" });
}

/** 새 번호 만들기(예전 번호로는 못 들어감). */
export function reissueAccessCode(workerId: string): Promise<WorkerWithCode> {
  return req<WorkerWithCode>(`/api/workers/${id(workerId)}/access-code`, { method: "POST" });
}

/** 지우기: 이름을 그대로 다시 적어야 한다(다르면 422). */
export function deleteWorker(workerId: string, confirmName: string): Promise<DeleteWorkerResult> {
  return req<DeleteWorkerResult>(`/api/workers/${id(workerId)}/delete`, {
    method: "POST",
    body: JSON.stringify({ confirm_name: confirmName }),
  });
}

export function updateWorker(
  workerId: string,
  patch: { display_name?: string; note?: string; ai_note_allowed?: boolean; a11y_prefs?: Partial<A11yPrefs> },
): Promise<WorkerRow> {
  return req<WorkerRow>(`/api/workers/${id(workerId)}`, { method: "PATCH", body: JSON.stringify(patch) });
}

export function workerStats(workerId: string, days = 7): Promise<WorkerStats> {
  return req<WorkerStats>(`/api/employer/workers/${id(workerId)}/stats?days=${days}`);
}

export function listConsents(workerId: string): Promise<Consent[]> {
  return req<Consent[]>(`/api/workers/${id(workerId)}/consents`);
}

export function grantConsent(workerId: string, consent_type: ConsentType, subject: ConsentSubject): Promise<Consent> {
  return req<Consent>(`/api/workers/${id(workerId)}/consents`, {
    method: "POST",
    body: JSON.stringify({ consent_type, subject }),
  });
}

export function revokeConsent(workerId: string, consentId: string): Promise<Consent> {
  return req<Consent>(`/api/workers/${id(workerId)}/consents/${id(consentId)}/revoke`, { method: "POST" });
}

export function exportWorker(workerId: string): Promise<Record<string, unknown>> {
  return req<Record<string, unknown>>(`/api/workers/${id(workerId)}/export`);
}

export function getWorkplace(): Promise<WorkplaceSettings> {
  return req<WorkplaceSettings>("/api/workplace");
}

/** 보낸 칸만 바꾼다. 한 칸이라도 틀리면 아무것도 저장하지 않는다(호칭 422 '호칭은 한글 1~6자로 적어 주세요.'). */
export function updateWorkplace(patch: WorkplacePatch): Promise<WorkplaceSettings> {
  return req<WorkplaceSettings>("/api/workplace", { method: "PATCH", body: JSON.stringify(patch) });
}
