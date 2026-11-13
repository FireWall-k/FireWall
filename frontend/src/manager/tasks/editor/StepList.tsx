// 편집기 단계 목록(명세 5.5 '단계 목록', tasks §4.3 StepList).
// - 행 88: 번호(tabular), 썸네일 64, 문장 2줄, 상태 줄(점 + 아이콘 + 글: 확인함·✦ 자동 · 확인 필요·골라 주세요·그림 없음).
// - 순서 바꾸기는 손잡이 끌기와 키보드 손잡이(Space로 들고 ↑↓로 옮긴 뒤 Space로 놓음, Esc 취소, aria-live로 알림).
//   마우스·손가락 끌기는 손잡이를 누른 채 끌기(usePointerReorder, 2b-2).
// - [+ 단계 추가]. 9단계가 넘으면 행마다 [묶음 나누기](group_break, 구분선)를 쓸 수 있다(데이터만, contract §3.1).
import { useRef, useState, type KeyboardEvent, type Ref } from "react";
import { GripVertical, Plus, Scissors, TriangleAlert } from "lucide-react";
import { Badge, Button, Input } from "../../../components/ui";
import { cn } from "../../../cn";
import type { EditorStep } from "../../api/types";
import { editor as copy, pictureStatus } from "../../copy";
import { STATE_TONE } from "./review";
import { usePointerReorder } from "./usePointerReorder";

/** 이 단계 수를 넘으면 [묶음 나누기]를 보인다(명세 4.7·5.5). */
export const GROUP_BREAK_AFTER = 9;

export interface StepListProps {
  steps: EditorStep[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** from번째 단계를 to번째 자리로(0부터). */
  onMove: (from: number, to: number) => void;
  onAddStep: (sentence: string) => Promise<boolean>;
  onToggleGroupBreak: (id: string, value: boolean) => void;
  /** 보내기가 막힌 단계(빨간 테두리). */
  blockedIds: ReadonlySet<string>;
  /** 저장(순서·추가)을 기다리는 중이면 순서 단추를 잠근다. */
  busy?: boolean;
  /** 서명 URL(사진)을 못 불러왔을 때 — 직무를 다시 받아 URL만 바꾼다. */
  onMediaError?: (url: string | null | undefined) => void;
  /** 목록 제목(화면 읽기 프로그램용). 390에서 단계를 지운 뒤 이웃 행이 없으면 여기로 초점을 옮긴다. */
  headingRef?: Ref<HTMLHeadingElement>;
}

interface Grab {
  id: string;
  from: number;
  at: number;
}

function moved<T>(list: T[], from: number, to: number): T[] {
  const next = [...list];
  const [x] = next.splice(from, 1);
  next.splice(to, 0, x);
  return next;
}

export default function StepList({
  steps, selectedId, onSelect, onMove, onAddStep, onToggleGroupBreak, blockedIds, busy = false, onMediaError, headingRef,
}: StepListProps) {
  const [grab, setGrab] = useState<Grab | null>(null);
  const [live, setLive] = useState("");
  const [adding, setAdding] = useState("");
  const [addBusy, setAddBusy] = useState(false);
  const handles = useRef<Map<string, HTMLButtonElement>>(new Map());
  const pointer = usePointerReorder({ ids: steps.map((s) => s.id), disabled: busy || !!grab, onMove });
  const active = grab ?? pointer.drag;
  const shown = active ? moved(steps, active.from, active.at) : steps;
  const showGroup = steps.length > GROUP_BREAK_AFTER;

  function focusHandle(id: string) {
    requestAnimationFrame(() => handles.current.get(id)?.focus());
  }

  function onHandleKey(e: KeyboardEvent<HTMLButtonElement>, step: EditorStep, index: number) {
    if (busy) return;
    if (!grab) {
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        setGrab({ id: step.id, from: index, at: index });
        setLive(copy.grabbed(index + 1));
      }
      return;
    }
    if (grab.id !== step.id) return;
    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      e.preventDefault();
      const at = Math.max(0, Math.min(steps.length - 1, grab.at + (e.key === "ArrowUp" ? -1 : 1)));
      if (at !== grab.at) {
        setGrab({ ...grab, at });
        setLive(copy.movedTo(at + 1));
        focusHandle(step.id);
      }
    } else if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      const g = grab;
      setGrab(null);
      setLive(g.at === g.from ? copy.reorderCancelled : copy.droppedAt(g.at + 1));
      if (g.at !== g.from) onMove(g.from, g.at);
      focusHandle(step.id);
    } else if (e.key === "Escape" || e.key === "Tab") {
      if (e.key === "Escape") e.preventDefault();
      setGrab(null);
      setLive(copy.reorderCancelled);
    }
  }

  async function submitAdd() {
    const text = adding.trim();
    if (!text || addBusy) return;
    setAddBusy(true);
    const ok = await onAddStep(text);
    setAddBusy(false);
    if (ok) setAdding("");
  }

  return (
    <div className="flex flex-col gap-3">
      <h2 ref={headingRef} tabIndex={-1} className="sr-only">
        {copy.stepsHeading}
      </h2>
      <p id="step-grab-hint" className="sr-only">
        {copy.grabHint}
      </p>
      <p aria-live="assertive" className="sr-only" data-testid="reorder-live">
        {live}
      </p>
      <ol aria-label={copy.stepsHeading} className="flex flex-col gap-2">
        {shown.map((s, i) => {
          const n = i + 1;
          const selected = s.id === selectedId;
          const lifted = active?.id === s.id;
          const blocked = blockedIds.has(s.id);
          return (
            <li key={s.id} data-step-id={s.id} className="flex flex-col gap-2">
              {showGroup && s.group_break && i > 0 && (
                <div role="separator" aria-label={copy.groupDivider} className="flex items-center gap-2 text-ui-xs font-semibold text-ink-700">
                  <span aria-hidden="true" className="h-px flex-1 bg-line-strong" />
                  {copy.groupDivider}
                  <span aria-hidden="true" className="h-px flex-1 bg-line-strong" />
                </div>
              )}
              <div
                data-testid={`step-row-${n}`}
                data-state={s.picture_state}
                data-selected={selected || undefined}
                className={cn(
                  "flex min-h-list-row items-stretch rounded-card border bg-white transition-colors duration-hover",
                  selected ? "border-moss-600 ring-1 ring-moss-600" : "border-paper-200",
                  blocked && "border-danger-700 bg-danger-50",
                  lifted && "shadow-ui-md ring-2 ring-moss-600",
                )}
              >
                <button
                  type="button"
                  onClick={() => onSelect(s.id)}
                  aria-current={selected ? "step" : undefined}
                  data-row-select=""
                  className="flex min-w-0 flex-1 items-center gap-3 rounded-l-card px-3 py-2 text-left hover:bg-paper-50"
                >
                  <span className="w-5 shrink-0 text-right text-ui-base font-bold tabular-nums text-ink-700">
                    {n}
                    {/* 이름은 보이는 글 그대로(번호·문장·상태 배지) — aria-label로 덮으면 보이는 상태를 못 듣는다(axe). */}
                    <span className="sr-only">{copy.stepWord}</span>
                  </span>
                  <span className="flex size-16 shrink-0 items-center justify-center overflow-hidden rounded-control border border-paper-200 bg-white">
                    {s.symbol_url ? (
                      <img src={s.symbol_url} alt="" loading="lazy" onError={() => onMediaError?.(s.symbol_url)} className="size-full object-contain" />
                    ) : (
                      <span aria-hidden="true" className="text-ui-xs text-ink-500">
                        —
                      </span>
                    )}
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className="line-clamp-2 text-ui-base text-ink-900">{s.sentence}</span>
                    <span className="flex flex-wrap items-center gap-1.5">
                      <Badge tone={STATE_TONE[s.picture_state]} icon={s.picture_state === "auto_high" ? false : undefined}>
                        {pictureStatus[s.picture_state]}
                      </Badge>
                      {s.safety_flag && (
                        <Badge
                          tone={s.safety.source === "auto" ? "auto" : "warning"}
                          icon={<TriangleAlert size={12} strokeWidth={2} aria-hidden="true" className="shrink-0" />}
                        >
                          {copy.caution}
                        </Badge>
                      )}
                    </span>
                  </span>
                </button>
                <div className="flex shrink-0 flex-col items-center justify-center gap-0.5 border-l border-paper-200 px-1 py-1">
                  <button
                    type="button"
                    ref={(el) => {
                      if (el) handles.current.set(s.id, el);
                      else handles.current.delete(s.id);
                    }}
                    aria-label={copy.grab(n)}
                    aria-describedby="step-grab-hint"
                    aria-pressed={lifted}
                    onKeyDown={(e) => onHandleKey(e, s, i)}
                    {...pointer.handleProps(s.id)}
                    data-testid={`step-grip-${n}`}
                    onBlur={() => {
                      if (lifted) {
                        setGrab(null);
                        setLive(copy.reorderCancelled);
                      }
                    }}
                    title={copy.grabHint}
                    className={cn(
                      "inline-flex size-8 cursor-grab touch-none items-center justify-center rounded-control text-ink-700 hover:bg-paper-100 active:cursor-grabbing coarse:size-control-coarse",
                      lifted && "bg-moss-600 text-white hover:bg-moss-700",
                    )}
                  >
                    <GripVertical size={16} strokeWidth={2} aria-hidden="true" />
                  </button>
                </div>
              </div>
              {showGroup && i > 0 && !active && (
                <button
                  type="button"
                  aria-pressed={s.group_break}
                  onClick={() => onToggleGroupBreak(s.id, !s.group_break)}
                  className="-mt-1 inline-flex min-h-8 items-center gap-1 self-start rounded-control px-2 text-ui-xs font-semibold text-ink-700 hover:bg-paper-100 coarse:min-h-control-coarse"
                >
                  <Scissors size={14} strokeWidth={2} aria-hidden="true" />
                  {copy.groupBreakLabel(n)}
                </button>
              )}
            </li>
          );
        })}
      </ol>
      {showGroup && <p className="text-ui-sm text-ink-700">{copy.groupHint}</p>}

      <form
        className="flex flex-col gap-2 rounded-card border border-dashed border-line-strong bg-white p-3"
        onSubmit={(e) => {
          e.preventDefault();
          void submitAdd();
        }}
      >
        <label htmlFor="add-step-input" className="flex items-center gap-1 text-ui-base font-semibold text-ink-900">
          <Plus size={16} strokeWidth={2} aria-hidden="true" />
          {copy.addStep}
        </label>
        <div className="flex gap-2">
          <Input
            id="add-step-input"
            aria-label={copy.addStepLabel}
            value={adding}
            onChange={(e) => setAdding(e.target.value)}
            placeholder={copy.addStepPlaceholder}
            maxLength={500}
          />
          <Button type="submit" variant="secondary" loading={addBusy} disabled={!adding.trim()}>
            {copy.addStepSubmit}
          </Button>
        </div>
      </form>
    </div>
  );
}
