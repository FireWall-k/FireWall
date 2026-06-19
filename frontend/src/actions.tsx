import type { ReactNode } from "react";

// 동작(action_type)을 색·아이콘·라벨로 시각화한다(기능 4).
// 같은 객체 그림(예: 상자)이라도 동작이 다르면 칩으로 구분돼 인지부하를 낮춘다.
// 결정론적(네트워크 의존 없음)이라 폴백 상징에도 항상 적용된다.
//
// 주의(Tailwind): 색 클래스는 반드시 '리터럴 문자열'로 둔다. `bg-${x}-100`처럼
// 동적으로 만들면 Tailwind가 스캔하지 못해 빌드에서 누락된다.

type ActionMeta = { label: string; chip: string; icon: ReactNode };

function svg(children: ReactNode): ReactNode {
  return (
    <svg
      viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round"
      className="h-[1.15em] w-[1.15em] shrink-0" aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const ACTION_META: Record<string, ActionMeta> = {
  observe: {
    label: "확인하기",
    chip: "bg-blue-100 text-blue-800",
    icon: svg(<><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" /></>),
  },
  move: {
    label: "옮기기",
    chip: "bg-green-100 text-green-800",
    icon: svg(<><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>),
  },
  stack: {
    label: "쌓기",
    chip: "bg-purple-100 text-purple-800",
    icon: svg(<><path d="m12 2 9 5-9 5-9-5 9-5Z" /><path d="m3 12 9 5 9-5" /><path d="m3 17 9 5 9-5" /></>),
  },
  sort: {
    label: "분류하기",
    chip: "bg-orange-100 text-orange-800",
    icon: svg(<><path d="M11 5h10" /><path d="M11 9h7" /><path d="M11 13h4" /><path d="m3 8 3-3 3 3" /><path d="M6 5v14" /></>),
  },
  pack: {
    label: "담기",
    chip: "bg-teal-100 text-teal-800",
    icon: svg(<><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z" /><path d="m3.3 7 8.7 5 8.7-5" /><path d="M12 22V12" /></>),
  },
  clean: {
    label: "청소하기",
    chip: "bg-cyan-100 text-cyan-800",
    icon: svg(<><path d="M9 4v4" /><path d="M7 6h4" /><path d="M15 10l1.6 3.4L20 15l-3.4 1.6L15 20l-1.6-3.4L10 15l3.4-1.6Z" /></>),
  },
  other: {
    label: "작업하기",
    chip: "bg-slate-100 text-slate-700",
    icon: svg(<><circle cx="12" cy="12" r="9" /><path d="M12 8v4l2 2" /></>),
  },
};

export function metaFor(action: string): ActionMeta {
  return ACTION_META[action] ?? ACTION_META.other;
}

export function ActionChip({ action, className = "" }: { action: string; className?: string }) {
  const m = metaFor(action);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 font-semibold ${m.chip} ${className}`}
      data-action={action}
    >
      {m.icon}
      {m.label}
    </span>
  );
}
