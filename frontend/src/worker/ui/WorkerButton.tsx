// 근로자 화면 버튼 두 가지(명세 7.1). 화면마다 크기·색을 따로 정하지 않고 이 둘만 쓴다.
// - PrimaryAction: 그 화면에서 할 일 하나([다 했어요]·[시작하기]). 88px, 초록 바탕, 흰 글씨 28px 굵게.
// - SecondaryAction: 그 밖([이전]·[취소]·[멈출래요]). 80px, 흰 바탕, 2px 테두리, 24px.
// 공통: 아이콘은 늘 글자와 함께(아이콘만 있는 버튼 없음), 글자는 줄을 바꾸지 않는다, 600ms 안의 두 번째 누름은
// 무시한다(손 떨림으로 두 번 눌려 단계를 건너뛰지 않게). native <button onClick>을 쓴다 — 손을 뗄 때 실행되고,
// 누른 채 밀어 내면 취소되는 브라우저 기본 동작을 그대로 얻는다.
import { useRef, type ComponentType, type ReactNode } from "react";
import { cn } from "../../cn";
import { IconSpinner, type IconProps } from "../../ui/icons";

/** 이 시간 안의 두 번째 누름은 무시한다. */
export const TAP_DEBOUNCE_MS = 600;

export interface WorkerButtonProps {
  icon?: ComponentType<IconProps>;
  children: ReactNode;
  onPress: () => void;
  disabled?: boolean;
  /** 처리 중: 회전 아이콘을 보이고 누름을 막는다. */
  busy?: boolean;
  /** 켜짐 상태가 있는 버튼(예: 도움 '불렀어요'). 주면 aria-pressed가 붙는다. */
  pressed?: boolean;
  className?: string;
  ariaLabel?: string;
}

function useDebouncedPress(onPress: () => void) {
  const last = useRef(0);
  return () => {
    const now = Date.now();
    if (now - last.current < TAP_DEBOUNCE_MS) return;
    last.current = now;
    onPress();
  };
}

function BaseButton({
  icon: Icon, children, onPress, disabled, busy, pressed, className, ariaLabel, variantClass, iconSize,
}: WorkerButtonProps & { variantClass: string; iconSize: number }) {
  const press = useDebouncedPress(onPress);
  const inactive = disabled || busy;
  return (
    <button
      type="button"
      onClick={inactive ? undefined : press}
      disabled={disabled}
      aria-disabled={busy || undefined}
      aria-busy={busy || undefined}
      aria-pressed={pressed}
      aria-label={ariaLabel}
      className={cn(
        "inline-flex select-none items-center justify-center gap-3 whitespace-nowrap rounded-worker-btn px-6 font-worker",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "hc:border-[3px] hc:border-black",
        variantClass,
        className,
      )}
    >
      {busy ? <IconSpinner size={iconSize} /> : Icon && <Icon size={iconSize} />}
      <span>{children}</span>
    </button>
  );
}

export function PrimaryAction(props: WorkerButtonProps) {
  return (
    <BaseButton
      {...props}
      iconSize={32}
      variantClass="min-h-touch-lg bg-worker-primary text-worker-title text-white active:bg-worker-primary-pressed hc:bg-worker-primary-pressed"
    />
  );
}

export function SecondaryAction(props: WorkerButtonProps) {
  return (
    <BaseButton
      {...props}
      iconSize={28}
      variantClass={cn(
        "min-h-touch border-2 border-worker-line bg-worker-card text-worker font-semibold text-worker-ink active:bg-worker-line-soft",
        props.pressed && "border-[3px] border-worker-primary bg-worker-primary-tint",
      )}
    />
  );
}
