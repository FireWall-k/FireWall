// 번호 넣기(/worker, 명세 4.1 + 창업자 결정 3). 번호는 숫자 4자리, 4번째 숫자를 누르면 바로 들어간다
// ([들어가기] 버튼 없음). 키패드 3×4, 맨 아래 줄 [지우기][0][비우기]. 넣은 숫자는 가리지 않고 보여 준다
// (외우지 않아도 확인하며 누를 수 있게, WCAG 3.3.8).
// 틀리면 '번호가 맞지 않아요. 다시 눌러 봐요.'(소리로도) + 칸을 비운다. 3번째부터 '(호칭)께 번호를 물어봐요.'.
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
/** 몇 번째 틀림부터 '(호칭)께 번호를 물어봐요.'를 덧붙이는지. */
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
              "flex h-16 w-[52px] items-center justify-center rounded-worker-btn bg-worker-card text-[2rem] font-bold tabular-nums small:h-14",
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

// 키 높이는 키패드 칸(grid 행)이 정한다: 행마다 64px 이상, 남는 높이를 나눠 갖는다(작은 휴대폰·가로 화면에서도
// 4줄이 다 보이게, 1차 검증 지적). 키 자체에는 고정 높이를 두지 않는다.
const keyClass = cn(
  "flex h-full min-h-0 select-none items-center justify-center rounded-worker-btn border-2 border-worker-line bg-worker-card font-bold text-worker-ink",
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
    <div
      className="mx-auto grid h-full max-h-[26rem] w-full max-w-sm grid-cols-3 grid-rows-[repeat(4,minmax(64px,1fr))] gap-3 small:gap-2 tablet:max-h-[30rem]"
      data-testid="keypad"
    >
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
        navigate("/worker/today", { replace: true });
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
    return <StatusScreen kind="unpaired" speak onSecondary={() => navigate("/worker/setup")} />;
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

  // 틀림·너무 많음 안내는 제목과 번호 칸 자리에 대신 나온다(칸은 이미 비워졌고, 첫 숫자를 누르면 다시 제목과
  // 칸이 나온다). 안내가 세 줄로 늘어도 키패드를 밀어내지 않게 하려는 것이다(1차 검증: 360×640에서 맨 아래 줄이
  // 화면 밖). 키패드만 남는 높이에 맞춰 늘고 준다.
  return (
    <WorkerScreen
      testId="entry-screen"
      top={
        // 낮은 화면(620 이하: 360×560, 가로 휴대폰)은 위 띠를 빼고 사업장 이름을 번호 칸 위로 옮긴다 — 키패드 키가
        // 80px 아래로 줄지 않게(명세 4.0·4.1, 2차 검증: 위 띠가 있으면 69~71px이었다).
        <div className="contents [@media(max-height:620px)]:hidden">
          <TopBar
            left={
              workplaceName ? (
                <p className="truncate text-worker-caption text-worker-ink-soft hc:text-black">{workplaceName}</p>
              ) : undefined
            }
          />
        </div>
      }
      mainClassName="items-center gap-4 overflow-hidden py-4 small:gap-2 small:py-2 land:grid land:grid-cols-2 land:grid-rows-[minmax(0,1fr)_auto] land:items-stretch land:gap-x-6 land:gap-y-2"
    >
      <div
        data-testid="entry-slot"
        className="flex min-h-[7.5rem] w-full max-w-sm flex-col items-center justify-center gap-3 small:min-h-[6.25rem] small:gap-2 land:col-start-1 land:row-start-1 land:max-w-none"
      >
        {workplaceName && (
          <p data-testid="entry-workplace-inline"
            className="hidden max-w-full truncate text-worker-caption text-worker-ink-soft hc:text-black [@media(max-height:620px)]:block">
            {workplaceName}
          </p>
        )}
        {!busy && message ? (
          <div role="alert" data-testid="login-notice"
            className="flex w-full items-start gap-2 rounded-worker-btn border-2 border-worker-caution-ink bg-worker-caution px-4 py-2 text-worker font-semibold leading-snug text-worker-caution-ink small:gap-1.5 small:px-2 small:py-1 hc:border-black hc:bg-white hc:text-black">
            {/* 글씨는 작은 화면에서도 24px(명세 4.1, 3차 검증). 자리가 모자라면 아이콘·여백을 줄인다. */}
            <IconCaution size={28} className="mt-0.5 shrink-0 small:size-6" />
            <div>
              {message.map((m) => (
                <p key={m}>{m}</p>
              ))}
            </div>
          </div>
        ) : (
          <>
            {busy ? (
              <p role="status" className="flex items-center gap-2 text-worker font-semibold text-worker-ink-soft">
                <IconSpinner size={28} />
                {COPY.login.entering}
              </p>
            ) : (
              <h1 className="text-center text-worker-lg font-bold small:text-worker-title">{COPY.login.title}</h1>
            )}
            <CodeBoxes digits={digits} busy={busy} />
          </>
        )}
      </div>
      {/* 화면 읽기 프로그램용: 넣은 자릿수(숫자는 화면에 보이므로 그대로 읽는다). */}
      <p className="sr-only" aria-live="polite">{digits.split("").join(" ")}</p>
      <div className="flex min-h-[calc(256px+2.25rem)] w-full flex-1 !shrink items-center justify-center small:min-h-[calc(256px+1.5rem)] land:col-start-2 land:row-span-2 land:row-start-1">
        <Keypad
          disabled={busy}
          onDigit={onDigit}
          onBackspace={() => setDigits((d) => d.slice(0, -1))}
          onClear={() => setDigits("")}
        />
      </div>
      {/* 사업주만 쓰는 작은 링크(근로자가 우연히 누르지 않게 작게). 예전 5자리 이상 번호용.
          세로 화면은 키패드 아래, 가로 화면은 왼쪽 칸 아래.
          4차 검증: 높이가 모자라면(글자 130% + 세 번 틀림 안내 네 줄) 키패드가 제 칸을 넘쳐 이 링크가 맨 아랫줄
          [지우기][0][비우기] 위에 겹쳤다 — 0을 누르려다 링크를 누를 수 있었다. 이제 키패드 칸은 키패드 최소 높이(64px ×
          4줄 + 틈) 아래로 줄지 않고, 모자라면 링크 칸이 가장 먼저 줄어(shrink 1000) 잘려 사라진다. 키패드와 겹치지 않는다. */}
      <div className="flex min-h-0 w-full !shrink-[1000] justify-center overflow-hidden land:col-start-1 land:row-start-2">
        <button
          type="button"
          data-teacher-only=""
          onClick={() => navigate("/login?tab=worker")}
          className="min-h-11 max-w-full shrink-0 rounded-worker-btn px-4 text-worker-caption leading-tight text-worker-ink-soft underline underline-offset-4 hc:text-black [@media(max-height:620px)]:min-h-9"
        >
          {COPY.btn.teacherLongCode}
        </button>
      </div>
    </WorkerScreen>
  );
}
