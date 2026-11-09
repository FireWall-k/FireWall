// 아이콘만 있는 버튼(명세 6.4, 7.3). 화면 읽기 프로그램이 읽을 이름이 없으면 안 되므로 aria-label을
// 타입에서 필수로 둔다(빠뜨리면 tsc가 실패한다 — tests/ui/IconButton.test.tsx).
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "../../cn";
import { iconButtonClasses } from "./styles";

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-label" | "children"> {
  "aria-label": string;
  icon: ReactNode;
  variant?: "ghost" | "secondary";
  /** 아이콘 오른쪽 위 숫자 배지(도움 요청 수 등). 0이면 그리지 않는다. */
  badge?: number;
}

const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon, variant = "ghost", badge, className, type = "button", ...rest },
  ref,
) {
  return (
    <button ref={ref} type={type} className={iconButtonClasses(variant, cn("relative", className))} {...rest}>
      {icon}
      {badge !== undefined && badge > 0 && (
        // 숫자는 CSS 내용(data-badge)으로 그린다: 이름(aria-label)에 이미 수가 들어 있어 글자로 또 두면
        // 화면 읽기 프로그램이 두 번 읽거나, 보이는 글과 이름이 어긋난다(axe label-content-name-mismatch).
        <span
          aria-hidden="true"
          data-badge={badge > 99 ? "99+" : String(badge)}
          className="absolute -right-0.5 -top-0.5 min-w-5 rounded-full bg-danger-700 px-1 text-center text-ui-xs font-bold tabular-nums text-white before:content-[attr(data-badge)]"
        />
      )}
    </button>
  );
});

export default IconButton;
