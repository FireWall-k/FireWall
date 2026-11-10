// 도움 요청 띠(명세 5.2-2, contract §5.2). 모든 /m 화면 맨 위(상단 바 아래)에 요청이 있을 때만 보인다.
// 목록은 LiveProvider(오늘 현황 폴링 하나)가 준다 — 상단 바 종과 같은 목록.
// - '김민지 님이 도움을 요청했어요 · 컵 씻기 3단계 · 방금', 단계 썸네일 40.
// - [보러 가기](오늘 기록 서랍) · [이 단계 고치기](편집기 그 단계로 1번) · [도와줬어요](주). [확인했어요]는 보조로 남긴다
//   (근로자 화면에 '선생님이 확인했어요'가 뜬다). 확인했지만 아직 해결 전이면 '도움 가는 중'.
// - 최대 3건, 나머지는 '그 외 N건'. 768 미만에서는 [이 단계 고치기]·[확인했어요]가 … 메뉴로 들어간다.
// 웹 푸시(화면을 안 보고 있을 때)는 서버가 따로 보낸다. 이 띠는 화면을 보고 있을 때의 알림이다.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Ellipsis } from "lucide-react";
import { api, type EmployerHelp } from "../../api";
import { Badge, Menu, buttonClasses, iconButtonClasses } from "../../components/ui";
import { cn } from "../../cn";
import { IconHelp } from "../../ui/icons";
import { helpBand as copy } from "../copy";
import { useLive } from "../shell/useLive";
import Thumb from "./Thumb";
import TimelineDrawer from "./TimelineDrawer";
import { agoText, editorLink } from "./time";

export const HELP_BAND_MAX = 3;

export default function HelpBand() {
  const { help, markHelp, reload, now } = useLive();
  const navigate = useNavigate();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<{ id: string; name: string } | null>(null);

  async function act(h: EmployerHelp, kind: "ack" | "resolve") {
    setBusyId(h.id);
    setError(null);
    try {
      if (kind === "ack") await api.ackHelp(h.id);
      else await api.resolveHelp(h.id);
      markHelp(h.id, kind === "ack" ? "acknowledged" : "resolved");
      void reload();
      // 누른 버튼이 사라지면(도와줬어요) 초점이 body로 빠진다: 띠(남은 요청) 또는 본문으로 옮긴다.
      requestAnimationFrame(() => {
        const a = document.activeElement;
        if (a && a !== document.body && a.isConnected) return;
        (document.getElementById("help") ?? document.getElementById("main"))?.focus({ preventScroll: true });
      });
    } catch (e) {
      // 근로자가 이미 취소한 요청(409) 같은 서버 문장은 그대로 보여 준다.
      setError(e instanceof Error && e.message ? e.message : copy.actionFailed);
      void reload();
    } finally {
      setBusyId(null);
    }
  }

  const drawerEl = drawer ? <TimelineDrawer workerId={drawer.id} name={drawer.name} onClose={() => setDrawer(null)} /> : null;
  if (help.length === 0) return drawerEl;

  const shown = help.slice(0, HELP_BAND_MAX);
  const rest = help.length - shown.length;

  return (
    <section id="help" aria-label={copy.region} data-testid="help-band" tabIndex={-1} className="border-b border-warn-line/30 bg-warn-50 focus:outline-none">
      <div className="mx-auto max-w-page px-4 py-2 md:px-8">
        <ul className="divide-y divide-warn-line/20" aria-live="polite">
          {shown.map((h) => {
            const busy = busyId === h.id;
            const fixTo = editorLink(h.task_id, h.source_step_id);
            const thumb = h.step_thumb_url ?? h.step_symbol_url;
            return (
              <li key={h.id} data-testid="help-band-item" className="flex flex-wrap items-center gap-x-3 gap-y-2 border-l-4 border-warn-line py-2 pl-3">
                <IconHelp size={20} strokeWidth={2} className="shrink-0 text-warn-700" />
                {h.step_order != null && <Thumb url={thumb} className="hidden sm:flex" />}
                <p className="min-w-0 flex-1 text-ui-base text-ink-900">
                  <strong className="font-bold">{h.worker_name}</strong> {copy.requested}
                  <span className="text-ink-700">
                    {" · "}
                    {h.task_title}
                    {h.step_order != null && ` ${copy.stepOf(h.step_order)}`}
                    {" · "}
                    <span className="whitespace-nowrap tabular-nums">{agoText(h.created_at, now)}</span>
                  </span>
                  {h.state === "acknowledged" && (
                    <Badge tone="info" className="ml-2 align-middle">
                      {copy.acked}
                    </Badge>
                  )}
                </p>
                <div className="flex w-full shrink-0 flex-wrap items-center gap-2 pl-8 md:w-auto md:pl-0">
                  <button type="button" className={buttonClasses("secondary", "sm")} onClick={() => setDrawer({ id: h.worker_id, name: h.worker_name })}>
                    {copy.seeMore}
                  </button>
                  <button type="button" className={buttonClasses("secondary", "sm", "hidden md:inline-flex")} onClick={() => navigate(fixTo)}>
                    {copy.fixStep}
                  </button>
                  {h.state === "open" && (
                    <button type="button" disabled={busy} className={buttonClasses("ghost", "sm", "hidden md:inline-flex")} onClick={() => void act(h, "ack")}>
                      {copy.ack}
                    </button>
                  )}
                  <button type="button" disabled={busy} className={buttonClasses("primary", "sm")} onClick={() => void act(h, "resolve")}>
                    {copy.resolve}
                  </button>
                  <div className="md:hidden">
                    <Menu
                      label={copy.actionsMenu(h.worker_name)}
                      items={[
                        { id: "fix", label: copy.fixStep, onSelect: () => navigate(fixTo) },
                        ...(h.state === "open" ? [{ id: "ack", label: copy.ack, disabled: busy, onSelect: () => void act(h, "ack") }] : []),
                      ]}
                      trigger={(p) => (
                        <button {...p} type="button" aria-label={copy.actionsMenu(h.worker_name)} className={cn(iconButtonClasses("ghost"))}>
                          <Ellipsis size={20} strokeWidth={2} aria-hidden="true" />
                        </button>
                      )}
                    />
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
        {rest > 0 && <p className="py-1 pl-4 text-ui-sm font-semibold text-warn-700">{copy.more(rest)}</p>}
        {error && (
          <p role="alert" className="py-1 pl-4 text-ui-sm text-danger-700">
            {error}
          </p>
        )}
      </div>
      {drawerEl}
    </section>
  );
}
