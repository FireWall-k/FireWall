// 입력 부품(명세 7.3): Field가 보이는 라벨·도움말·오류를 그리고, 안의 Input/Textarea/Select가 id와
// aria-describedby·aria-invalid를 Field에서 받아 연결한다(라벨이 눈에 보여야 함, KWCAG 7.3.2).
// Checkbox·Switch는 라벨이 옆에 붙는 꼴이라 스스로 라벨을 그린다.
import {
  createContext,
  forwardRef,
  useContext,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { Check } from "lucide-react";
import { cn } from "../../cn";
import { inputClasses } from "./styles";

interface FieldCtx {
  id: string;
  describedBy?: string;
  invalid: boolean;
  disabled: boolean;
  required: boolean;
}

const FieldContext = createContext<FieldCtx | null>(null);

export interface FieldProps {
  label: ReactNode;
  /** 라벨 아래 설명(13px ink-500). */
  hint?: ReactNode;
  /** 오류 문장(무엇이 안 됐는지 + 다음 할 일). 있으면 칸이 빨개지고 aria-invalid가 붙는다. */
  error?: ReactNode;
  disabled?: boolean;
  required?: boolean;
  /** 입력칸 id를 직접 정할 때. */
  id?: string;
  className?: string;
  children: ReactNode;
}

export function Field({ label, hint, error, disabled = false, required = false, id, className, children }: FieldProps) {
  const auto = useId();
  const fieldId = id ?? `f${auto}`;
  const hintId = hint ? `${fieldId}-hint` : undefined;
  const errorId = error ? `${fieldId}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <FieldContext.Provider value={{ id: fieldId, describedBy, invalid: !!error, disabled, required }}>
      <div className={cn("flex flex-col gap-1.5", className)}>
        <label htmlFor={fieldId} className="text-ui-base font-semibold text-ink-900">
          {label}
        </label>
        {hint && (
          <p id={hintId} className="text-ui-sm text-ink-500">
            {hint}
          </p>
        )}
        {children}
        {error && (
          <p id={errorId} className="text-ui-sm font-semibold text-danger-700">
            {error}
          </p>
        )}
      </div>
    </FieldContext.Provider>
  );
}

function useFieldProps(props: { id?: string; disabled?: boolean; required?: boolean; "aria-describedby"?: string }) {
  const ctx = useContext(FieldContext);
  return {
    id: props.id ?? ctx?.id,
    disabled: props.disabled ?? ctx?.disabled,
    required: props.required ?? ctx?.required,
    "aria-describedby": [ctx?.describedBy, props["aria-describedby"]].filter(Boolean).join(" ") || undefined,
    "aria-invalid": ctx?.invalid ? true : undefined,
  };
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest },
  ref,
) {
  const f = useFieldProps(rest);
  return <input ref={ref} {...rest} {...f} className={cn(inputClasses, "min-h-control coarse:min-h-control-coarse", className)} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, rows = 4, ...rest },
  ref,
) {
  const f = useFieldProps(rest);
  return <textarea ref={ref} rows={rows} {...rest} {...f} className={cn(inputClasses, "py-2", className)} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, children, ...rest },
  ref,
) {
  const f = useFieldProps(rest);
  return (
    <select ref={ref} {...rest} {...f} className={cn(inputClasses, "min-h-control pr-8 coarse:min-h-control-coarse", className)}>
      {children}
    </select>
  );
});

interface ToggleProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "onChange"> {
  label: ReactNode;
  hint?: ReactNode;
  onChange?: (checked: boolean) => void;
}

export function Checkbox({ label, hint, onChange, className, id, disabled, ...rest }: ToggleProps) {
  const auto = useId();
  const boxId = id ?? `c${auto}`;
  const hintId = hint ? `${boxId}-hint` : undefined;
  return (
    <div className={cn("flex items-start gap-2", className)}>
      <span className="relative mt-0.5 inline-flex size-5 shrink-0 coarse:mt-0">
        <input
          id={boxId}
          type="checkbox"
          disabled={disabled}
          aria-describedby={hintId}
          onChange={(e) => onChange?.(e.target.checked)}
          className="peer size-5 cursor-pointer appearance-none rounded border border-line-strong bg-white checked:border-moss-600 checked:bg-moss-600 disabled:cursor-not-allowed disabled:opacity-50"
          {...rest}
        />
        <Check
          size={14}
          strokeWidth={3}
          aria-hidden="true"
          className="pointer-events-none absolute left-[3px] top-[3px] hidden text-white peer-checked:block"
        />
      </span>
      <span className="flex min-w-0 flex-col">
        <label htmlFor={boxId} className={cn("cursor-pointer text-ui-base text-ink-900", disabled && "text-ink-500")}>
          {label}
        </label>
        {hint && (
          <span id={hintId} className="text-ui-sm text-ink-500">
            {hint}
          </span>
        )}
      </span>
    </div>
  );
}

export interface SwitchProps {
  label: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  hint?: ReactNode;
  disabled?: boolean;
  id?: string;
  className?: string;
}

/** 켜고 끄는 스위치. role=switch + aria-checked. 글자 라벨을 누르거나 스위치를 눌러 바꾼다. */
export function Switch({ label, checked, onChange, hint, disabled = false, id, className }: SwitchProps) {
  const auto = useId();
  const switchId = id ?? `s${auto}`;
  const labelId = `${switchId}-label`;
  const hintId = hint ? `${switchId}-hint` : undefined;
  return (
    <div className={cn("flex items-start justify-between gap-3", className)}>
      <span className="flex min-w-0 flex-col">
        <span id={labelId} className={cn("text-ui-base text-ink-900", disabled && "text-ink-500")} onClick={() => !disabled && onChange(!checked)}>
          {label}
        </span>
        {hint && (
          <span id={hintId} className="text-ui-sm text-ink-500">
            {hint}
          </span>
        )}
      </span>
      {/* 누를 곳은 단추 전체(36, 터치 화면 44 — 명세 6.3), 보이는 손잡이는 안쪽 24px 막대. */}
      <button
        id={switchId}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={labelId}
        aria-describedby={hintId}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className="group inline-flex min-h-control min-w-control shrink-0 items-center justify-center rounded-full disabled:cursor-not-allowed coarse:min-h-control-coarse coarse:min-w-control-coarse"
      >
        <span
          aria-hidden="true"
          className={cn(
            "relative inline-flex h-6 w-11 items-center rounded-full border transition-colors duration-hover",
            "group-disabled:opacity-50",
            checked ? "border-moss-600 bg-moss-600" : "border-line-strong bg-paper-200",
          )}
        >
          <span
            className={cn(
              "inline-block size-4 rounded-full bg-white shadow-ui-sm transition-transform duration-hover",
              checked ? "translate-x-6" : "translate-x-1",
            )}
          />
        </span>
      </button>
    </div>
  );
}
