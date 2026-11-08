// 근로자 화면(/w/*, 명세 3.2). 근로자가 머무는 곳은 홈(/w/today)과 단계 화면 두 곳뿐이다.
//   /w                     번호 넣기(연결 안 된 기기면 '연결 안 됨' 화면)
//   /w/setup               기기 연결(선생님이 함)
//   /w/today               오늘 할 일
//   /w/job/:aid            직무 시작
//   /w/job/:aid/step/:n    단계(주소에 단계 번호 → 새로고침해도 그 자리)
//   /w/job/:aid/done       직무 완료
//   /w/history(/:aid)      했던 일 / 다시 보기
// 쉼 화면(/w/job/:aid/rest)은 묶음 규칙(열린 질문 8)이 정해지면 넣는다.
import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import type { AuthState } from "../api";
import EntryScreen from "./EntryScreen";
import { HistoryDetailScreen, HistoryScreen } from "./HistoryScreen";
import JobDoneScreen from "./JobDoneScreen";
import JobStartScreen from "./JobStartScreen";
import SetupScreen from "./SetupScreen";
import StepRoute from "./StepRoute";
import TodayScreen from "./TodayScreen";
import { WorkerSession } from "./WorkerSession";

export interface WorkerAppProps {
  auth: AuthState | null;
  onLogin: (a: AuthState) => void;
  onLogout: () => void;
}

export default function WorkerApp({ auth, onLogin, onLogout }: WorkerAppProps) {
  const isWorker = auth?.role === "worker";
  // 문서 제목은 화면낭독기가 페이지를 열 때 읽고, 탭·최근 앱 목록에도 보인다. 근로자 화면은 늘 '잡카드'(명세 4.14:
  // 영어 'JOB CARD'는 쓰지 않는다, 3차 검증).
  useEffect(() => {
    document.title = "잡카드";
  }, []);
  // 사업주가 근로자 주소로 오면 사업주 화면으로(근로자 토큰이 아니라 근로자 API가 401이 된다).
  if (auth && !isWorker) return <Navigate to="/manager" replace />;

  return (
    <Routes>
      <Route index element={isWorker ? <Navigate to="/w/today" replace /> : <EntryScreen onLogin={onLogin} />} />
      <Route path="setup" element={<SetupScreen />} />
      <Route
        path="*"
        element={
          isWorker ? (
            // 로그인할 때마다 세션을 새로 만든다(다른 근로자가 같은 기기를 쓸 때 앞사람 상태가 남지 않게).
            <WorkerSession key={auth!.token} token={auth!.token} onLogout={onLogout}>
              <Routes>
                <Route path="today" element={<TodayScreen />} />
                <Route path="job/:aid" element={<JobStartScreen />} />
                <Route path="job/:aid/step/:n" element={<StepRoute />} />
                <Route path="job/:aid/done" element={<JobDoneScreen />} />
                <Route path="history" element={<HistoryScreen />} />
                <Route path="history/:aid" element={<HistoryDetailScreen />} />
                <Route path="*" element={<Navigate to="/w/today" replace />} />
              </Routes>
            </WorkerSession>
          ) : (
            <Navigate to="/w" replace />
          )
        }
      />
    </Routes>
  );
}
