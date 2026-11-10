// 사업주 화면 주소(contract §2.2). App.tsx는 '/m/*'를 이 파일에 넘기기만 하고, 화면 주소는 여기에만 더한다.
// 모든 /m 화면은 AppShell(사이드바·상단 바·도움 띠·토스트) 안에 그려지고, 틀은 화면을 옮겨도 다시 만들어지지 않는다
// (도움 요청 폴링이 끊기지 않음).
// 2a-1: /m = 옛 DashboardPage, /m/tasks = 직무 목록(TaskListPage), /m/tasks/new = 옛 ManagerPage(새 직무만, ?example=1은 예시로 채움),
// /m/workers = 옛 WorkersPage, /m/settings = '준비 중', /m/pictures = 사이드바에서 숨김(3차, 지금은 홈으로).
// /m/tasks/:id는 2b-1 편집기가 생길 때까지 열지 않는다(직무 목록으로 돌려보냄).
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { EmptyState } from "../components/ui";
import DashboardPage from "../pages/DashboardPage";
import ManagerPage from "../pages/ManagerPage";
import WorkersPage from "../pages/WorkersPage";
import { placeholder } from "./copy";
import AppShell from "./shell/AppShell";
import TaskListPage from "./tasks/TaskListPage";

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

// 준비 중 화면에도 화면 이름(h1)을 둔다(다른 /m 화면과 같게, axe page-has-heading-one).
function SettingsPlaceholder() {
  return (
    <div className="flex flex-col gap-5">
      <h1 className="text-ui-xl text-ink-900">{placeholder.settingsHeading}</h1>
      <EmptyState kind="empty" title={placeholder.settingsTitle} description={placeholder.settingsBody} />
    </div>
  );
}

// 옛 ManagerPage는 ?example=1을 처음 그릴 때만 읽는다. 예시 화면에서 [+ 새 직무]로 빈 화면에 가면 다시 그리게
// 검색어를 key로 쓴다(같은 주소로 다시 오면 그대로).
function NewTaskRoute() {
  const { search } = useLocation();
  return <ManagerPage key={search} />;
}

export default function ManagerRoutes(props: ManagerRoutesProps) {
  return (
    <Routes>
      <Route element={<ShellLayout {...props} />}>
        <Route index element={<DashboardPage />} />
        <Route path="tasks" element={<TaskListPage />} />
        <Route path="tasks/new" element={<NewTaskRoute />} />
        <Route path="tasks/:id" element={<Navigate to="/m/tasks" replace />} />
        <Route path="workers" element={<WorkersPage />} />
        <Route path="settings" element={<SettingsPlaceholder />} />
        <Route path="*" element={<Navigate to="/m" replace />} />
      </Route>
    </Routes>
  );
}
