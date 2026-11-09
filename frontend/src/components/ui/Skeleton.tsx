// 불러오는 중 자리(명세 7.3). 꾸밈이라 화면 읽기 프로그램에는 숨긴다 — '불러오는 중이에요'는 EmptyState가 알린다.
// 움직임 줄이기를 켠 기기에서는 깜빡이지 않는다.
import { cn } from "../../cn";

export default function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden="true" className={cn("block animate-pulse rounded-control bg-paper-200 motion-reduce:animate-none", className ?? "h-4 w-full")} />;
}
