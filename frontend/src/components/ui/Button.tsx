// 사업주 버튼(명세 7.3): primary·secondary·ghost·danger × sm·md, 불러오는 중·비활성.
// 버튼 글자는 동사로 끝낸다(명세 6.7). 글자는 줄을 바꾸지 않는다(whitespace-nowrap).
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { LoaderCircle } from "lucide-react";
import { buttonClasses, type ButtonSize, type ButtonVariant } from "./styles";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** 누른 뒤 서버 응답을 기다리는 중. 눌리지 않고 aria-busy가 붙는다. */
  loading?: boolean;
  /** 글자 앞 아이콘(lucide 16, 굵기 2). */
  icon?: ReactNode;
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading = false, icon, className, children, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClasses(variant, size, className)}
      {...rest}
    >
      {loading ? (
        <LoaderCircle size={16} strokeWidth={2} aria-hidden="true" className="shrink-0 animate-spin motion-reduce:animate-none" />
      ) : (
        icon
      )}
      {children}
    </button>
  );
});

export default Button;
