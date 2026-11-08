// 근로자 상태 화면 6종(명세 4.9). 일 화면을 못 보여 줄 때 늘 이 화면 하나로 알린다:
// 그림 200 + 제목 32 + 본문 24 + 주 버튼 1개. 영어 원문·서버 문장은 절대 나오지 않는다 —
// 오류는 copy.ts의 toWorkerMessage(err)로 kind를 고른 뒤 이 화면에 넘긴다.
// WorkerScreen(위 띠·아래 막대)에 기대지 않는 단독 전체 화면이다(로그인 전에도 쓴다).
import { useEffect, useState } from "react";
import { COPY } from "../copy";
import { speakText } from "../speech";
import { IconRetry } from "../../ui/icons";
import { Illustration, type IllustrationKind } from "./Illustration";
import { PrimaryAction } from "./WorkerButton";

export type StatusKind = "loading" | "empty" | "offline" | "error" | "expired" | "unpaired";

export interface StatusScreenProps {
  kind: StatusKind;
  /** 주 버튼을 눌렀을 때(다시 해 보기·새로 보기·번호 다시 넣기). 없으면 주 버튼을 그리지 않는다. */
  onAction?: () => void;
  /** unpaired의 작은 보조 버튼 [선생님용: 기기 연결하기]. */
  onSecondary?: () => void;
  /** offline: 받아 둔 일이 있으면 '받아 둔 일은 할 수 있어요.'를 덧붙인다. */
  hasCachedWork?: boolean;
  /** 화면이 열리면 제목을 소리로 읽는다. */
  speak?: boolean;
  /** 브라우저 음성 속도(근로자 설정 tts_rate). */
  ttsRate?: number;
}

/** 느린 불러오기: 8초 뒤 '조금 오래 걸려요', 20초 뒤 [다시 해 보기]. */
export const LOADING_SLOW_MS = 8_000;
export const LOADING_RETRY_MS = 20_000;

const PICTURE: Record<StatusKind, IllustrationKind> = {
  loading: "loading",
  empty: "empty",
  offline: "offline",
  error: "error",
  expired: "unpaired",
  unpaired: "unpaired",
};

function texts(kind: StatusKind, hasCachedWork: boolean): { title: string; body: string[]; action?: string } {
  switch (kind) {
    case "loading":
      return { title: COPY.status.loading.title, body: [], action: COPY.btn.retry };
    case "empty":
      return { title: COPY.status.empty.title, body: [COPY.status.empty.body], action: COPY.btn.refresh };
    case "offline":
      return {
        title: COPY.status.offline.title,
        body: hasCachedWork ? [COPY.status.offline.body, COPY.status.offline.cached] : [COPY.status.offline.body],
        action: COPY.btn.retry,
      };
    case "error":
      return { title: COPY.status.error.title, body: [COPY.status.error.body], action: COPY.btn.retry };
    case "expired":
      return { title: COPY.status.expired.title, body: [], action: COPY.btn.reenter };
    case "unpaired":
      return { title: COPY.status.unpaired.title, body: [COPY.status.unpaired.body] };
  }
}

function useElapsed(active: boolean) {
  const [stage, setStage] = useState<0 | 1 | 2>(0);
  useEffect(() => {
    if (!active) return;
    const slow = window.setTimeout(() => setStage(1), LOADING_SLOW_MS);
    const retry = window.setTimeout(() => setStage(2), LOADING_RETRY_MS);
    return () => {
      window.clearTimeout(slow);
      window.clearTimeout(retry);
      setStage(0);
    };
  }, [active]);
  return stage;
}

export function StatusScreen({ kind, onAction, onSecondary, hasCachedWork = false, speak = false, ttsRate }: StatusScreenProps) {
  const t = texts(kind, hasCachedWork);
  const loadingStage = useElapsed(kind === "loading");
  const isAlert = kind === "offline" || kind === "error" || kind === "expired";

  useEffect(() => {
    if (speak) speakText(t.title, { rate: ttsRate });
    // 제목이 바뀔 때(= kind가 바뀔 때)만 읽는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speak, t.title]);

  const body = kind === "loading" ? (loadingStage >= 1 ? [COPY.status.loading.slow] : []) : t.body;
  const showAction = !!onAction && !!t.action && (kind !== "loading" || loadingStage >= 2);

  return (
    <div
      data-testid="status-screen"
      data-kind={kind}
      className="flex min-h-dvh flex-col items-center justify-center bg-worker-bg px-4 py-8 text-center font-worker text-worker-ink hc:bg-white hc:text-black"
    >
      <div role={isAlert ? "alert" : "status"} className="flex max-w-xl flex-col items-center">
        <Illustration kind={PICTURE[kind]} size={200} className="small:size-40" />
        <h1 className="mt-6 text-worker-lg font-bold">{t.title}</h1>
        {body.map((line) => (
          <p key={line} className="mt-3 text-worker text-worker-ink-soft hc:text-black">
            {line}
          </p>
        ))}
      </div>
      {showAction && (
        <PrimaryAction icon={kind === "empty" || kind === "expired" ? undefined : IconRetry} onPress={onAction!} className="mt-8 w-full max-w-sm">
          {t.action}
        </PrimaryAction>
      )}
      {kind === "unpaired" && onSecondary && (
        // 선생님만 누르는 버튼이라 일부러 작게 둔다(근로자가 우연히 누르지 않게). 그래도 터치 영역은 48px.
        <button
          type="button"
          onClick={onSecondary}
          className="mt-10 min-h-12 rounded-worker-btn px-4 text-worker-caption text-worker-ink-soft underline underline-offset-4 hc:text-black"
        >
          {COPY.btn.teacherSetup}
        </button>
      )}
    </div>
  );
}
