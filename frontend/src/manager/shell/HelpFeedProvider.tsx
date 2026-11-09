// AppShell 안에서 도움 요청 폴링을 한 번만 돌린다(useHelpFeed.ts 주석). 띠와 종은 useHelpFeed로 읽는다.
import { useMemo, type ReactNode } from "react";
import { HelpFeedContext, useHelpFeedPoll } from "./useHelpFeed";

export default function HelpFeedProvider({ children }: { children: ReactNode }) {
  const { items, reload, setItems } = useHelpFeedPoll(true);
  const value = useMemo(() => ({ items, reload, setItems }), [items, reload, setItems]);
  return <HelpFeedContext.Provider value={value}>{children}</HelpFeedContext.Provider>;
}
