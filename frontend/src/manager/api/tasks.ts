// 직무 목록 API(contract §2.1). 화면 시험은 이 모듈을 통째로 목으로 바꾼다(vi.mock).
// 오류는 req가 던지는 ApiError·NetworkError·AuthError 그대로다(message = 서버의 한국어 detail).
import { req, type Task } from "../../api";
import type { TaskFilter, TaskListOut, TaskSummaryOut } from "./types";

/** 목록과 걸러보기별 개수. q는 제목 검색(앞뒤 빈칸은 뺀다). */
export function listEmployerTasks(filter: TaskFilter = "all", q = ""): Promise<TaskListOut> {
  const params = new URLSearchParams({ filter });
  const query = q.trim();
  if (query) params.set("q", query);
  return req<TaskListOut>(`/api/employer/tasks?${params.toString()}`);
}

/** 제목 바꾸기. 1~40자가 아니면 422 '제목을 1~40자로 적어 주세요.' */
export function renameTask(id: string, title: string): Promise<Task> {
  return req<Task>(`/api/tasks/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ title }) });
}

/** 보관함으로 옮기기. 보관한 직무는 보내기·배정이 막힌다(409). */
export function archiveTask(id: string): Promise<TaskSummaryOut> {
  return req<TaskSummaryOut>(`/api/tasks/${encodeURIComponent(id)}/archive`, { method: "POST" });
}

/** 보관함에서 꺼내기. */
export function unarchiveTask(id: string): Promise<TaskSummaryOut> {
  return req<TaskSummaryOut>(`/api/tasks/${encodeURIComponent(id)}/unarchive`, { method: "POST" });
}

/** 복제해서 고치기: 새 초안('… (복사본)')을 돌려준다. 원래 직무의 기록은 그대로 남는다. */
export function duplicateTask(id: string): Promise<Task> {
  return req<Task>(`/api/tasks/${encodeURIComponent(id)}/duplicate`, { method: "POST" });
}

/** 완전히 지우기. 보관한 직무만 된다(아니면 409 '보관함으로 옮긴 직무만 완전히 지울 수 있어요.'). */
export function deleteTask(id: string): Promise<{ ok: boolean }> {
  return req<{ ok: boolean }>(`/api/tasks/${encodeURIComponent(id)}`, { method: "DELETE" });
}
