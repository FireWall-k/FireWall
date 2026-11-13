import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useEffect, useState, type ReactNode } from "react";
import { clearAuth, getAuth, type AuthState, type Role } from "./api";
import { getSavedWorkplaceCode } from "./workerCodes";
import LoginPage from "./pages/LoginPage";
import ManagerRoutes from "./manager/routes";
import WorkerApp from "./worker/WorkerApp";

/** 근로자 화면 첫 자리. 새 근로자 화면(/worker)의 홈이다. */
const WORKER_HOME = "/worker/today";
/** 사업주 화면 첫 자리(2c 전까지는 옛 대시보드, contract §2.2). */
const EMPLOYER_HOME = "/manager";

function RequireAuth({
  auth,
  role,
  children,
}: {
  auth: AuthState | null;
  role?: Role;
  children: ReactNode;
}) {
  if (!auth) return <Navigate to={role === "employer" ? "/manager/login" : "/"} replace />;
  if (role && auth.role !== role) {
    return <Navigate to={auth.role === "worker" ? WORKER_HOME : EMPLOYER_HOME} replace />;
  }
  return <>{children}</>;
}

/** 옛 주소 → 새 주소(contract §2.2). 즐겨찾기·북마크의 ?쿼리와 #은 그대로 넘긴다. replace라 뒤로 가기에 옛 주소가 남지 않는다. */
function LegacyRedirect({ to }: { to: string }) {
  const { search, hash } = useLocation();
  return <Navigate to={`${to}${search}${hash}`} replace />;
}

/** 앞부분만 바뀐 주소 → 새 주소. '/w/job/1/step/2?x#y' → '/worker/job/1/step/2?x#y'. */
function PrefixRedirect({ from, to }: { from: string; to: string }) {
  const { pathname, search, hash } = useLocation();
  const rest = pathname.startsWith(from) ? pathname.slice(from.length) : "";
  return <Navigate to={`${to}${rest}${search}${hash}`} replace />;
}

function AppRoutes() {
  const [auth, setAuth] = useState<AuthState | null>(() => getAuth());

  function handleLogout() {
    clearAuth();
    setAuth(null);
  }

  // 다른 탭(또는 홈 화면 앱)에서 로그인이 바뀌면 이 탭도 따른다(3차 검증). 저장된 로그인은 기기에 하나라, 따르지
  // 않으면 이 탭은 앞사람 화면을 그린 채 뒷사람 토큰으로 기록을 보냈다.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== null && !e.key.startsWith("jobcard_token") && !e.key.startsWith("jobcard_role")) return;
      setAuth((cur) => {
        const next = getAuth();
        if (cur?.token === next?.token && cur?.role === next?.role) return cur;
        return next;
      });
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const home = auth?.role === "worker" ? WORKER_HOME : EMPLOYER_HOME;

  return (
    <Routes>
      {/* 첫 화면: 로그인돼 있으면 각자 홈으로. 아니면 근로자 기기(사업장 코드가 저장된 기기)는 번호 키패드(/worker)로,
          그 밖은 로그인 화면으로 간다. */}
      <Route
        path="/"
        element={
          auth ? (
            <Navigate to={home} replace />
          ) : getSavedWorkplaceCode() ? (
            <Navigate to="/worker" replace />
          ) : (
            <LoginPage onLogin={setAuth} />
          )
        }
      />
      {/* 늘 로그인 화면을 보이는 주소. 근로자 기기에서 사업주가 로그인할 때, 키패드로 못 넣는 예전 긴 번호
          (5자리 이상)로 들어갈 때 쓴다(/worker의 [선생님용: 긴 번호로 들어가기] → /login?tab=worker). */}
      <Route path="/login" element={auth ? <Navigate to={home} replace /> : <LoginPage onLogin={setAuth} />} />
      {/* 새 근로자 화면. 위 띠를 근로자 화면이 직접 그리므로 Shell로 감싸지 않는다. */}
      <Route path="/worker/*" element={<WorkerApp auth={auth} onLogin={setAuth} onLogout={handleLogout} />} />
      {/* 새 사업주 로그인(명세 5.1). 로그인하면 사업주 홈으로 간다. */}
      <Route path="/manager/login" element={auth ? <Navigate to={home} replace /> : <LoginPage onLogin={setAuth} />} />
      {/* 사업주 화면 전체. 주소는 manager/routes.tsx에만 더한다(contract §2.2). */}
      <Route
        path="/manager/*"
        element={
          <RequireAuth auth={auth} role="employer">
            {auth && <ManagerRoutes displayName={auth.displayName} onLogout={handleLogout} />}
          </RequireAuth>
        }
      />
      {/* 짧은 옛 주소(/w, /m — 2026-11-13에 /worker, /manager로 바꿈)는 뒤 주소·?쿼리·#을 그대로 붙여 새 주소로 넘긴다.
          이미 인쇄한 근로자 QR(/w?site=…)과 즐겨찾기, 예전 알림(/m#help)이 계속 열린다. */}
      <Route path="/w/*" element={<PrefixRedirect from="/w" to="/worker" />} />
      <Route path="/m/*" element={<PrefixRedirect from="/m" to="/manager" />} />
      {/* 더 옛 사업주 주소도 새 주소로 넘긴다(2a-1). */}
      <Route path="/dashboard" element={<LegacyRedirect to="/manager" />} />
      <Route path="/workers" element={<LegacyRedirect to="/manager/workers" />} />
      <Route path="/admin/tasks" element={<LegacyRedirect to="/manager/tasks/new" />} />
      <Route path="/admin/dashboard" element={<LegacyRedirect to="/manager" />} />
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
