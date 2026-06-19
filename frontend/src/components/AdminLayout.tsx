import React from "react";
import { NavLink, Outlet } from "react-router-dom";
import { LayoutGrid, FileText, BarChart3, Tablet } from "lucide-react";

const navItem =
  "flex items-center gap-2.5 rounded-lg px-3.5 py-2.5 text-sm font-medium transition-colors";

export const AdminLayout: React.FC = () => {
  return (
    <div className="min-h-screen bg-paper-50 font-body">
      <div className="flex">
        <aside className="sticky top-0 h-screen w-64 shrink-0 border-r border-paper-200 bg-paper-100/60 px-4 py-6">
          <div className="mb-8 px-2">
            <div className="flex items-center gap-2">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-moss-500 text-paper-50">
                <LayoutGrid size={18} />
              </div>
              <div>
                <p className="font-display text-lg font-semibold leading-tight text-ink-900">설리번</p>
                <p className="text-[11px] font-medium uppercase tracking-wide text-ink-500">JOB CARD</p>
              </div>
            </div>
          </div>

          <nav className="flex flex-col gap-1">
            <NavLink
              to="/admin/tasks"
              className={({ isActive }) =>
                `${navItem} ${isActive ? "bg-moss-500 text-white" : "text-ink-700 hover:bg-paper-200"}`
              }
            >
              <FileText size={17} />
              직무 입력 · 검토
            </NavLink>
            <NavLink
              to="/admin/dashboard"
              className={({ isActive }) =>
                `${navItem} ${isActive ? "bg-moss-500 text-white" : "text-ink-700 hover:bg-paper-200"}`
              }
            >
              <BarChart3 size={17} />
              수행 대시보드
            </NavLink>
          </nav>

          <div className="mt-8 border-t border-paper-200 pt-5">
            <a
              href="/worker"
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-2.5 rounded-lg px-3.5 py-2.5 text-sm font-medium text-clay-600 hover:bg-clay-400/10"
            >
              <Tablet size={17} />
              근로자 화면 미리보기
            </a>
          </div>

          <div className="absolute bottom-6 left-4 right-4 rounded-lg bg-paper-200/60 p-3">
            <p className="text-xs leading-relaxed text-ink-500">
              프론트엔드 단독 데모 · 실제 백엔드 연동 전 목 데이터로 동작합니다.
            </p>
          </div>
        </aside>

        <main className="flex-1 px-8 py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
};
