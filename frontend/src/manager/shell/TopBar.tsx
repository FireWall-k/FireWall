// 상단 바 56(명세 3.3, 5.0): 이동 경로 · [새 직무] · 도움 요청 종(숫자 배지) · 사용자 메뉴.
// 종은 띠와 같은 오늘 현황(useLive, LiveProvider 하나)을 읽는다 — 같은 주소를 두 번 부르지 않는다.
// (2c) 사용자 메뉴에 '도움 알림 받기' 스위치(웹 푸시). 서버에 키가 없거나 브라우저가 못 하면 보이지 않는다.
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Bell, BellRing, ChevronRight, CircleUser, LogOut, Plus, Settings } from "lucide-react";
import { IconButton, Menu, buttonClasses, useToast, type MenuItem } from "../../components/ui";
import { cn } from "../../cn";
import { nav, pushToggle, shell } from "../copy";
import { crumbsFor } from "./navItems";
import { guardLeave } from "../tasks/new/useLeaveGuard";
import { usePushToggle } from "./pushToggle";
import { useLive } from "./useLive";

export interface TopBarProps {
  displayName: string;
  onLogout: () => void;
}

/** 띠의 첫 버튼으로 초점을 옮긴다(띠는 본문 위에 있다). */
function focusHelpStrip() {
  const strip = document.querySelector<HTMLElement>("[data-testid='help-band']");
  if (!strip) return;
  (strip.querySelector<HTMLElement>("button") ?? strip).focus();
}

export default function TopBar({ displayName, onLogout }: TopBarProps) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { help } = useLive();
  const push = usePushToggle();
  const toast = useToast();
  const crumbs = crumbsFor(pathname);
  const name = displayName || shell.employerFallbackName;
  const helpCount = help.length;

  async function togglePush() {
    const r = await push.toggle();
    if (r === "on") toast.show({ tone: "success", message: pushToggle.turnedOn });
    else if (r === "off") toast.show({ tone: "info", message: pushToggle.turnedOff });
    else if (r === "denied") toast.show({ tone: "error", message: pushToggle.denied });
    else toast.show({ tone: "error", message: pushToggle.failed });
  }

  const menuItems: MenuItem[] = [
    ...(push.available
      ? [{
          id: "push",
          label: pushToggle.label,
          hint: push.on ? pushToggle.on : pushToggle.off,
          disabled: push.busy,
          icon: <BellRing size={16} strokeWidth={2} aria-hidden="true" />,
          onSelect: () => void togglePush(),
        }]
      : []),
    { id: "settings", label: nav.settings, icon: <Settings size={16} strokeWidth={2} aria-hidden="true" />, onSelect: () => guardLeave(() => navigate("/m/settings")) },
    { id: "logout", label: shell.logout, icon: <LogOut size={16} strokeWidth={2} aria-hidden="true" />, onSelect: () => guardLeave(onLogout) },
  ];

  return (
    <header className="sticky top-0 z-20 flex h-topbar items-center gap-2 border-b border-paper-200 bg-white px-4 md:px-8">
      <nav aria-label={nav.breadcrumb} className="min-w-0 flex-1">
        <ol className="flex min-w-0 items-center gap-1 text-ui-base">
          {crumbs.map((c, i) => {
            const last = i === crumbs.length - 1;
            return (
              <li key={c.label} className={cn("flex min-w-0 items-center gap-1", !last && "shrink-0")}>
                {c.to && !last ? (
                  <Link
                    to={c.to}
                    className="inline-flex items-center whitespace-nowrap text-ink-500 hover:text-ink-900 hover:underline coarse:-mx-2 coarse:min-h-control-coarse coarse:min-w-control-coarse coarse:justify-center coarse:px-2"
                  >
                    {c.label}
                  </Link>
                ) : (
                  <span aria-current={last ? "page" : undefined} className="truncate font-bold text-ink-900">
                    {c.label}
                  </span>
                )}
                {!last && <ChevronRight size={16} strokeWidth={2} aria-hidden="true" className="shrink-0 text-ink-500" />}
              </li>
            );
          })}
        </ol>
      </nav>

      <Link to="/m/tasks/new" className={buttonClasses("primary", "md")}>
        <Plus size={16} strokeWidth={2} aria-hidden="true" />
        {nav.newTask}
      </Link>

      <IconButton
        aria-label={shell.helpBell(helpCount)}
        icon={<Bell size={20} strokeWidth={2} aria-hidden="true" />}
        badge={helpCount}
        disabled={helpCount === 0}
        onClick={focusHelpStrip}
        data-testid="help-bell"
      />

      <Menu
        label={shell.userMenu}
        items={menuItems}
        trigger={(p) => (
          <button
            {...p}
            type="button"
            className="inline-flex min-h-control min-w-control items-center justify-center gap-2 rounded-control px-1 text-ink-700 hover:bg-paper-100 coarse:min-h-control-coarse coarse:min-w-control-coarse md:px-2"
          >
            <CircleUser size={20} strokeWidth={2} aria-hidden="true" className="shrink-0" />
            {/* 이름은 넓은 화면에서만 보이고, 좁은 화면에서는 화면 읽기 프로그램만 읽는다. */}
            <span className="sr-only max-w-32 truncate text-ui-base font-semibold text-ink-900 lg:not-sr-only">{name}</span>
            <span className="sr-only">{shell.userMenuSuffix}</span>
          </button>
        )}
      />
    </header>
  );
}
