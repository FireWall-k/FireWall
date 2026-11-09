// 사업주 화면 주소(contract §2.2). App.tsx는 '/m/*'를 이 파일에 넘기기만 하고, 화면 주소는 여기에만 더한다.
// 모든 /m 화면은 AppShell(사이드바·상단 바·도움 띠·토스트) 안에 그려지고, 틀은 화면을 옮겨도 다시 만들어지지 않는다
// (도움 요청 폴링이 끊기지 않음).
// 2a-1: /m = 옛 DashboardPage, /m/tasks/new = 옛 ManagerPage(새 직무만), /m/workers = 옛 WorkersPage.
// /m/tasks/:id는 2b-1 편집기가 생길 때까지 열지 않는다(직무 목록으로 돌려보냄).
import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { EmptyState } from "../components/ui";
import DashboardPage from "../pages/DashboardPage";
import ManagerPage from "../pages/ManagerPage";
import WorkersPage from "../pages/WorkersPage";
import { placeholder } from "./copy";
import AppShell from "./shell/AppShell";

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

// 직무 목록 자리. FEATURE 트랙의 TaskListPage(manager/tasks)가 들어오면 바꾼다.
function TasksPlaceholder() {
  return <EmptyState kind="empty" title={placeholder.tasksTitle} description={placeholder.tasksBody} />;
}

function SettingsPlaceholder() {
  return <EmptyState kind="empty" title={placeholder.settingsTitle} description={placeholder.settingsBody} />;
}

export default function ManagerRoutes(props: ManagerRoutesProps) {
  return (
    <Routes>
      <Route element={<ShellLayout {...props} />}>
        <Route index element={<DashboardPage />} />
        <Route path="tasks" element={<TasksPlaceholder />} />
        <Route path="tasks/new" element={<ManagerPage />} />
        <Route path="tasks/:id" element={<Navigate to="/m/tasks" replace />} />
        <Route path="workers" element={<WorkersPage />} />
        <Route path="settings" element={<SettingsPlaceholder />} />
        <Route path="*" element={<Navigate to="/m" replace />} />
      </Route>
    </Routes>
  );
}
