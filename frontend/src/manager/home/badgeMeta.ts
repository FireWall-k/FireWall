// 배지 → 색(톤)과 걸러보기 묶음. 부품(badge.tsx)과 나눠 둔다(빠른 새로고침 규칙).
import type { Tone } from "../../components/ui";
import type { LiveBadge } from "../api/types";

export const BADGE_TONE: Record<LiveBadge, Tone> = {
  help: "warning",
  help_acked: "info",
  offline: "danger",
  stuck_suspect: "warning",
  in_progress: "info",
  new: "neutral",
  done: "success",
  idle: "neutral",
};

/** '지금 일하는 사람' 카드로 걸러 볼 때 남기는 배지(서버 summary.working과 같은 뜻: 하는 중인 사람). */
export const WORKING_BADGES: ReadonlySet<LiveBadge> = new Set(["in_progress", "stuck_suspect", "offline", "help", "help_acked"]);
