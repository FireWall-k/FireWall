// 사업주 메뉴와 이동 경로(명세 3.3). '그림'(/manager/pictures)은 파일럿 전까지 메뉴에 넣지 않는다(contract §2.2).
import { ClipboardList, House, Settings, Users, type LucideIcon } from "lucide-react";
import { nav } from "../copy";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** '/manager'은 자기 주소에서만 켜진다(아래 주소에서는 꺼짐). */
  end?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/manager", label: nav.home, icon: House, end: true },
  { to: "/manager/tasks", label: nav.tasks, icon: ClipboardList },
  { to: "/manager/workers", label: nav.workers, icon: Users },
  { to: "/manager/settings", label: nav.settings, icon: Settings },
];

/** 휴대폰 아래 탭바: 홈·직무·근로자 + 더보기(설정·로그아웃). */
export const TAB_ITEMS = NAV_ITEMS.slice(0, 3);

export interface Crumb {
  label: string;
  to?: string;
}

/** 주소 → 이동 경로. 마지막 칸이 지금 화면이다. */
export function crumbsFor(pathname: string): Crumb[] {
  const p = pathname.replace(/\/+$/, "") || "/manager";
  if (p === "/manager") return [{ label: nav.home }];
  if (p === "/manager/tasks") return [{ label: nav.tasks }];
  if (p === "/manager/tasks/new") return [{ label: nav.tasks, to: "/manager/tasks" }, { label: nav.newTask }];
  if (p.startsWith("/manager/tasks/")) return [{ label: nav.tasks, to: "/manager/tasks" }, { label: nav.editTask }];
  if (p === "/manager/workers") return [{ label: nav.workers }];
  if (p.startsWith("/manager/workers/")) return [{ label: nav.workers, to: "/manager/workers" }, { label: nav.workerDetail }];
  if (p.startsWith("/manager/settings")) return [{ label: nav.settings }];
  if (p.startsWith("/manager/pictures")) return [{ label: nav.pictures }];
  return [{ label: nav.home, to: "/manager" }];
}

/** 편집기(/manager/tasks/:id)는 화면을 꽉 채우고, 목록·홈은 최대 1200(명세 3.3). */
export function isFullWidth(pathname: string): boolean {
  return /^\/manager\/tasks\/(?!new\/?$)[^/]+\/?$/.test(pathname);
}
