// 근로자 화면 공통 틀(명세 4.0, 7.1 WorkerScreen·WorkerTopBar·BottomActionBar·띠).
// 세로 3칸: 위 띠 / (띠 한 개) / 내용 / 아래 막대. 높이는 100dvh, 문서는 스크롤하지 않는다 —
// 넘치면 가운데 내용만 스크롤하고 위 띠·아래 막대(주 버튼)는 늘 화면 안에 남는다.
// 띠(도움·오프라인·기록 보냄)는 한 번에 하나만 보인다. 도움 띠가 있으면 오프라인은 위 띠 가운데 작은 표시로.
import type { ReactNode } from "react";
import { cn } from "../cn";
import { COPY } from "./copy";
import { IconOffline } from "../ui/icons";

export function WorkerScreen({
  top,
  band,
  bottom,
  children,
  mainClassName,
  testId,
}: {
  top: ReactNode;
  band?: ReactNode;
  bottom?: ReactNode;
  children: ReactNode;
  mainClassName?: string;
  testId?: string;
}) {
  return (
    <div
      data-testid={testId}
      className="flex h-dvh flex-col overflow-hidden bg-worker-bg font-worker text-worker-ink hc:bg-white hc:text-black"
    >
      {top}
      {band}
      <main
        data-testid="worker-main"
        className={cn(
          // 내용이 넘쳐도 줄어들지 않고(겹침 방지) 이 칸만 스크롤한다.
          "mx-auto flex min-h-0 w-full max-w-[1024px] flex-1 flex-col overflow-y-auto px-4 tablet:px-8 [&>*]:shrink-0",
          mainClassName,
        )}
      >
        {children}
      </main>
      {bottom}
    </div>
  );
}

/** 위 띠: 왼쪽(나가기·홈으로·인사) / 가운데(오프라인 표시 자리) / 오른쪽(도와주세요·끝내기).
 *  높이 80, 태블릿 96. 작은 화면(명세 4.0 작은 기기 규칙)은 72 — 다만 버튼은 그때도 80px 이상이라(명세 4.0),
 *  80px 버튼이 있는 띠는 버튼 높이만큼(80)이고, 버튼 없는 띠(번호 넣기 등)만 72로 줄어든다. 띠에 위아래 여백은 없다. */
export function TopBar({ left, center, right }: { left?: ReactNode; center?: ReactNode; right?: ReactNode }) {
  return (
    <header className="w-full shrink-0 border-b-2 border-worker-line-soft bg-worker-bg pt-[env(safe-area-inset-top)] hc:border-black hc:bg-white">
      <div className="mx-auto flex h-worker-top w-full max-w-[1024px] items-center justify-between gap-2 px-4 small:h-auto small:min-h-worker-top-sm tablet:h-worker-top-tab tablet:px-8">
        <div className="flex min-w-0 items-center">{left}</div>
        <div className="flex min-w-0 flex-1 items-center justify-center">{center}</div>
        <div className="flex shrink-0 items-center">{right}</div>
      </div>
    </header>
  );
}

/** 아래 행동 막대: 버튼 1·2개. 왼손 설정이면 좌우를 바꾼다(주 버튼이 왼쪽). */
export function BottomBar({ children, stacked = false, className }: { children: ReactNode; stacked?: boolean; className?: string }) {
  return (
    <footer className="w-full shrink-0 border-t-2 border-worker-line-soft bg-worker-bg pb-[env(safe-area-inset-bottom)] hc:border-black hc:bg-white">
      <div
        className={cn(
          "mx-auto flex w-full max-w-[1024px] gap-6 px-4 py-3 small:py-2 tablet:px-8 tablet:py-4",
          // 쌓은 두 버튼도 가로 휴대폰(낮은 화면)에서는 나란히 둔다 — 쌓으면 아래 막대가 화면 절반을 먹는다.
          stacked ? "flex-col land:flex-row land:items-stretch land:lefty:flex-row-reverse" : "items-stretch lefty:flex-row-reverse",
          className,
        )}
      >
        {children}
      </div>
    </footer>
  );
}

/** 띠 공통 모양(64px 이상, 24px 글씨, role=status). 작은 화면에서도 글씨는 24px이다(3차 검증: 20px로 줄였었다,
 *  명세 4.5) — 대신 여백을 줄인다. */
export function Band({
  tone,
  children,
  testId,
  spaced = false,
}: {
  tone: "help" | "offline" | "synced";
  children: ReactNode;
  testId?: string;
  /** 버튼이 있는 띠: 위 띠 버튼과 24px 넘게 떨어뜨린다. */
  spaced?: boolean;
}) {
  return (
    <div
      role="status"
      data-testid={testId}
      className={cn(
        "w-full shrink-0 border-b-2",
        tone === "help" && "border-worker-help-line bg-worker-help text-worker-help-ink",
        tone === "offline" && "border-worker-caution-ink bg-worker-caution text-worker-caution-ink",
        tone === "synced" && "border-worker-primary bg-worker-primary-tint text-worker-primary",
        "hc:border-black hc:bg-white hc:text-black",
      )}
    >
      <div
        className={cn(
          "mx-auto flex min-h-16 w-full max-w-[1024px] items-center gap-3 px-4 py-1 text-worker font-semibold small:min-h-14 small:gap-2 small:px-3 tablet:px-8",
          // 버튼이 있는 띠([취소]·[다시 부르기])는 위 띠의 [도와주세요]와 24px 넘게 떨어뜨린다(명세 8.1: 다른 행동
          // 버튼 사이 24px. 2차 검증: 6px 아래라 '불렀어요'를 조금 낮게 누르면 취소됐다).
          spaced && "pt-6",
        )}
      >
        {children}
      </div>
    </div>
  );
}

export function OfflineBanner() {
  return (
    <Band tone="offline" testId="offline-band">
      <IconOffline size={28} />
      <p className="min-w-0 flex-1">{COPY.band.offline}</p>
    </Band>
  );
}

export function SyncNotice() {
  return (
    <Band tone="synced" testId="sync-notice">
      <p className="min-w-0 flex-1">{COPY.band.synced}</p>
    </Band>
  );
}

/** 도움 띠가 떠 있을 때 위 띠 가운데에 두는 작은 오프라인 표시(20px). 좁은 휴대폰(420 이하)은 아이콘 아래에
 *  '끊김' 두 글자 — 아이콘만으로는 뜻을 알기 어렵다(2차 검증). 화면 읽기 프로그램은 늘 '인터넷 끊김'을 읽는다. */
export function OfflineMark() {
  return (
    <span role="status" data-testid="offline-mark" aria-label={COPY.band.offlineShort}
      className="flex items-center gap-1 text-worker-caption leading-tight text-worker-caution-ink hc:text-black max-[420px]:flex-col max-[420px]:gap-0">
      <IconOffline size={24} />
      <span aria-hidden="true" className="whitespace-nowrap max-[420px]:hidden">{COPY.band.offlineShort}</span>
      <span aria-hidden="true" className="hidden whitespace-nowrap max-[420px]:inline">{COPY.band.offlineTiny}</span>
    </span>
  );
}
