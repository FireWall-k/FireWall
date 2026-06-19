import { useState } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import ManagerPage from "./pages/ManagerPage";
import WorkerPage from "./pages/WorkerPage";
import DashboardPage from "./pages/DashboardPage";
import LoginPage from "./pages/LoginPage";
import { clearAuth, getAuth, type AuthState } from "./api";

const employerTabs = [
  { to: "/", label: "사업주 · 직무 만들기" },
  { to: "/dashboard", label: "사업주 · 대시보드" },
];
const workerTabs = [{ to: "/worker", label: "근로자 · 오늘 할 일" }];

export default function App() {
  const { pathname } = useLocation();
  const [authState, setAuthState] = useState<AuthState | null>(getAuth());

  if (!authState) return <LoginPage onLogin={setAuthState} />;

  const tabs = authState.role === "employer" ? employerTabs : workerTabs;
  const home = authState.role === "employer" ? "/" : "/worker";

  function logout() {
    clearAuth();
    setAuthState(null);
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl items-center gap-4 px-4 py-3">
          <span className="text-lg font-bold text-slate-900">잡카드</span>
          <nav className="flex gap-1" aria-label="메뉴">
            {tabs.map((t) => (
              <Link key={t.to} to={t.to} aria-current={pathname === t.to ? "page" : undefined}
                className={"rounded-md px-3 py-2 text-sm font-medium " +
                  (pathname === t.to ? "bg-blue-700 text-white" : "text-slate-600 hover:bg-slate-100")}>
                {t.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm text-slate-500">
            <span>{authState.displayName}</span>
            <button onClick={logout} className="rounded-md border border-slate-200 px-2 py-1 hover:bg-slate-50">
              로그아웃
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-6">
        <Routes>
          {authState.role === "employer" ? (
            <>
              <Route path="/" element={<ManagerPage />} />
              <Route path="/dashboard" element={<DashboardPage />} />
            </>
          ) : (
            <Route path="/worker" element={<WorkerPage />} />
          )}
          <Route path="*" element={<Navigate to={home} replace />} />
        </Routes>
      </main>
    </div>
  );
}
