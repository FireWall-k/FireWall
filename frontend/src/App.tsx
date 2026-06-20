import { BrowserRouter, Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { Briefcase, BarChart3, LogOut, Tablet, UserRound } from "lucide-react";
import { useState, type ReactNode } from "react";
import { clearAuth, getAuth, type AuthState, type Role } from "./api";
import LoginPage from "./pages/LoginPage";
import ManagerPage from "./pages/ManagerPage";
import DashboardPage from "./pages/DashboardPage";
import WorkerPage from "./pages/WorkerPage";

const navItem =
  "flex items-center gap-2 rounded-xl px-3.5 py-2.5 text-sm font-semibold transition-colors";

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
      <div className="flex min-h-screen">
        <aside className="sticky top-0 hidden h-screen w-64 shrink-0 border-r border-paper-200 bg-paper-100/70 px-4 py-6 md:block">
          <div className="mb-8 px-2">
            <div className="flex items-center gap-2">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-moss-500 text-white">
                <Briefcase size={18} />
              </div>
              <div>
                <p className="font-display text-lg font-semibold leading-tight text-ink-900">설리번</p>
                <p className="text-[11px] font-bold uppercase tracking-wide text-ink-500">JOB CARD</p>
              </div>
            </div>
          </div>

          <nav className="flex flex-col gap-1">
            <NavLink
              to="/manager"
              className={({ isActive }) =>
                `${navItem} ${isActive ? "bg-moss-500 text-white" : "text-ink-700 hover:bg-paper-200"}`
              }
            >
              <Briefcase size={17} />
              직무 입력 · 검토
            </NavLink>
            <NavLink
              to="/dashboard"
              className={({ isActive }) =>
                `${navItem} ${isActive ? "bg-moss-500 text-white" : "text-ink-700 hover:bg-paper-200"}`
              }
            >
              <BarChart3 size={17} />
              수행 대시보드
            </NavLink>
          </nav>

          <div className="mt-8 border-t border-paper-200 pt-5">
            <button
              onClick={logout}
              className="flex w-full items-center gap-2.5 rounded-xl px-3.5 py-2.5 text-left text-sm font-semibold text-clay-600 hover:bg-clay-400/10"
            >
              <Tablet size={17} />
              근로자 로그인으로 전환
            </button>
          </div>

          <div className="absolute bottom-6 left-4 right-4 rounded-xl bg-white/80 p-3 shadow-sm">
            <div className="flex items-center gap-2 text-sm font-semibold text-ink-900">
              <UserRound size={16} />
              {auth.displayName || "사업주"}
            </div>
            <button onClick={logout} className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-ink-500 hover:text-ink-900">
              <LogOut size={13} />
              로그아웃
            </button>
          </div>
        </aside>

        <main className="flex-1 px-4 py-6 md:px-8 md:py-8">
          <div className="mb-5 flex items-center justify-between md:hidden">
            <div>
              <p className="text-xs font-bold uppercase tracking-wide text-moss-600">JOB CARD</p>
              <h1 className="text-lg font-bold text-ink-900">설리번</h1>
            </div>
            <button onClick={logout} className="rounded-lg border border-paper-200 bg-white px-3 py-2 text-sm font-semibold text-ink-700">
              로그아웃
            </button>
          </div>
          {children}
        </main>
      </div>
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
