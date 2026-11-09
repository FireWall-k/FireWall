// 이니셜 아바타(명세 5.2·5.3). 받은 사람 목록은 3개까지 보이고 나머지는 '+n'.
import { cn } from "../../cn";

export interface AvatarProps {
  initials: string;
  /** 화면 읽기 프로그램이 읽을 이름('김민지 님'). 없으면 꾸밈으로 숨긴다. */
  label?: string;
  size?: "sm" | "md";
  className?: string;
}

export function Avatar({ initials, label, size = "md", className }: AvatarProps) {
  return (
    <span
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      title={label}
      className={cn(
        "inline-flex shrink-0 select-none items-center justify-center rounded-full border-2 border-white bg-paper-100 font-semibold text-ink-700",
        size === "sm" ? "size-7 text-ui-xs" : "size-9 text-ui-sm",
        className,
      )}
    >
      {initials.slice(0, 2)}
    </span>
  );
}

export interface AvatarGroupProps {
  people: { id: string; initials: string; label?: string }[];
  /** 보이는 사람 밖에 더 있는 수(서버 recipients_more). */
  more?: number;
  max?: number;
  /** 묶음 전체를 읽을 문장('받은 사람 5명'). */
  label?: string;
}

export function AvatarGroup({ people, more = 0, max = 3, label }: AvatarGroupProps) {
  const shown = people.slice(0, max);
  const rest = more + Math.max(0, people.length - shown.length);
  return (
    <span role={label ? "group" : undefined} aria-label={label} className="inline-flex items-center">
      <span className="flex -space-x-2">
        {shown.map((p) => (
          <Avatar key={p.id} initials={p.initials} label={label ? undefined : p.label} size="sm" />
        ))}
      </span>
      {rest > 0 && <span className="ml-1.5 text-ui-xs font-semibold tabular-nums text-ink-700">+{rest}</span>}
    </span>
  );
}
