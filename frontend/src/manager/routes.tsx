// 사업주 화면 주소(contract §2.2). App.tsx는 '/m/*'를 이 파일에 넘기기만 하고, 화면 주소는 여기에만 더한다.
// 모든 /m 화면은 AppShell(사이드바·상단 바·도움 띠·토스트) 안에 그려지고, 틀은 화면을 옮겨도 다시 만들어지지 않는다
// (도움 요청 폴링이 끊기지 않음).
// 2c: /m = 홈·오늘 현황(HomePage). 옛 DashboardPage·WorkersPage는 2d에서 지웠다(/m/legacy-dashboard도 없앰).
// /m/tasks = 직무 목록(TaskListPage),
// /m/tasks/new·/m/tasks/:id = 새 직무·편집기(2b-1, 한 Route·같은 key — TaskWorkspace, ?example=1은 예시로 채움).
// 편집기는 ?step=(&fix=)를 받아 그 단계를 열고 초점을 옮긴다(홈의 도움 띠·코칭 카드가 이 주소로 온다).
// 2d: /m/workers = 근로자 목록, /m/workers/:id = 근로자 상세(탭 4개), /m/settings = 설정.
// /m/pictures = 사이드바에서 숨김(3차, 지금은 홈으로).
import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import HomePage from "./home/HomePage";
import SettingsPage from "./settings/SettingsPage";
import WorkerDetailPage from "./workers/WorkerDetailPage";
import WorkerListPage from "./workers/WorkerListPage";
import AppShell from "./shell/AppShell";
import TaskListPage from "./tasks/TaskListPage";
import TaskWorkspace from "./tasks/TaskWorkspace";

export interface ManagerRoutesProps {
  displayName: string;
  onLogout: () => void;
}

function ShellLayout({ displayName, onLogout }: ManagerRoutesProps) {
  return (
    <AppShell displayName={displayName} onLogout={onLogout}>
      <Outlet />
    </AppShell>
  );
}

export default function ManagerRoutes(props: ManagerRoutesProps) {
  return (
    <Routes>
      <Route element={<ShellLayout {...props} />}>
        <Route index element={<HomePage />} />
        <Route path="tasks" element={<TaskListPage />} />
        {/* 'new'도 이 Route가 받는다 — 초안을 만든 뒤 주소가 바뀌어도 화면이 다시 만들어지지 않게(contract §2.2). */}
        <Route path="tasks/:id" element={<TaskWorkspace key="task-workspace" />} />
        <Route path="workers" element={<WorkerListPage />} />
        <Route path="workers/:id" element={<WorkerDetailPage />} />
        <Route path="settings" element={<SettingsPage displayName={props.displayName} onLogout={props.onLogout} />} />
        <Route path="*" element={<Navigate to="/m" replace />} />
      </Route>
    </Routes>
  );
}
