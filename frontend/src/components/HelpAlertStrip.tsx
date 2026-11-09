// 사업주 화면 도움 요청 띠(명세 5.2-2를 1차 크기로, 창업자 결정 6). 근로자가 [도와주세요]를 누르면
// 사업주 화면 맨 위(상단 바 아래)에 5초 안에 뜬다. 요청이 없으면 아무것도 그리지 않는다.
// 목록은 useHelpFeed(manager/shell)가 준다: AppShell 안에서는 상단 바 종과 같은 폴링 하나를 나눠 쓰고
// (같은 주소를 두 번 부르지 않음, contract §2.2), 밖에서 혼자 쓰면 스스로 5초마다 부른다.
// 폴링 규칙(숨은 탭 정지·늦은 응답 버림·실패 시 그대로 둠)은 useHelpFeed.ts에 있다.
// TODO(결정 6): 웹 푸시 — 사업주가 이 화면을 안 보고 있을 때도 알리려면 서비스 워커 구독 + 서버
//   notify_help_opened()에서 보낸다(2c). 그때도 이 띠는 그대로 둔다(화면을 보고 있을 때의 알림).
import { useState } from "react";
import { api, type EmployerHelp } from "../api";
import { buttonClasses } from "./ui/styles";
import { HELP_FEED_POLL_MS, useHelpFeed } from "../manager/shell/useHelpFeed";
import { IconHelp } from "../ui/icons";
import { relativeTime } from "./helpTime";

export const HELP_POLL_MS = HELP_FEED_POLL_MS;
const MAX_SHOWN = 3;

export default function HelpAlertStrip() {
  const { items, setItems, reload: load } = useHelpFeed();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

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
            // 휴대폰(768 미만): 버튼 줄을 글 아래로 내려 글이 좁은 칸에 여러 줄로 꺾이지 않게 한다(명세 8.2).
            <li key={h.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 border-l-4 border-warn-line py-2 pl-3">
              <IconHelp size={20} strokeWidth={2} className="text-warn-700" />
              <p className="min-w-0 flex-1 text-sm text-ink-900">
                <strong className="font-bold">{h.worker_name}</strong> 님이 도움을 요청했어요
                <span className="text-ink-700">
                  {" · "}
                  {h.task_title}
                  {h.step_order != null && ` ${h.step_order}단계`}
                  {" · "}
                  <span className="whitespace-nowrap tabular-nums">{relativeTime(h.created_at)}</span>
                </span>
                {h.state === "acknowledged" && (
                  <span className="ml-2 inline-block rounded-full bg-white px-2 text-xs font-semibold text-warn-700">확인함</span>
                )}
              </p>
              {/* 버튼은 공통 부품 크기(32, 손가락 기기 44 — 사업주 휴대폰에서도 도움 응대, 명세 6.3·8.2). */}
              <div className="flex w-full shrink-0 gap-2 pl-8 md:w-auto md:pl-0">
                {h.state === "open" && (
                  <button
                    type="button"
                    onClick={() => act(h, "ack")}
                    disabled={busyId === h.id}
                    className={buttonClasses("secondary", "sm")}
                  >
                    확인했어요
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => act(h, "resolve")}
                  disabled={busyId === h.id}
                  className={buttonClasses("primary", "sm")}
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
