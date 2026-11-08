// 도움 요청 버튼과 띠(명세 4.5 + 창업자 결정 8, 7.1 HelpButton·HelpBanner).
// 띠 문구는 상태를 사실대로: 부르는 중 / 불렀어요(+[취소]) / 아직 못 불렀어요(+[다시 부르기]) / 선생님이 확인했어요.
// '불렀어요' 띠는 문장과 [취소]를 한 줄 가로로 둔다: 문장은 왼쪽에서 줄을 바꿔도 되고, [취소]는 오른쪽에
// 붙어 글자가 줄을 바꾸지 않는다(결정 8).
import { cn } from "../cn";
import { IconCancel, IconHelp } from "../ui/icons";
import { COPY } from "./copy";
import type { HelpPhase } from "./hooks/useHelp";
import { SecondaryAction } from "./ui/WorkerButton";
import { Band } from "./WorkerScreen";

/** 위 띠 오른쪽 [도와주세요] 160×80. 바탕 help, 3px help-line 테두리. 부른 뒤에는 '불렀어요'(aria-pressed). */
export function HelpButton({ phase, onPress }: { phase: HelpPhase; onPress: () => void }) {
  const label = phase === "sending" ? COPY.help.btnSending : phase === "sent" ? COPY.help.btnSent : COPY.btn.help;
  const pressed = phase === "sending" || phase === "sent";
  return (
    <button
      type="button"
      onClick={onPress}
      aria-pressed={pressed}
      data-testid="help-button"
      className={cn(
        "inline-flex min-h-touch min-w-[160px] select-none items-center justify-center gap-2 whitespace-nowrap rounded-worker-btn bg-worker-help px-3 text-worker font-bold text-worker-help-ink small:min-w-0",
        // 좁은 위 띠(글자를 키운 360·390 폭): 손 아이콘을 글자 위로 올려 폭을 줄인다(글자 크기는 그대로, 4차 검증).
        "topnarrow:min-w-0 topnarrow:flex-col topnarrow:gap-0 topnarrow:px-2 topnarrow:leading-tight",
        pressed ? "border-4 border-worker-help-ink" : "border-[3px] border-worker-help-line",
        "hc:border-black hc:bg-white hc:text-black",
      )}
    >
      <IconHelp size={28} />
      <span>{label}</span>
    </button>
  );
}

export function HelpBanner({ phase, onCancel, onRetry }: { phase: HelpPhase; onCancel: () => void; onRetry: () => void }) {
  if (phase === "idle") return null;
  if (phase === "sending") {
    return (
      <Band tone="help" testId="help-band">
        <IconHelp size={28} />
        <p className="min-w-0 flex-1">{COPY.help.sending}</p>
      </Band>
    );
  }
  if (phase === "sent") {
    return (
      <Band tone="help" testId="help-band" spaced>
        {/* 결정 8: 문장 왼쪽(flex-1, 줄바꿈 가능) · [취소] 오른쪽(줄바꿈 없음, 줄지 않음) 한 줄. */}
        <p data-testid="help-band-text" className="min-w-0 flex-1">{COPY.help.sent}</p>
        <SecondaryAction icon={IconCancel} onPress={onCancel} className="shrink-0 !gap-2 !px-4">
          {COPY.btn.cancel}
        </SecondaryAction>
      </Band>
    );
  }
  if (phase === "failed") {
    return (
      <Band tone="help" testId="help-band" spaced>
        {/* 좁은 휴대폰에서 문장 자리를 넓히려고 왼쪽 아이콘과 버튼 아이콘을 뺐다. */}
        <p data-testid="help-band-text" className="min-w-0 flex-1">{COPY.help.failed}</p>
        <SecondaryAction onPress={onRetry} className="shrink-0 !px-4">
          {COPY.btn.recall}
        </SecondaryAction>
      </Band>
    );
  }
  return (
    <Band tone="help" testId="help-band">
      <IconHelp size={28} />
      <p className="min-w-0 flex-1">{COPY.help.acked}</p>
    </Band>
  );
}
