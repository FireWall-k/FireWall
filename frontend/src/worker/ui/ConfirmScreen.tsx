// 근로자 확인 화면(명세 4.10). 작은 대화상자 대신 전체 화면 하나로 묻는다 — 작은 상자는 어디를 눌러야
// 할지 헷갈리고, 바깥을 눌러 닫히는 동작이 예상 밖이다. 위에 [계속할래요](주), 24px 아래에 멈춤/끝냄(보조).
// '계속'이 늘 위·주 버튼이라, 잘못 눌러 들어와도 같은 자리를 한 번 더 누르면 하던 일로 돌아간다.
import { useEffect, useId, useRef } from "react";
import { COPY } from "../copy";
import { speakText } from "../speech";
import { IconEnd, IconPlay, IconStop } from "../../ui/icons";
import { PrimaryAction, SecondaryAction } from "./WorkerButton";

export interface ConfirmScreenProps {
  kind: "exit" | "end";
  onStay: () => void;
  onLeave: () => void;
  /** 열리면 제목을 소리로 읽는다. */
  speak?: boolean;
  ttsRate?: number;
  /** 질문 아래 한 줄 알림(예: 아직 못 보낸 기록). */
  note?: string | null;
}

export function ConfirmScreen({ kind, onStay, onLeave, speak = false, ttsRate, note }: ConfirmScreenProps) {
  const titleId = useId();
  const t = kind === "exit" ? COPY.confirm.exit : COPY.confirm.end;
  const body = kind === "exit" ? COPY.confirm.exit.body : null;
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // 화면 읽기 프로그램·키보드 사용자가 바로 질문과 [계속할래요]를 만나게 첫 버튼에 초점을 둔다.
    rootRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    if (speak) speakText(note ? `${t.title} ${note}` : t.title, { rate: ttsRate });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);

  return (
    <div
      ref={rootRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      data-testid="confirm-screen"
      data-kind={kind}
      className="fixed inset-0 z-50 flex flex-col items-center justify-center overflow-y-auto bg-worker-bg px-4 py-8 text-center font-worker text-worker-ink hc:bg-white hc:text-black"
    >
      <h1 id={titleId} className="text-worker-lg font-bold">{t.title}</h1>
      {body && <p className="mt-3 text-worker text-worker-ink-soft hc:text-black">{body}</p>}
      {note && (
        <p role="status" data-testid="confirm-note"
          className="mt-4 max-w-md rounded-worker-btn border-2 border-worker-caution-ink bg-worker-caution px-4 py-2 text-worker font-semibold text-worker-caution-ink hc:border-black hc:bg-white hc:text-black">
          {note}
        </p>
      )}
      <div className="mt-10 flex w-full max-w-sm flex-col gap-6">
        <PrimaryAction icon={IconPlay} onPress={onStay} className="w-full">
          {t.stay}
        </PrimaryAction>
        <SecondaryAction icon={kind === "exit" ? IconStop : IconEnd} onPress={onLeave} className="w-full">
          {t.leave}
        </SecondaryAction>
      </div>
    </div>
  );
}
