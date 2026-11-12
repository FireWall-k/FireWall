// (2b-2) /m/preview/:taskId — 편집기 미리보기 iframe 안에 그리는 근로자 화면(명세 5.6).
// 근로자와 같은 StepPlayer를 review 모드로 쓴다: 소리 자동 재생 없음, 도와주세요 없음, 기록 없음.
// 여기서는 기록·도움·신호·측정 호출(performance-logs·worker/help·worker/presence·events)을 하나도 부르지 않는다 —
// StepPlayer에 onRecord·onDone·onSignal·onEvent·help를 넘기지 않는다. AppShell(도움 폴링)도 씌우지 않는다.
// 서명 URL이 만료되면(그림·소리 못 읽음) 미리보기를 다시 받는다.
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { DEFAULT_A11Y_PREFS, type A11yPrefs } from "../../api";
import { useMediaRefresh } from "../../media";
import { StepPlayer } from "../../worker/StepPlayer";
import { previewApi } from "../api/preview";
import type { PreviewStep } from "../api/types";
import { preview as copy } from "../copy";
import { isPreviewMessage, PREVIEW_MSG, type PreviewCommandMessage, type PreviewStateMessage } from "./messages";
import { stepWarnings } from "./warnings";

const PREFS: A11yPrefs = { ...DEFAULT_A11Y_PREFS, autoplay_sound: false, sfx: false, vibration: false };
const NO_DONE: ReadonlySet<string> = new Set();

type Load = { kind: "loading" } | { kind: "error" } | { kind: "ready"; title: string; steps: PreviewStep[] };

function post(msg: Omit<PreviewStateMessage, "source">) {
  if (window.parent === window) return;
  window.parent.postMessage({ source: PREVIEW_MSG, ...msg }, window.location.origin);
}

export default function PhonePreviewPage() {
  const { taskId = "" } = useParams();
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [index, setIndex] = useState(0);

  const fetchPreview = useCallback(
    () =>
      previewApi.get(taskId).then((p) => {
        setLoad({ kind: "ready", title: p.title, steps: p.steps });
      }),
    [taskId],
  );

  useEffect(() => {
    let alive = true;
    previewApi
      .get(taskId)
      .then((p) => alive && setLoad({ kind: "ready", title: p.title, steps: p.steps }))
      .catch(() => alive && setLoad({ kind: "error" }));
    return () => {
      alive = false;
    };
  }, [taskId]);

  const onMediaError = useMediaRefresh(fetchPreview);
  const steps = useMemo(() => (load.kind === "ready" ? load.steps : []), [load]);
  const total = steps.length;
  const i = Math.min(index, Math.max(0, total - 1));

  // 바깥 편집기의 [‹ 이전][다음 ›][처음부터 재생]과 편집 뒤 다시 불러오기.
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (!isPreviewMessage<PreviewCommandMessage>(e)) return;
      const cmd = e.data.cmd;
      const last = Math.max(0, total - 1);
      if (cmd === "prev") setIndex((x) => Math.max(0, Math.min(x, last) - 1));
      else if (cmd === "next") setIndex((x) => Math.min(last, x + 1));
      else if (cmd === "restart") setIndex(0);
      else if (cmd === "reload") fetchPreview().catch(() => {});
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [total, fetchPreview]);

  // 지금 단계와 경고를 바깥에 알린다.
  const step = steps[i];
  const warnKey = step ? stepWarnings(step).join(",") : "";
  useEffect(() => {
    const status = load.kind === "ready" ? (total === 0 ? "empty" : "ready") : load.kind;
    post({ status, index: i, total, warnings: warnKey ? (warnKey.split(",") as PreviewStateMessage["warnings"]) : [] });
  }, [load.kind, i, total, warnKey]);

  if (load.kind !== "ready" || total === 0) {
    const text = load.kind === "loading" ? copy.loading : load.kind === "error" ? copy.failed : copy.empty;
    return (
      <main className="flex h-dvh items-center justify-center bg-worker-bg p-6 text-center font-worker text-worker-ink">
        <p className="text-xl font-bold" role="status">
          {text}
        </p>
      </main>
    );
  }

  return (
    <StepPlayer
      mode="review"
      title={load.title}
      steps={steps}
      index={i}
      doneIds={NO_DONE}
      prefs={PREFS}
      onPrev={() => setIndex(Math.max(0, i - 1))}
      onNext={() => setIndex(Math.min(total - 1, i + 1))}
      onExit={() => setIndex(0)}
      onMediaError={onMediaError}
    />
  );
}
