// 근로자 상태 화면 그림(명세 4.9·6.4). 이모지 대신 AAC 카드에 가까운 그림체로 직접 그린 SVG:
// 굵은 검정 선, 단색 면, 글자 없음, 정사각. 뜻은 늘 아래 제목 글자가 전하고, 그림은 거들 뿐이라
// 화면 읽기 프로그램에는 숨긴다(aria-hidden).
import type { ReactElement } from "react";
import { cn } from "../../cn";

export type IllustrationKind = "praise" | "empty" | "error" | "offline" | "unpaired" | "loading";

const INK = "#1A1A1A";
const SKIN = "#F6D2B0";
const SHIRT = "#7FB38F";
const WARM = "#FFE3B8";
const PAPER = "#FFFFFF";
const SOFT = "#E9DFCF";

const line = { stroke: INK, strokeWidth: 6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

/** 잘했어요: 두 팔을 들고 웃는 사람 + 체크 별. */
function Praise() {
  return (
    <>
      <circle cx="100" cy="100" r="88" fill={WARM} />
      <path d="M62 178 C62 138 78 122 100 122 C122 122 138 138 138 178" fill={SHIRT} {...line} />
      <path d="M72 140 L44 92" fill="none" {...line} />
      <path d="M128 140 L156 92" fill="none" {...line} />
      <circle cx="42" cy="86" r="9" fill={SKIN} {...line} />
      <circle cx="158" cy="86" r="9" fill={SKIN} {...line} />
      <circle cx="100" cy="86" r="28" fill={SKIN} {...line} />
      <circle cx="90" cy="82" r="3.5" fill={INK} />
      <circle cx="110" cy="82" r="3.5" fill={INK} />
      <path d="M88 95 Q100 106 112 95" fill="none" {...line} strokeWidth={5} />
      <path d="M140 34 L150 44 L170 22" fill="none" {...line} stroke="#1F6340" strokeWidth={8} />
    </>
  );
}

/** 아직 받은 일이 없어요: 비어 있는 바구니. */
function Empty() {
  return (
    <>
      <circle cx="100" cy="100" r="88" fill={SOFT} />
      <path d="M38 92 L162 92 L148 160 L52 160 Z" fill={PAPER} {...line} />
      <path d="M70 92 L88 50" fill="none" {...line} />
      <path d="M130 92 L112 50" fill="none" {...line} />
      <path d="M78 112 L80 140" fill="none" {...line} strokeWidth={5} />
      <path d="M100 112 L100 140" fill="none" {...line} strokeWidth={5} />
      <path d="M122 112 L120 140" fill="none" {...line} strokeWidth={5} />
    </>
  );
}

/** 잠깐 문제가 생겼어요: 공구(스패너) — 고치는 중. */
function ErrorPic() {
  return (
    <>
      <circle cx="100" cy="100" r="88" fill={WARM} />
      <path
        d="M128 44 a28 28 0 0 0 -30 38 L52 128 a12 12 0 0 0 17 17 L115 99 a28 28 0 0 0 38 -30 L136 86 L118 80 L112 62 Z"
        fill={PAPER}
        {...line}
      />
      <circle cx="60" cy="136" r="4" fill={INK} />
    </>
  );
}

/** 인터넷이 안 돼요: 와이파이 부채꼴 + 빗금. */
function Offline() {
  return (
    <>
      <circle cx="100" cy="100" r="88" fill={SOFT} />
      <path d="M44 88 Q100 40 156 88" fill="none" {...line} strokeWidth={10} />
      <path d="M64 110 Q100 80 136 110" fill="none" {...line} strokeWidth={10} />
      <path d="M84 132 Q100 120 116 132" fill="none" {...line} strokeWidth={10} />
      <circle cx="100" cy="152" r="8" fill={INK} />
      <path d="M48 48 L152 160" fill="none" {...line} stroke="#B45309" strokeWidth={10} />
    </>
  );
}

/** 이 기기를 아직 연결하지 않았어요: 태블릿 + 떨어진 고리 두 개. */
function Unpaired() {
  return (
    <>
      <circle cx="100" cy="100" r="88" fill={SOFT} />
      <rect x="40" y="46" width="80" height="108" rx="12" fill={PAPER} {...line} />
      <circle cx="80" cy="140" r="4" fill={INK} />
      <rect x="120" y="90" width="38" height="22" rx="11" fill="none" {...line} transform="rotate(-30 139 101)" />
      <rect x="138" y="122" width="38" height="22" rx="11" fill="none" {...line} transform="rotate(-30 157 133)" />
    </>
  );
}

/** 일을 가져오고 있어요: 모래시계. */
function Loading() {
  return (
    <>
      <circle cx="100" cy="100" r="88" fill={SOFT} />
      <path d="M64 40 L136 40" fill="none" {...line} />
      <path d="M64 160 L136 160" fill="none" {...line} />
      <path d="M72 40 C72 80 128 80 128 100 C128 120 72 120 72 160" fill="none" {...line} />
      <path d="M128 40 C128 80 72 80 72 100 C72 120 128 120 128 160" fill="none" {...line} />
      <path d="M84 148 Q100 128 116 148 Z" fill={WARM} {...line} strokeWidth={4} />
    </>
  );
}

const PICTURES: Record<IllustrationKind, () => ReactElement> = {
  praise: Praise,
  empty: Empty,
  error: ErrorPic,
  offline: Offline,
  unpaired: Unpaired,
  loading: Loading,
};

export function Illustration({ kind, size = 200, className }: { kind: IllustrationKind; size?: number; className?: string }) {
  const Picture = PICTURES[kind];
  return (
    <svg
      viewBox="0 0 200 200"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
      data-illustration={kind}
      className={cn("shrink-0", className)}
    >
      <Picture />
    </svg>
  );
}
