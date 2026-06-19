import React from "react";
import type { TaskStatus } from "../types";

const config: Record<TaskStatus, { label: string; cls: string }> = {
  draft: { label: "분해 완료 · 검토 전", cls: "bg-paper-200 text-ink-700" },
  under_review: { label: "검토 중", cls: "bg-signal-amber/20 text-clay-600" },
  published: { label: "게시됨", cls: "bg-moss-500/15 text-moss-600" },
  archived: { label: "보관됨", cls: "bg-ink-500/10 text-ink-500" },
};

export const StatusBadge: React.FC<{ status: TaskStatus }> = ({ status }) => {
  const c = config[status];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${c.cls}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {c.label}
    </span>
  );
};
