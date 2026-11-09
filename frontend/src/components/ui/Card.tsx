// 카드(명세 5.0): 흰 바탕, 모서리 10, 1px paper-200, 그림자 sm.
import type { HTMLAttributes } from "react";
import { cn } from "../../cn";
import { cardClasses } from "./styles";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** 안쪽 여백. none은 표·목록을 카드 가장자리까지 붙일 때. */
  padding?: "none" | "md" | "lg";
}

export default function Card({ padding = "md", className, ...rest }: CardProps) {
  return <div className={cn(cardClasses, padding === "md" && "p-4", padding === "lg" && "p-6", className)} {...rest} />;
}
