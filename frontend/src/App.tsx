import { BrowserRouter, Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { Briefcase, BarChart3, LogOut, Users } from "lucide-react";
import { useState, type ReactNode } from "react";
import { clearAuth, getAuth, type AuthState, type Role } from "./api";
import { cn } from "./cn";
import LoginPage from "./pages/LoginPage";
import ManagerPage from "./pages/ManagerPage";
import DashboardPage from "./pages/DashboardPage";
import WorkersPage from "./pages/WorkersPage";
import WorkerPage from "./pages/WorkerPage";

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
      // break-keep: 한국어를 낱말 단위로 줄바꿈한다("접 / 으세요"처럼 낱말 중간에서 끊기면 읽기 어려운 근로자가
      // 다른 낱말로 읽는다). 아주 긴 낱말(코드·영문)이 화면을 넘지 않게 overflow-wrap:anywhere를 함께 둔다.
      // 둘 다 상속되므로 근로자 화면 전체(머리글·문장·버튼)에 적용된다.
      // 위아래 여백(py-3)·머리글 여백을 줄여 단계 화면의 그림 자리를 늘렸다. 아래 여백 0.75rem은
      // WorkerPage의 useFillViewport가 쓰는 값과 같아야 한다.
      <div className="min-h-dvh break-keep bg-worker-bg px-4 py-3 font-worker text-worker-ink [overflow-wrap:anywhere]">
        {/* 휴대폰(sm 미만)에서는 머리글을 한 줄로 둔다: 영문 눈썹 글씨(JOB CARD)를 숨기고, 아주 좁은 화면(400px 미만)
            에서는 "님의 오늘 할 일"을 화면에서만 감춘다(화면 읽기 프로그램은 그대로 읽는다). 360px 폭에서
            "김민수님의 오늘 / 할 일"로 두 줄이 되던 것. 로그아웃 버튼은 그대로 둔다. */}
        <header className="mx-auto mb-3 flex max-w-3xl items-center justify-between gap-3 rounded-2xl border border-paper-200 bg-white px-4 py-2 shadow-sm wide:max-w-5xl">
          <div className="min-w-0">
            <p className="text-xs font-bold uppercase tracking-wide text-moss-600 max-sm:hidden">JOB CARD</p>
            <h1 className="text-pretty text-lg font-bold">
              {auth.displayName || "근로자"}님<span className="max-[400px]:sr-only">의 오늘 할 일</span>
            </h1>
          </div>
          {/* 근로자 화면의 모든 버튼은 80px 터치 영역(min-h-touch)을 지킨다. 예전에는 이 버튼만 38px이라
              작업 버튼보다 훨씬 작았고, e2e도 <main> 안만 재서 놓쳤다(Phase 0.4 보완). */}
          <button
            onClick={logout}
            className="min-h-touch shrink-0 rounded-xl border border-paper-200 px-4 text-worker font-semibold text-ink-700 hover:bg-paper-100"
          >
            로그아웃
          </button>
        </header>
        <main className="mx-auto max-w-3xl wide:max-w-5xl">{children}</main>
      </div>
    );
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
              사업주 · 직무 만들기
            </NavLink>
            <NavLink
              to="/dashboard"
              className={({ isActive }) =>
                cn(tabItem, isActive ? "bg-moss-500 text-white" : "text-ink-700 hover:bg-paper-200")
              }
            >
              <BarChart3 size={16} />
              사업주 · 대시보드
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
