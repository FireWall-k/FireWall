// 사업주 기본 부품이 함께 쓰는 클래스 모음(명세 6.1~6.3, 7.3). 링크(<Link>)를 버튼 모양으로 그릴 때도 쓴다.
// cn(...)으로 감싸야 eslint-plugin-tailwindcss가 이 안의 클래스도 검사한다(src/cn.ts).
import { cn } from "../../cn";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

const BASE = cn(
  "inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-control font-semibold",
  "transition-colors duration-hover",
  "disabled:cursor-not-allowed disabled:opacity-50 aria-disabled:cursor-not-allowed aria-disabled:opacity-50",
);

const SIZE: Record<ButtonSize, string> = {
  // 컨트롤 36(손가락 기기 44, 명세 6.3). sm은 표 안·띠 안처럼 좁은 자리용 32 — 손가락 기기에서는 똑같이 44.
  md: cn("min-h-control px-3.5 text-ui-base coarse:min-h-control-coarse"),
  sm: cn("min-h-8 px-2.5 text-ui-sm coarse:min-h-control-coarse"),
};

const VARIANT: Record<ButtonVariant, string> = {
  primary: cn("bg-moss-600 text-white hover:bg-moss-700"),
  secondary: cn("border border-line-strong bg-white text-ink-900 hover:bg-paper-100"),
  ghost: cn("text-ink-700 hover:bg-paper-100 hover:text-ink-900"),
  danger: cn("bg-danger-700 text-white hover:bg-danger-800"),
};

export function buttonClasses(variant: ButtonVariant = "secondary", size: ButtonSize = "md", extra?: string): string {
  return cn(BASE, SIZE[size], VARIANT[variant], extra);
}

/** 아이콘만 있는 정사각 버튼. */
export function iconButtonClasses(variant: Exclude<ButtonVariant, "primary" | "danger"> = "ghost", extra?: string): string {
  return cn(
    BASE,
    "size-control coarse:size-control-coarse",
    variant === "ghost" ? cn("text-ink-700 hover:bg-paper-100 hover:text-ink-900") : VARIANT.secondary,
    extra,
  );
}

/** 입력칸 공통 모양. 글자 16(iOS 확대 방지, 명세 6.2), 테두리 line-strong(흰색 위 4.1:1). */
export const inputClasses = cn(
  "block w-full rounded-control border border-line-strong bg-white px-3 text-ui-md text-ink-900",
  "placeholder:text-ink-500 disabled:cursor-not-allowed disabled:bg-paper-100 disabled:text-ink-500",
  "aria-[invalid=true]:border-danger-700",
);

/** 카드: 흰 바탕, 모서리 10, 1px paper-200, 그림자 sm(명세 5.0). */
export const cardClasses = cn("rounded-card border border-paper-200 bg-white shadow-ui-sm");

/** 떠 있는 판(메뉴·툴팁 등). */
export const popoverClasses = cn("rounded-card border border-paper-200 bg-white shadow-ui-md");
