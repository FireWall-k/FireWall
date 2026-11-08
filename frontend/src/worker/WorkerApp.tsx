// 임시 자리(FOUNDATION 트랙이 App.tsx 연결용으로 만든 빈 껍데기). WORKER 트랙이 /w 화면 전체로 덮어쓴다.
// 그 전까지는 옛 근로자 화면으로 보낸다: 로그인돼 있으면 /worker, 아니면 늘 로그인 화면을 보이는 /login(근로자 탭).
// ('/'로 보내면 사업장 코드가 저장된 기기에서 다시 /w로 와 끝없이 돈다.)
import { Navigate } from "react-router-dom";
import type { AuthState } from "../api";

export interface WorkerAppProps {
  auth: AuthState | null;
  onLogin: (a: AuthState) => void;
  onLogout: () => void;
}

export default function WorkerApp({ auth }: WorkerAppProps) {
  if (auth?.role === "worker") return <Navigate to="/worker" replace />;
  return <Navigate to="/login?tab=worker" replace />;
}
