// 도움 요청 목록 하나를 띠(HelpAlertStrip)와 상단 바 종(TopBar)이 같이 쓴다(contract §2.2).
// 같은 주소를 두 번 부르지 않도록 AppShell의 HelpFeedProvider가 5초 폴링을 한 번만 돌리고, 둘은 useHelpFeed로 읽는다.
// - 5초마다 GET /api/employer/help?state=active. 숨은 탭에서는 멈추고, 다시 보이면 바로 한 번 부른다.
// - 늦게 온 응답(앞서 보낸 요청의 응답이 뒤에 도착)은 버린다 — 이미 닫은 요청이 다시 나타나지 않게.
// - 불러오기에 실패하면(잠깐 끊김) 목록을 그대로 두고 다음 차례에 다시 부른다.
// Provider 밖(옛 화면 단독 시험)에서 useHelpFeed를 부르면 그 자리에서 직접 폴링한다 — 띠 혼자서도 동작한다.
// 2c에서 LiveProvider(/api/employer/live)가 이 자리를 대신한다.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { api, type EmployerHelp } from "../../api";

export const HELP_FEED_POLL_MS = 5_000;

export interface HelpFeed {
  items: EmployerHelp[];
  /** 지금 바로 다시 부른다(처리 뒤 서버 목록과 맞출 때). */
  reload: () => Promise<void>;
  /** 화면에 먼저 반영할 때(낙관적 갱신). 다음 불러오기가 서버 목록으로 덮는다. */
  setItems: Dispatch<SetStateAction<EmployerHelp[]>>;
}

export const HelpFeedContext = createContext<HelpFeed | null>(null);

/** 폴링 본체. enabled=false면 부르지 않는다(Provider 안에서 띠가 따로 부르지 않게). */
export function useHelpFeedPoll(enabled: boolean): HelpFeed {
  const [items, setItems] = useState<EmployerHelp[]>([]);
  const seq = useRef(0);

  const reload = useCallback(async () => {
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
    if (!enabled) return;
    let timer: number | undefined;
    const start = () => {
      if (timer !== undefined) return;
      void reload();
      timer = window.setInterval(() => void reload(), HELP_FEED_POLL_MS);
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
  }, [enabled, reload]);

  return { items, reload, setItems };
}

/** 띠·종이 쓰는 도움 요청 목록. Provider 안이면 공용 폴링을, 밖이면 스스로 폴링한다. */
export function useHelpFeed(): HelpFeed {
  const shared = useContext(HelpFeedContext);
  const own = useHelpFeedPoll(shared === null);
  return shared ?? own;
}
