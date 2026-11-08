// 사업주 화면 도움 요청 띠(명세 5.2-2를 1차 크기로, 창업자 결정 6). 근로자가 [도와주세요]를 누르면
// 사업주 화면 맨 위(머리글 아래)에 5초 안에 뜬다. 요청이 없으면 아무것도 그리지 않는다.
// - 5초마다 GET /api/employer/help?state=active. 숨은 탭에서는 멈추고, 다시 보이면 바로 한 번 부른다.
// - 늦게 온 응답(앞서 보낸 요청의 응답이 뒤에 도착)은 버린다 — 이미 닫은 요청이 다시 나타나지 않게.
// - 불러오기에 실패하면(서버가 아직 이 API를 모름·잠깐 끊김) 띠를 조용히 두고 다음 차례에 다시 부른다.
// TODO(결정 6): 웹 푸시 — 사업주가 이 화면을 안 보고 있을 때도 알리려면 서비스 워커 구독 + 서버
//   notify_help_opened()에서 보낸다(2차). 그때도 이 띠는 그대로 둔다(화면을 보고 있을 때의 알림).
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type EmployerHelp } from "../api";
import { cn } from "../cn";
import { IconHelp } from "../ui/icons";
import { relativeTime } from "./helpTime";

export const HELP_POLL_MS = 5_000;
const MAX_SHOWN = 3;

export default function HelpAlertStrip() {
  const [items, setItems] = useState<EmployerHelp[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const list = await api.employerHelp("active");
      if (mine !== seq.current) return; // 더 나중에 보낸 요청이 있다: 이 응답은 낡았다.
      setItems(Array.isArray(list) ? list : []);
    } catch {
      /* 다음 차례에 다시 부른다(위 주석) */
    }
  }, []);

  useEffect(() => {
    let timer: number | undefined;
    const start = () => {
      if (timer !== undefined) return;
      void load();
      timer = window.setInterval(() => void load(), HELP_POLL_MS);
    };
    const stop = () => {
      if (timer !== undefined) window.clearInterval(timer);
      timer = undefined;
    };
    const onVisibility = () => (document.visibilityState === "hidden" ? stop() : start());
    const seqRef = seq; // 정리 함수에서 쓸 ref(같은 객체)
    if (document.visibilityState !== "hidden") start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
      seqRef.current++; // 화면을 떠난 뒤 도착한 응답은 버린다.
    };
  }, [load]);

  async function act(h: EmployerHelp, kind: "ack" | "resolve") {
    setBusyId(h.id);
    setActionError(null);
    try {
      if (kind === "ack") await api.ackHelp(h.id);
      else await api.resolveHelp(h.id);
      // 바로 화면에 반영하고(도와줬어요는 목록에서 뺌), 서버 목록으로 다시 맞춘다.
      setItems((cur) =>
        kind === "resolve"
          ? cur.filter((x) => x.id !== h.id)
          : cur.map((x) => (x.id === h.id ? { ...x, state: "acknowledged" } : x)),
      );
      void load();
    } catch (e) {
      // 근로자가 이미 취소한 요청(409) 같은 서버 문장은 사업주에게 그대로 보여 준다.
      setActionError(e instanceof Error ? e.message : "처리하지 못했어요. 다시 눌러 주세요.");
      void load();
    } finally {
      setBusyId(null);
    }
  }

  if (items.length === 0) return null;
  const shown = items.slice(0, MAX_SHOWN);
  const rest = items.length - shown.length;

  return (
    <div role="status" aria-live="polite" data-testid="help-alert-strip" className="border-b border-warn-line/30 bg-warn-50">
      <div className="mx-auto max-w-6xl px-4 py-2 md:px-8">
        <ul className="divide-y divide-warn-line/20">
          {shown.map((h) => (
            <li key={h.id} className="flex flex-wrap items-center gap-3 border-l-4 border-warn-line py-2 pl-3">
              <IconHelp size={20} strokeWidth={2} className="text-warn-700" />
              <p className="min-w-0 flex-1 text-sm text-ink-900">
                <strong className="font-bold">{h.worker_name}</strong> 님이 도움을 요청했어요
                <span className="text-ink-700">
                  {" · "}
                  {h.task_title}
                  {h.step_order != null && ` ${h.step_order}단계`}
                  {" · "}
                  <span className="tabular-nums">{relativeTime(h.created_at)}</span>
                </span>
                {h.state === "acknowledged" && (
                  <span className="ml-2 inline-block rounded-full bg-white px-2 text-xs font-semibold text-warn-700">확인함</span>
                )}
              </p>
              <div className="flex shrink-0 gap-2">
                {h.state === "open" && (
                  <button
                    type="button"
                    onClick={() => act(h, "ack")}
                    disabled={busyId === h.id}
                    className="rounded-md border border-line-strong bg-white px-3 py-1.5 text-sm font-semibold text-ink-900 hover:bg-paper-100 disabled:opacity-50"
                  >
                    확인했어요
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => act(h, "resolve")}
                  disabled={busyId === h.id}
                  className={cn(
                    "rounded-md bg-moss-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-moss-700 disabled:opacity-50",
                  )}
                >
                  도와줬어요
                </button>
              </div>
            </li>
          ))}
        </ul>
        {rest > 0 && <p className="py-1 pl-4 text-xs font-semibold text-warn-700">그 외 {rest}건</p>}
        {actionError && (
          <p role="alert" className="py-1 pl-4 text-sm text-danger-700">
            {actionError}
          </p>
        )}
      </div>
    </div>
  );
}
