// 근로자 세션 공유 값(WorkerSession이 채운다). 컴포넌트 파일과 나눈 이유: 화면 갱신(react-refresh)은
// 컴포넌트만 내보내는 파일을 요구한다.
import { createContext, useContext, type ReactNode } from "react";
import type { A11yPrefs, Step } from "../api";
import type { JobProgress } from "./resume";
import type { TodayJob, WorkerMe } from "./workerApi";
import { OfflineBanner, SyncNotice } from "./WorkerScreen";

export const TODAY_POLL_MS = 30_000;
export const OUTBOX_RETRY_MS = 30_000;
export const SYNC_NOTICE_MS = 3_000;


export interface StepCompletion {
  durationSec: number;
  replayCount: number;
  /** '어려움 신호'(다시 듣기 과다·시간 초과). 도움 요청은 따로 보낸다. */
  stuck: boolean;
}

export interface WorkerSessionValue {
  me: WorkerMe;
  prefs: A11yPrefs;
  jobs: TodayJob[];
  online: boolean;
  /** '기록을 다 보냈어요'를 잠깐 보이는 중. */
  synced: boolean;
  pendingCount: number;
  refresh: () => Promise<void>;
  progressOf: (job: TodayJob) => JobProgress;
  completeStep: (job: TodayJob, step: Step, info: StepCompletion) => void;
  onMediaError: (url: string | null | undefined) => void;
  /** 끝내기(로그아웃): 로그인 상태를 지우고 번호 넣기 화면으로. 사업장 코드는 남긴다. */
  logout: () => void;
  /** 화면에서 받은 오류를 알린다(401이면 다시 들어오기 화면, 네트워크면 오프라인 표시). */
  reportError: (e: unknown) => void;
}

export const SessionContext = createContext<WorkerSessionValue | null>(null);

export function useWorkerSession(): WorkerSessionValue {
  const v = useContext(SessionContext);
  if (!v) throw new Error("WorkerSession 밖에서 불렀습니다");
  return v;
}

/** 지금 띠 하나(도움 > 오프라인 > 기록 보냄). 도움 띠가 있으면 오프라인은 위 띠 가운데 표시(offlineMark)로. */
export function useBand(help?: ReactNode): { band: ReactNode; offlineMark: boolean } {
  const { online, synced } = useWorkerSession();
  if (help) return { band: help, offlineMark: !online };
  if (!online) return { band: <OfflineBanner />, offlineMark: false };
  if (synced) return { band: <SyncNotice />, offlineMark: false };
  return { band: null, offlineMark: false };
}

