// 번호 넣기(/w, 명세 4.1 + 창업자 결정 3). 번호는 숫자 4자리, 4번째 숫자를 누르면 바로 들어간다
// ([들어가기] 버튼 없음). 키패드 3×4, 맨 아래 줄 [지우기][0][비우기]. 넣은 숫자는 가리지 않고 보여 준다
// (외우지 않아도 확인하며 누를 수 있게, WCAG 3.3.8).
// 틀리면 '번호가 맞지 않아요. 다시 눌러 봐요.'(소리로도) + 칸을 비운다. 3번째부터 '선생님께 번호를 물어봐요.'.
// 시도가 너무 많으면(429) 서버가 잠시 막는다 — 그 문구를 보인다. 대입 방어는 서버 시도 제한이 맡는다.
// 예전 5자리 이상 번호는 키패드로 넣을 수 없다: 작은 보조 링크로 로그인 화면(근로자 탭)에 보낸다.
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { auth as authApi, type AuthState } from "../api";
import { cn } from "../cn";
import { getSavedWorkplaceCode, getSavedWorkplaceName } from "../workerCodes";
import { IconBackspace, IconCaution, IconClear, IconSpinner } from "../ui/icons";
import { COPY, toWorkerMessage } from "./copy";
import { speakText } from "./speech";
import { StatusScreen } from "./ui/StatusScreen";
import { TopBar, WorkerScreen } from "./WorkerScreen";

export const CODE_LENGTH = 4;
/** 몇 번째 틀림부터 '선생님께 번호를 물어봐요.'를 덧붙이는지. */
export const ASK_TEACHER_AFTER = 3;

type Notice = { kind: "wrong"; failures: number } | { kind: "too_many" } | null;

function CodeBoxes({ digits, busy }: { digits: string; busy: boolean }) {
  return (
    <div className="flex justify-center gap-3" aria-hidden="true" data-testid="code-boxes">
      {Array.from({ length: CODE_LENGTH }, (_, i) => {
        const current = !busy && i === digits.length;
        return (
          <span
            key={i}
            className={cn(
              "flex h-16 w-[52px] items-center justify-center rounded-worker-btn bg-worker-card text-[2rem] font-bold tabular-nums",
              current ? "border-[3px] border-worker-primary" : "border-2 border-worker-line",
              "hc:border-black",
            )}
          >
            {digits[i] ?? ""}
          </span>
        );
      })}
    </div>
  );
}

const keyClass = cn(
  "flex min-h-touch select-none items-center justify-center rounded-worker-btn border-2 border-worker-line bg-worker-card font-bold text-worker-ink tablet:min-h-24",
  "active:bg-worker-line-soft disabled:cursor-not-allowed disabled:opacity-50 hc:border-black",
);

function Keypad({ disabled, onDigit, onBackspace, onClear }: {
  disabled: boolean;
  onDigit: (d: string) => void;
  onBackspace: () => void;
  onClear: () => void;
}) {
  const digits = ["1", "2", "3", "4", "5", "6", "7", "8", "9"];
  return (
    <div className="mx-auto grid w-full max-w-sm grid-cols-3 gap-3" data-testid="keypad">
      {digits.map((d) => (
        <button key={d} type="button" disabled={disabled} onClick={() => onDigit(d)} className={cn(keyClass, "text-[2.25rem]")}>
          {d}
        </button>
      ))}
      <button type="button" disabled={disabled} onClick={onBackspace} className={cn(keyClass, "flex-col gap-0 text-worker-caption")}>
        <IconBackspace size={28} />
        <span>{COPY.key.backspace}</span>
      </button>
      <button type="button" disabled={disabled} onClick={() => onDigit("0")} className={cn(keyClass, "text-[2.25rem]")}>
        0
      </button>
      <button type="button" disabled={disabled} onClick={onClear} className={cn(keyClass, "flex-col gap-0 text-worker-caption")}>
        <IconClear size={28} />
        <span>{COPY.key.clear}</span>
      </button>
    </div>
  );
}

export default function EntryScreen({ onLogin }: { onLogin: (a: AuthState) => void }) {
  const navigate = useNavigate();
  const workplaceCode = getSavedWorkplaceCode();
  const workplaceName = getSavedWorkplaceName();
  const [digits, setDigits] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [failures, setFailures] = useState(0);
  const [fatal, setFatal] = useState<"offline" | "error" | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // 들어오면 제목을 한 번 읽는다.
  useEffect(() => {
    if (workplaceCode && !fatal) speakText(COPY.login.title);
  }, [workplaceCode, fatal]);

  const submit = useCallback(
    async (code: string) => {
      if (!workplaceCode) return;
      setBusy(true);
      try {
        const state = await authApi.loginWorker(workplaceCode, code);
        if (!alive.current) return;
        onLogin(state);
        navigate("/w/today", { replace: true });
      } catch (e) {
        if (!alive.current) return;
        setBusy(false);
        setDigits("");
        const kind = toWorkerMessage(e);
        if (kind === "offline") return setFatal("offline");
        if (kind === "too_many") {
          setNotice({ kind: "too_many" });
          speakText(COPY.login.tooMany);
          return;
        }
        if (kind === "error") return setFatal("error");
        // 401(번호 틀림)·그 밖(400·404·422): 번호가 맞지 않다고 알린다.
        const n = failures + 1;
        setFailures(n);
        setNotice({ kind: "wrong", failures: n });
        speakText(n >= ASK_TEACHER_AFTER ? `${COPY.login.wrong} ${COPY.login.askTeacher}` : COPY.login.wrong);
      }
    },
    [workplaceCode, failures, onLogin, navigate],
  );

  const onDigit = (d: string) => {
    if (busy || digits.length >= CODE_LENGTH) return;
    const next = digits + d;
    setDigits(next);
    if (next.length === 1) setNotice(null);
    // 4번째 숫자를 누르면 바로 들어간다(창업자 결정 3).
    if (next.length === CODE_LENGTH) void submit(next);
  };

  if (!workplaceCode) {
    return <StatusScreen kind="unpaired" speak onSecondary={() => navigate("/w/setup")} />;
  }
  if (fatal) {
    return <StatusScreen kind={fatal} speak onAction={() => setFatal(null)} />;
  }

  const message =
    notice?.kind === "too_many"
      ? [COPY.login.tooMany]
      : notice?.kind === "wrong"
        ? notice.failures >= ASK_TEACHER_AFTER
          ? [COPY.login.wrong, COPY.login.askTeacher]
          : [COPY.login.wrong]
        : null;

  return (
    <WorkerScreen
      testId="entry-screen"
      top={
        <TopBar
          left={
            workplaceName ? (
              <p className="truncate text-worker-caption text-worker-ink-soft hc:text-black">{workplaceName}</p>
            ) : undefined
          }
        />
      }
      mainClassName="items-center gap-4 py-4 small:gap-3 small:py-3"
    >
      <h1 className="text-center text-worker-lg font-bold">{COPY.login.title}</h1>
      <CodeBoxes digits={digits} busy={busy} />
      {/* 화면 읽기 프로그램용: 넣은 자릿수(숫자는 화면에 보이므로 그대로 읽는다). */}
      <p className="sr-only" aria-live="polite">{digits.split("").join(" ")}</p>
      <div className="flex min-h-12 w-full max-w-sm flex-col items-center justify-center">
        {busy && (
          <p role="status" className="flex items-center gap-2 text-worker font-semibold text-worker-ink-soft">
            <IconSpinner size={28} />
            {COPY.login.entering}
          </p>
        )}
        {!busy && message && (
          <div role="alert" data-testid="login-notice"
            className="flex w-full items-start gap-2 rounded-worker-btn border-2 border-worker-caution-ink bg-worker-caution px-4 py-2 text-worker font-semibold text-worker-caution-ink hc:border-black hc:bg-white hc:text-black">
            <IconCaution size={28} className="mt-1" />
            <div>
              {message.map((m) => (
                <p key={m}>{m}</p>
              ))}
            </div>
          </div>
        )}
      </div>
      <Keypad
        disabled={busy}
        onDigit={onDigit}
        onBackspace={() => setDigits((d) => d.slice(0, -1))}
        onClear={() => setDigits("")}
      />
      {/* 선생님만 쓰는 작은 링크(근로자가 우연히 누르지 않게 작게). 예전 5자리 이상 번호용. */}
      <button
        type="button"
        data-teacher-only=""
        onClick={() => navigate("/login?tab=worker")}
        className="mt-2 min-h-12 shrink-0 rounded-worker-btn px-4 text-worker-caption text-worker-ink-soft underline underline-offset-4 hc:text-black"
      >
        {COPY.btn.teacherLongCode}
      </button>
    </WorkerScreen>
  );
}
