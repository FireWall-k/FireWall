// 단계 썸네일(40 / 96). 그림이 없거나 못 불러오면 '그림 없음' 아이콘.
import { useState } from "react";
import { ImageOff } from "lucide-react";
import { cn } from "../../cn";

export default function Thumb({ url, size = 40, className }: { url: string | null | undefined; size?: 40 | 96; className?: string }) {
  const [failed, setFailed] = useState<string | null>(null);
  const ok = !!url && failed !== url;
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center overflow-hidden rounded-control border border-paper-200 bg-white",
        size === 40 ? "size-10" : "size-24",
        className,
      )}
    >
      {ok ? (
        <img src={url} alt="" loading="lazy" className="size-full object-contain" onError={() => setFailed(url)} />
      ) : (
        <ImageOff size={size === 40 ? 16 : 28} strokeWidth={2} aria-hidden="true" className="text-ink-500" />
      )}
    </span>
  );
}
