// 근로자 상태 배지(서버 판정 값 → 색·아이콘·글). 색만으로 뜻을 전하지 않도록 아이콘과 글을 늘 함께 보인다.
import { CircleAlert, CircleCheck, CircleDashed, Hand, HandHelping, Minus, Play, WifiOff } from "lucide-react";
import { Badge } from "../../components/ui";
import type { LiveBadge } from "../api/types";
import { liveBadge } from "../copy";
import { BADGE_TONE } from "./badgeMeta";

const ICON_P = { size: 14, strokeWidth: 2, "aria-hidden": true as const, className: "shrink-0" };


function BadgeIcon({ badge }: { badge: LiveBadge }) {
  switch (badge) {
    case "help":
      return <Hand {...ICON_P} />;
    case "help_acked":
      return <HandHelping {...ICON_P} />;
    case "offline":
      return <WifiOff {...ICON_P} />;
    case "stuck_suspect":
      return <CircleAlert {...ICON_P} />;
    case "in_progress":
      return <Play {...ICON_P} />;
    case "new":
      return <CircleDashed {...ICON_P} />;
    case "done":
      return <CircleCheck {...ICON_P} />;
    default:
      return <Minus {...ICON_P} />;
  }
}

export function LiveStatusBadge({ badge }: { badge: LiveBadge }) {
  return (
    <span data-badge-kind={badge}>
      <Badge tone={BADGE_TONE[badge]} icon={<BadgeIcon badge={badge} />}>
        {liveBadge[badge]}
      </Badge>
    </span>
  );
}
