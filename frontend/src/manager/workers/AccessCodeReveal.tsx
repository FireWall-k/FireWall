// 접속 코드 가림(명세 5.7): 늘 ●●●●로 가리고, 눈 단추를 누르면 서버에서 받아(reveal, 볼 때마다 감사 기록) 5초 보여 준 뒤
// 다시 가린다. 보이는 동안 다시 누르면 바로 가린다. 너무 자주 열면(분당 10번) 서버 문장을 오류 토스트로 보인다.
import { useEffect, useRef, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { IconButton, useToast } from "../../components/ui";
import { cn } from "../../cn";
import { accessCode } from "../copy";
import { revealAccessCode } from "../api/workers";
import { errorMessage } from "../tasks/listHelpers";
import { REVEAL_MS, maskedCode } from "./helpers";

export interface AccessCodeRevealProps {
  workerId: string;
  name: string;
  length: number;
  /** 큰 글씨(상세 '접속 코드' 탭). */
  large?: boolean;
}

export default function AccessCodeReveal({ workerId, name, length, large = false }: AccessCodeRevealProps) {
  const toast = useToast();
  const [code, setCode] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  function hide() {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
    setCode(null);
  }

  async function toggle() {
    if (code !== null) {
      hide();
      return;
    }
    setBusy(true);
    try {
      const r = await revealAccessCode(workerId);
      setCode(r.code);
      timer.current = window.setTimeout(() => {
        timer.current = null;
        setCode(null);
      }, REVEAL_MS);
    } catch (e) {
      toast.show({ tone: "error", message: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  }

  const shown = code !== null;
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap">
      <span
        data-testid="access-code"
        className={cn("font-semibold tabular-nums text-ink-900", large ? "text-ui-xl tracking-[0.3em]" : "tracking-[0.2em]")}
      >
        {shown ? code : maskedCode(length)}
      </span>
      {/* 화면 읽기 프로그램에 보인 번호를 알린다(가리면 비움). */}
      <span className="sr-only" aria-live="polite">
        {shown ? code!.split("").join(" ") : ""}
      </span>
      <IconButton
        aria-label={shown ? accessCode.hide(name) : accessCode.show(name)}
        aria-pressed={shown}
        aria-busy={busy || undefined}
        icon={shown ? <EyeOff size={18} strokeWidth={2} aria-hidden="true" /> : <Eye size={18} strokeWidth={2} aria-hidden="true" />}
        onClick={() => {
          if (!busy) void toggle();
        }}
      />
    </span>
  );
}
