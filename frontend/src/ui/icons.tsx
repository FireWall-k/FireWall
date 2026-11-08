// 근로자·사업주 화면 공통 아이콘(명세 6.4). lucide-react 한 벌만 쓰고, 뜻을 이름으로 고정한다
// (←는 나가기, 손은 도와주세요, 스피커는 듣기, 체크는 다 했어요, 세모는 조심, 와이파이 끊김은 인터넷).
// 화면 코드는 lucide 이름 대신 여기 이름을 쓴다 — 같은 뜻에 다른 그림이 섞이지 않게.
// 이모지는 쓰지 않는다(기기마다 그림이 달라 근로자가 같은 뜻으로 알아보기 어렵다).
// 근로자 기본값: 32px, 굵기 2.5. 늘 글자 라벨과 함께 두므로 화면 읽기 프로그램에는 숨긴다(aria-hidden).
import {
  ArrowLeft,
  Check,
  ChevronLeft,
  ChevronRight,
  Delete,
  DoorOpen,
  Eye,
  EyeOff,
  Hand,
  History,
  House,
  LoaderCircle,
  Play,
  RotateCw,
  Square,
  TriangleAlert,
  Undo2,
  Volume2,
  WifiOff,
  X,
  type LucideIcon,
} from "lucide-react";
import { cn } from "../cn";

export interface IconProps {
  size?: number;
  className?: string;
  /** 굵기. 근로자 2.5(기본), 사업주 화면은 2를 넘긴다. */
  strokeWidth?: number;
}

function make(Glyph: LucideIcon, name: string, extraClass?: string) {
  function Icon({ size = 32, className, strokeWidth = 2.5 }: IconProps) {
    return (
      <Glyph
        size={size}
        strokeWidth={strokeWidth}
        aria-hidden="true"
        focusable="false"
        className={cn("shrink-0", extraClass, className)}
      />
    );
  }
  Icon.displayName = name;
  return Icon;
}

export const IconExit = make(ArrowLeft, "IconExit");
export const IconHelp = make(Hand, "IconHelp");
export const IconSpeak = make(Volume2, "IconSpeak");
export const IconStop = make(Square, "IconStop");
/** 도움 요청 [취소](되돌리기 화살표). 네모(멈춤)는 소리 멈춤 전용으로 둔다 — 한 화면에 같은 그림이 두 뜻으로 섞였다(1차 검증). */
export const IconCancel = make(Undo2, "IconCancel");
export const IconDone = make(Check, "IconDone");
export const IconCaution = make(TriangleAlert, "IconCaution");
export const IconOffline = make(WifiOff, "IconOffline");
export const IconPrev = make(ChevronLeft, "IconPrev");
export const IconNext = make(ChevronRight, "IconNext");
export const IconPlay = make(Play, "IconPlay");
export const IconHome = make(House, "IconHome");
export const IconEnd = make(DoorOpen, "IconEnd");
export const IconHistory = make(History, "IconHistory");
export const IconBackspace = make(Delete, "IconBackspace");
export const IconClear = make(X, "IconClear");
export const IconRetry = make(RotateCw, "IconRetry");
// 들어가는 중. 움직임 줄이기를 켠 기기에서는 돌지 않는다(motion-reduce).
export const IconSpinner = make(LoaderCircle, "IconSpinner", "animate-spin motion-reduce:animate-none");
export const IconShow = make(Eye, "IconShow");
export const IconHide = make(EyeOff, "IconHide");
