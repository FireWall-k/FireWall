// 탭(명세 7.3). 직무 목록의 걸러보기(전체/초안/확인 필요/보냄/보관)처럼 같은 자리의 내용을 바꾼다.
// 키보드: ←/→로 옮기고 Home/End로 처음·끝(WAI-ARIA tabs, 자동 선택). 숫자는 tabular-nums.
// 휴대폰(768 미만): 탭 사이·안쪽 여백을 줄여 390폭에서 5개가 한 줄에 다 보이게 하고, 그래도 넘치면
// 고른 탭이 보이도록 옆으로 밀어 준다(마지막 '보관'이 반쯤 잘려 안 보이지 않게).
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "../../cn";

export interface TabItem<K extends string> {
  id: K;
  label: ReactNode;
  /** 탭 옆 개수. undefined면 그리지 않는다. */
  count?: number;
}

export interface TabsProps<K extends string> {
  items: TabItem<K>[];
  value: K;
  onChange: (id: K) => void;
  /** 탭 묶음 이름(화면 읽기 프로그램). */
  label: string;
  /** 탭이 다스리는 내용 영역 id. */
  controls?: string;
  /** fill: 좌우를 나눠 채움(로그인 화면). */
  fill?: boolean;
  className?: string;
}

export default function Tabs<K extends string>({ items, value, onChange, label, controls, fill, className }: TabsProps<K>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const selectedIndex = items.findIndex((t) => t.id === value);

  useEffect(() => {
    if (fill) return; // 나눠 채우는 탭(로그인)은 넘치지 않는다.
    // jsdom 등 scrollIntoView가 없는 곳에서는 건너뛴다. 이미 보이면 움직이지 않는다(nearest).
    refs.current[selectedIndex]?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [selectedIndex, fill]);

  function onKeyDown(e: KeyboardEvent, index: number) {
    let next = -1;
    if (e.key === "ArrowRight") next = (index + 1) % items.length;
    else if (e.key === "ArrowLeft") next = (index - 1 + items.length) % items.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = items.length - 1;
    if (next < 0) return;
    e.preventDefault();
    onChange(items[next].id);
    refs.current[next]?.focus();
  }

  return (
    <div role="tablist" aria-label={label} className={cn("flex overflow-x-auto border-b border-paper-200", fill ? "gap-1" : "gap-0 md:gap-1", className)}>
      {items.map((t, i) => {
        const selected = t.id === value;
        return (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={controls}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(t.id)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={cn(
              "-mb-px inline-flex min-h-control items-center justify-center whitespace-nowrap border-b-2 text-ui-base font-semibold transition-colors duration-hover coarse:min-h-control-coarse",
              fill ? "flex-1 gap-1.5 px-3" : "shrink-0 gap-0.5 px-2 md:gap-1.5 md:px-3",
              selected ? "border-moss-600 text-ink-900" : "border-transparent text-ink-500 hover:text-ink-900",
            )}
          >
            {t.label}
            {t.count !== undefined && (
              <span
                className={cn(
                  "rounded-full text-ui-xs tabular-nums",
                  fill ? "px-1.5" : "px-1 md:px-1.5",
                  selected ? "bg-moss-600 text-white" : "bg-paper-100 text-ink-700",
                )}
              >
                {t.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
