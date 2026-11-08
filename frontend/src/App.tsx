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
import WorkerPage from "./pages/WorkerPage";
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

  if (auth.role === "worker") {
    return (
      // 낱말 단위 줄바꿈(keep-all + overflow-wrap:anywhere)은 이제 index.css 전역 규칙이다(0차 1번).
      // 위아래 여백(py-3)·머리글 여백을 줄여 단계 화면의 그림 자리를 늘렸다. 아래 여백 0.75rem은
      // WorkerPage의 useFillViewport가 쓰는 값과 같아야 한다.
      // 이 옛 근로자 틀(/worker)은 새 근로자 화면(/w, worker/WorkerApp)으로 옮기는 동안만 남겨 둔다.
      <div className="min-h-dvh bg-worker-bg px-4 py-3 font-worker text-worker-ink">
        {/* 휴대폰(sm 미만)에서는 머리글을 한 줄로 둔다: 눈썹 글씨(잡카드)를 숨기고, 아주 좁은 화면(400px 미만)
            에서는 "님의 오늘 할 일"을 화면에서만 감춘다(화면 읽기 프로그램은 그대로 읽는다). 360px 폭에서
            "김민수님의 오늘 / 할 일"로 두 줄이 되던 것. 로그아웃 버튼은 그대로 둔다. */}
        <header className="mx-auto mb-3 flex max-w-3xl items-center justify-between gap-3 rounded-2xl border border-paper-200 bg-white px-4 py-2 shadow-sm wide:max-w-5xl">
          <div className="min-w-0">
            {/* 근로자 화면에는 영어를 쓰지 않는다(명세 4.14). 예전 'JOB CARD'. */}
            <p className="text-xs font-bold tracking-wide text-moss-600 max-sm:hidden">잡카드</p>
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
