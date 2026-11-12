// AppShell 안에서 오늘 현황 폴링을 한 번만 돌린다(규칙은 useLive.ts 주석). 옛 HelpFeedProvider를 대신한다.
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../../api";
import { getLive } from "../api/live";
import type { LiveOut } from "../api/types";
import { LIVE_POLL_MS, LOCAL_HELP_MS, LiveContext, type LiveFeed, type LocalHelpAction } from "./useLive";

function parseUtc(iso: string): number {
  return Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
}

export default function LiveProvider({ children, enabled = true }: { children: ReactNode; enabled?: boolean }) {
  const [data, setData] = useState<LiveOut | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [disconnected, setDisconnected] = useState(false);
  const [now, setNow] = useState(0);
  const [local, setLocal] = useState<Record<string, { action: LocalHelpAction; until: number }>>({});
  const seq = useRef(0);

  const reload = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const out = await getLive();
      if (mine !== seq.current) return; // 더 나중에 보낸 요청이 있다: 이 응답은 낡았다.
      const got = Date.now();
      setData(out);
      setUpdatedAt(got);
      setDisconnected(false);
      const server = parseUtc(out.server_now);
      setNow(Number.isNaN(server) ? got : server);
      // 덮어 둔 결과는 시간이 지나면 버린다(서버 답이 따라잡았다).
      setLocal((cur) => {
        const keep = Object.entries(cur).filter(([, v]) => v.until > got);
        return keep.length === Object.keys(cur).length ? cur : Object.fromEntries(keep);
      });
    } catch (e) {
      if (mine !== seq.current) return;
      // 429는 '잠깐 뒤에' — 끊김이 아니다. 다음 주기에 다시 부른다.
      if (e instanceof ApiError && e.status === 429) return;
      setDisconnected(true);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let timer: number | undefined;
    const start = () => {
      if (timer !== undefined) return;
      void reload();
      timer = window.setInterval(() => void reload(), LIVE_POLL_MS);
    };
    const stop = () => {
      if (timer !== undefined) window.clearInterval(timer);
      timer = undefined;
    };
    const onVisibility = () => (document.visibilityState === "hidden" ? stop() : start());
    const seqRef = seq;
    if (document.visibilityState !== "hidden") start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
      seqRef.current++; // 떠난 뒤 도착한 응답은 버린다.
    };
  }, [enabled, reload]);

  const markHelp = useCallback((id: string, action: LocalHelpAction) => {
    setLocal((cur) => ({ ...cur, [id]: { action, until: Date.now() + LOCAL_HELP_MS } }));
  }, []);

  const help = useMemo(() => {
    const list = data?.help ?? [];
    // 버리는 것은 응답을 받을 때 한다(위 reload). 여기서는 남은 덮개를 그대로 쓴다.
    return list
      .filter((h) => local[h.id]?.action !== "resolved")
      .map((h) => (local[h.id]?.action === "acknowledged" && h.state === "open" ? { ...h, state: "acknowledged" as const } : h));
  }, [data, local]);

  const value = useMemo<LiveFeed>(
    () => ({ data, help, updatedAt, disconnected, now, reload, markHelp }),
    [data, help, updatedAt, disconnected, now, reload, markHelp],
  );
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}
