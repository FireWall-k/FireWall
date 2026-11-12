// 오늘 현황 하나를 홈·도움 띠·상단 바 종이 같이 쓴다(contract §5.2, tasks §6 FOUNDATION).
// AppShell의 LiveProvider가 GET /api/employer/live 폴링을 한 번만 돌리고, 나머지는 useLive로 읽는다.
// - 5초마다 부른다. 숨은 탭에서는 멈추고, 다시 보이면 바로 한 번 부른다.
// - 늦게 온 응답(앞서 보낸 요청의 응답이 뒤에 도착)은 버린다.
// - 실패하면 화면을 그대로 두고 disconnected=true(토스트 없음, 제목 줄에 '연결이 잠시 끊겼어요'). 다음 차례에 다시 부른다.
// - 429(너무 자주)는 끊김으로 보지 않고 다음 주기에 다시 부른다.
// - [확인했어요]·[도와줬어요]를 누르면 화면에 먼저 반영한다. 서버는 4초 동안 같은 답을 주므로, 누른 결과를
//   잠깐(LOCAL_HELP_MS) 서버 답 위에 덮어 둔다 — 닫은 요청이 다음 폴링에 다시 나타나지 않게.
import { createContext, useContext } from "react";
import type { EmployerHelp } from "../../api";
import type { LiveOut } from "../api/types";

export const LIVE_POLL_MS = 5_000;
export const LOCAL_HELP_MS = 12_000;

export type LocalHelpAction = "acknowledged" | "resolved";

export interface LiveFeed {
  /** 마지막으로 받은 현황(아직 못 받았으면 null). help는 화면에서 누른 결과를 덮은 목록이다. */
  data: LiveOut | null;
  /** 도움 요청 목록(열림 + 확인함). data가 없으면 빈 목록. */
  help: EmployerHelp[];
  /** 마지막으로 받은 시각(기기 시계, ms). */
  updatedAt: number | null;
  /** 마지막 불러오기가 실패했다(429 제외). */
  disconnected: boolean;
  /** 마지막 응답의 서버 시각(ms, 없으면 0). '1분 전'을 서버 시계로 잰다. */
  now: number;
  /** 지금 바로 다시 부른다. */
  reload: () => Promise<void>;
  /** 도움 요청 하나를 화면에 먼저 반영한다(확인함 / 닫음). */
  markHelp: (id: string, action: LocalHelpAction) => void;
}

export const LiveContext = createContext<LiveFeed | null>(null);

const EMPTY: LiveFeed = {
  data: null,
  help: [],
  updatedAt: null,
  disconnected: false,
  now: 0,
  reload: async () => {},
  markHelp: () => {},
};

/** LiveProvider 안에서만 값이 있다. 밖이면(단독 시험) 빈 현황 — 따로 폴링하지 않는다(같은 주소를 두 번 부르지 않음). */
export function useLive(): LiveFeed {
  return useContext(LiveContext) ?? EMPTY;
}

/** 'HH:MM:SS'(기기 현지 시각, tabular-nums로 보인다). */
export function clockText(ms: number): string {
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
