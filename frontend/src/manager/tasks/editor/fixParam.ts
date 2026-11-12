// 편집기 주소의 ?fix=(홈의 코칭 카드·도움 띠가 붙여 보냄, home/time.ts editorLink).
// ?step=으로 그 단계를 연 뒤, fix에 따라 할 일을 바로 연다. 한 번 쓰면 주소에서 지운다(새로고침에 다시 열리지 않게).
import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";

export type FixAction = { kind: "picker"; mode: "search" | "photo" } | { kind: "detail" };

/** picture → 그림 고르기 창, photo → 사진 올리기 창, split·easy_words → 그 단계 상세(문장 고치기). 모르는 값은 무시. */
export function fixAction(fix: string | null | undefined): FixAction | null {
  switch ((fix ?? "").trim()) {
    case "picture":
      return { kind: "picker", mode: "search" };
    case "photo":
      return { kind: "picker", mode: "photo" };
    case "split":
    case "easy_words":
      return { kind: "detail" };
    default:
      return null;
  }
}

/**
 * 불러온 직무에 ?step= 단계가 있을 때 한 번만 onPicker를 부른다. stepId가 없거나 직무에 없는 단계면 아무것도 하지 않고
 * fix만 지운다(엉뚱한 단계의 창을 열지 않게).
 */
export function useFixParam(opts: { ready: boolean; hasStep: (id: string) => boolean; onPicker: (stepId: string, mode: "search" | "photo") => void }) {
  const [params, setParams] = useSearchParams();
  const done = useRef(false);
  const { ready, hasStep, onPicker } = opts;
  const fix = params.get("fix");
  const stepId = params.get("step");
  useEffect(() => {
    if (done.current || !ready || fix === null) return;
    done.current = true;
    const action = fixAction(fix);
    if (action?.kind === "picker" && stepId && hasStep(stepId)) onPicker(stepId, action.mode);
    setParams(
      (cur) => {
        const next = new URLSearchParams(cur);
        next.delete("fix");
        return next;
      },
      { replace: true },
    );
  }, [ready, fix, stepId, hasStep, onPicker, setParams]);
}
