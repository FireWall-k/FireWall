// 근로자 화면(/worker/*, 명세 3.2). 근로자가 머무는 곳은 홈(/worker/today)과 단계 화면 두 곳뿐이다.
//   /worker                     번호 넣기(연결 안 된 기기면 '연결 안 됨' 화면)
//   /worker/setup               기기 연결(사업주가 함)
//   /worker/today               오늘 할 일
//   /worker/job/:aid            직무 시작
//   /worker/job/:aid/step/:n    단계(주소에 단계 번호 → 새로고침해도 그 자리)
//   /worker/job/:aid/done       직무 완료
//   /worker/history(/:aid)      했던 일 / 다시 보기
// 쉼 화면(/worker/job/:aid/rest)은 묶음 규칙(열린 질문 8)이 정해지면 넣는다.
import { useEffect, useState, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import type { AuthState } from "../api";
import EntryScreen from "./EntryScreen";
import { HistoryDetailScreen, HistoryScreen } from "./HistoryScreen";
import JobDoneScreen from "./JobDoneScreen";
import JobStartScreen from "./JobStartScreen";
import SetupScreen from "./SetupScreen";
import StepRoute from "./StepRoute";
import TodayScreen from "./TodayScreen";
import { WorkerSession } from "./WorkerSession";
import { useWorkerSession } from "./session";
import { applySiteCode, saveTeacherTitle } from "../workerCodes";

/**
 * (2d) 로그인한 근로자의 호칭(/me teacher_title)을 기기에 저장한다. 아래 화면이 그리기 전에(같은 그리기 안에서)
 * 저장해야 첫 화면부터 새 호칭이 나온다. 같은 값이면 쓰지 않는다(saveTeacherTitle).
 */
function TeacherTitleSync({ children }: { children: ReactNode }) {
  const { me } = useWorkerSession();
  saveTeacherTitle(me.teacher_title);
  return <>{children}</>;
}

export interface WorkerAppProps {
  auth: AuthState | null;
  onLogin: (a: AuthState) => void;
  onLogout: () => void;
}

export default function WorkerApp({ auth, onLogin, onLogout }: WorkerAppProps) {
  const isWorker = auth?.role === "worker";
  const location = useLocation();
  const navigate = useNavigate();
  // (2d) 기기 연결 주소 /worker?site=CODE: 첫 그리기 전에 사업장 코드를 저장한다(번호 넣기 화면이 그 값을 바로 읽게).
  // 저장된 코드와 다르면 예전 가게 이름·호칭을 지운다(applySiteCode). 그 뒤 주소에서 site를 뺀다(replace).
  const [siteParam] = useState(() => {
    const site = new URLSearchParams(location.search).get("site");
    if (site !== null) applySiteCode(site);
    return site;
  });
  useEffect(() => {
    if (siteParam === null) return;
    const params = new URLSearchParams(location.search);
    if (!params.has("site")) return;
    params.delete("site");
    const q = params.toString();
    navigate({ pathname: location.pathname, search: q ? `?${q}` : "", hash: location.hash }, { replace: true });
    // 처음 한 번만(주소 정리).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // 문서 제목은 화면낭독기가 페이지를 열 때 읽고, 탭·최근 앱 목록에도 보인다. 근로자 화면은 늘 '잡카드'(명세 4.14:
  // 영어 'JOB CARD'는 쓰지 않는다, 3차 검증).
  useEffect(() => {
    document.title = "잡카드";
  }, []);
  // 사업주가 근로자 주소로 오면 사업주 화면으로(근로자 토큰이 아니라 근로자 API가 401이 된다).
  if (auth && !isWorker) return <Navigate to="/manager" replace />;

  return (
    <Routes>
      <Route index element={isWorker ? <Navigate to="/worker/today" replace /> : <EntryScreen onLogin={onLogin} />} />
      <Route path="setup" element={<SetupScreen />} />
      <Route
        path="*"
        element={
          isWorker ? (
            // 로그인할 때마다 세션을 새로 만든다(다른 근로자가 같은 기기를 쓸 때 앞사람 상태가 남지 않게).
            <WorkerSession key={auth!.token} token={auth!.token} onLogout={onLogout}>
              <TeacherTitleSync>
              <Routes>
                <Route path="today" element={<TodayScreen />} />
                <Route path="job/:aid" element={<JobStartScreen />} />
                <Route path="job/:aid/step/:n" element={<StepRoute />} />
                <Route path="job/:aid/done" element={<JobDoneScreen />} />
                <Route path="history" element={<HistoryScreen />} />
                <Route path="history/:aid" element={<HistoryDetailScreen />} />
                <Route path="*" element={<Navigate to="/worker/today" replace />} />
              </Routes>
              </TeacherTitleSync>
            </WorkerSession>
          ) : (
            <Navigate to="/worker" replace />
          )
        }
      />
    </Routes>
  );
}
