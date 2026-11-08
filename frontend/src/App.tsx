import { BrowserRouter, Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { Briefcase, BarChart3, LogOut, Users } from "lucide-react";
import { useState, type ReactNode } from "react";
import { clearAuth, getAuth, type AuthState, type Role } from "./api";
import { cn } from "./cn";
import { getSavedWorkplaceCode } from "./workerCodes";
import HelpAlertStrip from "./components/HelpAlertStrip";
import LoginPage from "./pages/LoginPage";
import ManagerPage from "./pages/ManagerPage";
import DashboardPage from "./pages/DashboardPage";
import WorkersPage from "./pages/WorkersPage";
import WorkerApp from "./worker/WorkerApp";

/** 근로자 화면 첫 자리. 새 근로자 화면(/w)의 홈이다. */
const WORKER_HOME = "/w/today";

// 위쪽 가로 탭. 사업주 화면 상단 바에서 쓴다(예전 왼쪽 사이드바 메뉴를 대체).
// cn()으로 감싸 eslint-plugin-tailwindcss가 이 상수의 클래스도 검사하게 한다(src/cn.ts).
const tabItem = cn(
  "flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3.5 py-2 text-sm font-semibold transition-colors",
);

function RequireAuth({
  auth,
  role,
  children,
}: {
  auth: AuthState | null;
  role?: Role;
  children: ReactNode;
}) {
  if (!auth) return <Navigate to="/" replace />;
  if (role && auth.role !== role) {
    return <Navigate to={auth.role === "worker" ? WORKER_HOME : "/manager"} replace />;
  }
  return <>{children}</>;
}

function Shell({ auth, onLogout, children }: { auth: AuthState; onLogout: () => void; children: ReactNode }) {
  const navigate = useNavigate();

  function logout() {
    onLogout();
    navigate("/", { replace: true });
  }

  return (
    <div className="min-h-screen bg-paper-50 font-body">
      <header className="sticky top-0 z-30 border-b border-paper-200 bg-paper-100/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3 md:px-8">
          <div className="flex flex-wrap items-center gap-1">
            <NavLink
              to="/manager"
              className={({ isActive }) =>
                cn(tabItem, isActive ? "bg-moss-500 text-white" : "text-ink-700 hover:bg-paper-200")
              }
            >
              <Briefcase size={16} />
              직무 만들기
            </NavLink>
            <NavLink
              to="/dashboard"
              className={({ isActive }) =>
                cn(tabItem, isActive ? "bg-moss-500 text-white" : "text-ink-700 hover:bg-paper-200")
              }
            >
              <BarChart3 size={16} />
              대시보드
            </NavLink>
            <NavLink
              to="/workers"
              className={({ isActive }) =>
                cn(tabItem, isActive ? "bg-moss-500 text-white" : "text-ink-700 hover:bg-paper-200")
              }
            >
              <Users size={16} />
              근로자 관리
            </NavLink>
          </div>

          <div className="flex items-center gap-3">
            <div className="text-right leading-tight">
              <p className="text-xs text-ink-500">현재 역할: 사업주 로그인 중</p>
              <p className="text-sm font-semibold text-ink-900">{auth.displayName || "사업주"}</p>
            </div>
            <button
              onClick={logout}
              className="inline-flex items-center gap-1.5 rounded-lg border border-paper-200 bg-white px-3 py-2 text-sm font-semibold text-ink-700 hover:bg-paper-100"
            >
              <LogOut size={14} />
              로그아웃
            </button>
          </div>
        </div>
      </header>

      {/* 근로자 도움 요청 띠(요청이 있을 때만 보인다, 창업자 결정 6). */}
      <HelpAlertStrip />

      <main className="mx-auto max-w-6xl px-4 py-6 md:px-8 md:py-8">{children}</main>
    </div>
  );
}

function AppRoutes() {
  const [auth, setAuth] = useState<AuthState | null>(() => getAuth());

  function handleLogout() {
    clearAuth();
    setAuth(null);
  }

  const home = auth?.role === "worker" ? WORKER_HOME : "/manager";

  return (
    <Routes>
      {/* 첫 화면: 로그인돼 있으면 각자 홈으로. 아니면 근로자 기기(사업장 코드가 저장된 기기)는 번호 키패드(/w)로,
          그 밖은 로그인 화면으로 간다. */}
      <Route
        path="/"
        element={
          auth ? (
            <Navigate to={home} replace />
          ) : getSavedWorkplaceCode() ? (
            <Navigate to="/w" replace />
          ) : (
            <LoginPage onLogin={setAuth} />
          )
        }
      />
      {/* 늘 로그인 화면을 보이는 주소. 근로자 기기에서 사업주가 로그인할 때, 키패드로 못 넣는 예전 긴 번호
          (5자리 이상)로 들어갈 때 쓴다(/w의 [선생님용: 긴 번호로 들어가기] → /login?tab=worker). */}
      <Route path="/login" element={auth ? <Navigate to={home} replace /> : <LoginPage onLogin={setAuth} />} />
      {/* 새 근로자 화면. 위 띠를 근로자 화면이 직접 그리므로 Shell로 감싸지 않는다. */}
      <Route path="/w/*" element={<WorkerApp auth={auth} onLogin={setAuth} onLogout={handleLogout} />} />
      <Route
        path="/manager"
        element={
          <RequireAuth auth={auth} role="employer">
            {auth && <Shell auth={auth} onLogout={handleLogout}><ManagerPage /></Shell>}
          </RequireAuth>
        }
      />
      <Route
        path="/workers"
        element={
          <RequireAuth auth={auth} role="employer">
            {auth && <Shell auth={auth} onLogout={handleLogout}><WorkersPage /></Shell>}
          </RequireAuth>
        }
      />
      <Route
        path="/dashboard"
        element={
          <RequireAuth auth={auth} role="employer">
            {auth && <Shell auth={auth} onLogout={handleLogout}><DashboardPage /></Shell>}
          </RequireAuth>
        }
      />
      {/* 옛 근로자 화면(/worker, WorkerPage)은 없앴다. 즐겨찾기한 기기도 새 근로자 화면으로 보낸다 — 옛 화면은
          [도움]을 단계 기록(stuck)으로 보내 마지막 단계에서 도움만 눌러도 직무가 '다 함'이 됐다(명세 4.5, 1차 검증). */}
      <Route path="/worker" element={<Navigate to="/w" replace />} />
      <Route path="/admin/tasks" element={<Navigate to="/manager" replace />} />
      <Route path="/admin/dashboard" element={<Navigate to="/dashboard" replace />} />
      <Route path="/worker/*" element={<Navigate to="/w" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
