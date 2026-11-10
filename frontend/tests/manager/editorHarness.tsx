/* eslint-disable react-refresh/only-export-components -- 시험 틀(목·렌더 도우미)이라 화면 새로고침과 상관없다 */
// 편집기·새 직무 화면 시험 틀: manager/api/editor·send·tasks를 통째로 목으로 바꾸고 한 Route(/m/tasks/:id)로 그린다.
import { vi } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { ToastProvider } from "../../src/components/ui";

export const editorMock = {
  getTask: vi.fn(),
  splitPreview: vi.fn(),
  createTask: vi.fn(),
  patchStep: vi.fn(),
  rewriteStep: vi.fn(),
  mergeSteps: vi.fn(),
  addStep: vi.fn(),
  deleteStep: vi.fn(),
  reorderSteps: vi.fn(),
  confirmPicture: vi.fn(),
  confirmPictures: vi.fn(),
  applyPicture: vi.fn(),
  candidates: vi.fn(),
  stepCandidates: vi.fn(),
  stepTts: vi.fn(),
  uploadPhoto: vi.fn(),
  removePhoto: vi.fn(),
  searchPictures: vi.fn(),
  listWorkers: vi.fn(),
};

export const sendMock = {
  sendCheck: vi.fn(),
  recipients: vi.fn(),
  send: vi.fn(),
  confirmPicture: vi.fn(),
};

export const tasksMock = {
  renameTask: vi.fn(),
};

export function resetMocks() {
  for (const f of [...Object.values(editorMock), ...Object.values(sendMock), ...Object.values(tasksMock)]) f.mockReset();
  editorMock.listWorkers.mockResolvedValue([]);
  editorMock.stepCandidates.mockResolvedValue({ step_id: "", reason: "no_candidate", candidates: [] });
  editorMock.candidates.mockResolvedValue({ steps: [] });
}

function Where() {
  const l = useLocation();
  return <output data-testid="where">{l.pathname + l.search}</output>;
}

export async function renderAt(path: string) {
  const { default: TaskWorkspace } = await import("../../src/manager/tasks/TaskWorkspace");
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/m/tasks/:id" element={<TaskWorkspace key="ws" />} />
          <Route path="/m/tasks" element={<p>직무 목록</p>} />
          <Route path="/m" element={<p>홈 화면</p>} />
        </Routes>
        <Where />
      </MemoryRouter>
    </ToastProvider>,
  );
}

/** 화면 글에서 ✦(확인하지 않은 자동 결과 표시) 개수. */
export function sparkleCount(): number {
  return (document.body.textContent ?? "").split("✦").length - 1;
}
