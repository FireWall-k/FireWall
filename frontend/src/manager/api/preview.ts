// (2b-2) 편집기 휴대폰 미리보기 API. GET /api/tasks/{id}/preview(사업주 토큰, 서버에 기록을 남기지 않음, 2b-1).
import { req } from "../../api";
import type { TaskPreview } from "./types";

export const previewApi = {
  get: (taskId: string) => req<TaskPreview>(`/api/tasks/${encodeURIComponent(taskId)}/preview`),
};
