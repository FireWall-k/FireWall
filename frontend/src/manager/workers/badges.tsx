// 근로자 표의 작은 부품: 오늘 상태 배지, 동의 배지, 최근 7일 작은 막대.
import { Hand, Footprints } from "lucide-react";
import { Badge, type Tone } from "../../components/ui";
import { consentState, todayBadge, workerList } from "../copy";
import type { ConsentState, TodayBadge } from "../api/workerTypes";

const TODAY_TONE: Record<TodayBadge, Tone> = {
  help: "danger",
  help_coming: "warning",
  done: "success",
  in_progress: "info",
  not_started: "neutral",
  none: "neutral",
};

const iconProps = { size: 14, strokeWidth: 2, "aria-hidden": true as const, className: "shrink-0" };

/** 색 + 아이콘 + 글(명세 8.2). '도움 가는 중'은 확인했지만 아직 끝나지 않은 도움. */
export function TodayBadgeView({ value }: { value: TodayBadge }) {
  const icon = value === "help" ? <Hand {...iconProps} /> : value === "help_coming" ? <Footprints {...iconProps} /> : undefined;
  return (
    <Badge tone={TODAY_TONE[value]} icon={value === "none" || value === "not_started" ? false : icon}>
      {todayBadge[value]}
    </Badge>
  );
}

export function ConsentBadge({ value }: { value: ConsentState }) {
  return <Badge tone={value === "complete" ? "success" : "warning"}>{consentState[value]}</Badge>;
}

/** 최근 7일 완료: 막대 7개(꾸밈) + 합계 숫자. 뜻은 숫자와 이름(aria-label)이 전한다. */
export function Done7({ values }: { values: number[] }) {
  const total = values.reduce((a, b) => a + b, 0);
  const max = Math.max(1, ...values);
  return (
    <span className="inline-flex items-end gap-2 whitespace-nowrap" aria-label={workerList.done7Label(total)} role="img">
      <span aria-hidden="true" className="flex h-5 items-end gap-0.5">
        {values.map((v, i) => (
          <span
            key={i}
            className={v > 0 ? "w-1.5 rounded-t-sm bg-moss-600" : "w-1.5 rounded-t-sm bg-paper-200"}
            style={{ height: `${v > 0 ? Math.max(25, (v / max) * 100) : 15}%` }}
          />
        ))}
      </span>
      <span aria-hidden="true" className="text-ui-sm tabular-nums text-ink-700">
        {workerList.times(total)}
      </span>
    </span>
  );
}
