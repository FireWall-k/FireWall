import { BrowserRouter, Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { Briefcase, BarChart3, LogOut, Users } from "lucide-react";
import { useState, type ReactNode } from "react";
import { clearAuth, getAuth, type AuthState, type Role } from "./api";
import LoginPage from "./pages/LoginPage";
import ManagerPage from "./pages/ManagerPage";
import DashboardPage from "./pages/DashboardPage";
import WorkersPage from "./pages/WorkersPage";
import WorkerPage from "./pages/WorkerPage";

// 위쪽 가로 탭. 사업주 화면 상단 바에서 쓴다(예전 왼쪽 사이드바 메뉴를 대체).
const tabItem =
  "flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3.5 py-2 text-sm font-semibold transition-colors";

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
    return <Navigate to={auth.role === "worker" ? "/worker" : "/manager"} replace />;
  }
  return <>{children}</>;
}

function Shell({ auth, onLogout, children }: { auth: AuthState; onLogout: () => void; children: ReactNode }) {
  const navigate = useNavigate();

  function logout() {
    onLogout();
    navigate("/", { replace: true });
  }

  if (auth.role === "worker") {
    return (
      <div className="min-h-screen bg-worker-bg px-4 py-5 font-worker text-worker-ink">
        <header className="mx-auto mb-5 flex max-w-3xl items-center justify-between rounded-2xl border border-paper-200 bg-white px-4 py-3 shadow-sm">
          <div>
            <p className="text-xs font-bold uppercase tracking-wide text-moss-600">JOB CARD</p>
            <h1 className="text-lg font-bold">{auth.displayName || "근로자"}님의 오늘 할 일</h1>
          </div>
          <button
            onClick={logout}
            className="rounded-xl border border-paper-200 px-3 py-2 text-sm font-semibold text-ink-700 hover:bg-paper-100"
          >
            로그아웃
          </button>
        </header>
        <main className="mx-auto max-w-3xl">{children}</main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-paper-50 font-body">
      <header className="sticky top-0 z-30 border-b border-paper-200 bg-paper-100/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3 md:px-8">
          <div className="flex flex-wrap items-center gap-1">
            {/* 2번째(원래 순서 기준 대시보드)를 맨 앞에 둔다 */}
            <NavLink
              to="/dashboard"
              className={({ isActive }) =>
                `${tabItem} ${isActive ? "bg-moss-500 text-white" : "text-ink-700 hover:bg-paper-200"}`
              }
            >
              <BarChart3 size={16} />
              사업주 · 대시보드
            </NavLink>
            <NavLink
              to="/manager"
              className={({ isActive }) =>
                `${tabItem} ${isActive ? "bg-moss-500 text-white" : "text-ink-700 hover:bg-paper-200"}`
              }
            >
              <Briefcase size={16} />
              사업주 · 직무 만들기
            </NavLink>
            <NavLink
              to="/workers"
              className={({ isActive }) =>
                `${tabItem} ${isActive ? "bg-moss-500 text-white" : "text-ink-700 hover:bg-paper-200"}`
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

  return (
    <Routes>
      <Route
        path="/"
        element={
          auth ? (
            <Navigate to={auth.role === "worker" ? "/worker" : "/manager"} replace />
          ) : (
            <LoginPage onLogin={setAuth} />
          )
        }
      />
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
      <Route
        path="/worker"
        element={
          <RequireAuth auth={auth} role="worker">
            {auth && <Shell auth={auth} onLogout={handleLogout}><WorkerPage /></Shell>}
          </RequireAuth>
        }
      />
      <Route path="/admin/tasks" element={<Navigate to="/manager" replace />} />
      <Route path="/admin/dashboard" element={<Navigate to="/dashboard" replace />} />
      <Route path="/worker/:taskId" element={<Navigate to="/worker" replace />} />
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
