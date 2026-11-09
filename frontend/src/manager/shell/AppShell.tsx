// 사업주 공통 틀(명세 3.3, 5.0, R9). 옛 AdminLayout·위 가로 탭 Shell을 대신한다.
// - 1280 이상: 왼쪽 사이드바 240(흰 바탕, 오른쪽 1px paper-200)
// - 768~1279: 사이드바를 72 아이콘 모드로 접음
// - 768 미만: 사이드바 대신 아래 탭바(홈·직무·근로자·더보기)
// - 본문 위: 상단 바 56 + 도움 요청 띠(모든 /m 화면, contract §2.2). 본문은 paper-50, 좌우 32(휴대폰 16).
//   목록·홈은 최대 1200, 편집기(/m/tasks/:id)는 꽉 채운다.
// 토스트와 도움 요청 폴링도 여기서 한 번만 연다.
import type { ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { Ellipsis, LogOut, Settings } from "lucide-react";
import HelpAlertStrip from "../../components/HelpAlertStrip";
import { Menu, ToastProvider } from "../../components/ui";
import { cn } from "../../cn";
import { nav, shell } from "../copy";
import HelpFeedProvider from "./HelpFeedProvider";
import TopBar from "./TopBar";
import { NAV_ITEMS, TAB_ITEMS, isFullWidth } from "./navItems";

export interface AppShellProps {
  displayName: string;
  onLogout: () => void;
  children: ReactNode;
}

export default function AppShell({ displayName, onLogout, children }: AppShellProps) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const full = isFullWidth(pathname);

  function logout() {
    onLogout();
    navigate("/m/login", { replace: true });
  }

  return (
    <ToastProvider>
      <HelpFeedProvider>
        <div className="min-h-screen bg-paper-50 font-body text-ink-900">
          <a
            href="#main"
            className="sr-only z-50 rounded-control bg-white px-3 py-2 text-ui-base font-semibold text-ink-900 shadow-ui-md focus:not-sr-only focus:fixed focus:left-4 focus:top-2"
          >
            {shell.skipToContent}
          </a>

          <Sidebar />

          <div className="flex min-h-screen min-w-0 flex-col md:pl-rail xl:pl-sidebar">
            <TopBar displayName={displayName} onLogout={logout} />
            {/* 근로자 도움 요청 띠(요청이 있을 때만 보인다, 창업자 결정 6). 2c에서 LiveProvider가 대신한다. */}
            <HelpAlertStrip />
            <main
              id="main"
              tabIndex={-1}
              className="min-w-0 flex-1 px-4 pb-24 pt-6 focus:outline-none md:px-8 md:pb-8"
            >
              <div className={cn("mx-auto w-full", full ? "max-w-none" : "max-w-page")}>{children}</div>
            </main>
          </div>

          <MobileTabBar onLogout={logout} />
        </div>
      </HelpFeedProvider>
    </ToastProvider>
  );
}

function Sidebar() {
  return (
    <aside
      data-testid="sidebar"
      className="fixed inset-y-0 left-0 z-30 hidden w-rail flex-col border-r border-paper-200 bg-white md:flex xl:w-sidebar"
    >
      <div className="flex h-topbar shrink-0 items-center justify-center gap-2 border-b border-paper-200 xl:justify-start xl:px-5">
        <span aria-hidden="true" className="flex size-8 items-center justify-center rounded-control bg-moss-600 font-display text-ui-md font-bold text-white">
          잡
        </span>
        <span className="sr-only font-display text-ui-lg font-bold text-ink-900 xl:not-sr-only">{shell.brand}</span>
      </div>
      <nav aria-label={nav.mainNav} className="flex-1 overflow-y-auto p-2 xl:p-3">
        <ul className="flex flex-col gap-1">
          {NAV_ITEMS.map((it) => (
            <li key={it.to}>
              <NavLink
                to={it.to}
                end={it.end}
                className={({ isActive }) =>
                  cn(
                    "flex min-h-control-coarse flex-col items-center justify-center gap-0.5 rounded-control px-1 py-1.5 text-ui-xs font-semibold transition-colors duration-hover",
                    "xl:flex-row xl:justify-start xl:gap-3 xl:px-3 xl:text-ui-base",
                    isActive ? "bg-moss-600 text-white" : "text-ink-700 hover:bg-paper-100 hover:text-ink-900",
                  )
                }
              >
                <it.icon size={20} strokeWidth={2} aria-hidden="true" className="shrink-0" />
                <span className="whitespace-nowrap">{it.label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}

const TAB_CLASS = cn(
  "flex h-full min-w-0 flex-1 flex-col items-center justify-center gap-0.5 text-ui-xs font-semibold transition-colors duration-hover",
);

function MobileTabBar({ onLogout }: { onLogout: () => void }) {
  const navigate = useNavigate();
  return (
    <nav
      aria-label={nav.mobileNav}
      data-testid="mobile-tabbar"
      className="fixed inset-x-0 bottom-0 z-30 border-t border-paper-200 bg-white pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      <ul className="flex h-tabbar">
        {TAB_ITEMS.map((it) => (
          <li key={it.to} className="flex min-w-0 flex-1">
            <NavLink
              to={it.to}
              end={it.end}
              className={({ isActive }) => cn(TAB_CLASS, isActive ? "text-moss-600" : "text-ink-500 hover:text-ink-900")}
            >
              <it.icon size={20} strokeWidth={2} aria-hidden="true" />
              <span className="whitespace-nowrap">{it.label}</span>
            </NavLink>
          </li>
        ))}
        <li className="flex min-w-0 flex-1">
          <Menu
            label={nav.more}
            placement="up"
            align="right"
            className="flex-1"
            items={[
              { id: "settings", label: nav.settings, icon: <Settings size={16} strokeWidth={2} aria-hidden="true" />, onSelect: () => navigate("/m/settings") },
              { id: "logout", label: shell.logout, icon: <LogOut size={16} strokeWidth={2} aria-hidden="true" />, onSelect: onLogout },
            ]}
            trigger={(p) => (
              <button {...p} type="button" className={cn(TAB_CLASS, "w-full text-ink-500 hover:text-ink-900")}>
                <Ellipsis size={20} strokeWidth={2} aria-hidden="true" />
                <span className="whitespace-nowrap">{nav.more}</span>
              </button>
            )}
          />
        </li>
      </ul>
    </nav>
  );
}
