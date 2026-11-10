// 편집기 머리의 제목(명세 5.5 '제목은 그 자리에서 고칩니다'). 화면 이름(h1)이기도 하다.
// [✎]를 누르면 칸이 열리고 Enter·칸 벗어나기로 저장, Esc로 그대로 둔다. 1~40자(서버 422 문구를 그대로 보인다).
import { useEffect, useRef, useState } from "react";
import { PencilLine } from "lucide-react";
import { IconButton } from "../../../components/ui";
import { inputClasses } from "../../../components/ui/styles";
import { cn } from "../../../cn";
import { editor as copy } from "../../copy";

export default function TitleEditor({ title, onSave }: { title: string; onSave: (title: string) => Promise<boolean> }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(title);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement | null>(null);
  const button = useRef<HTMLButtonElement | null>(null);
  const done = useRef(false);

  useEffect(() => {
    if (editing) input.current?.select();
  }, [editing]);

  function open() {
    setValue(title);
    done.current = false;
    setEditing(true);
  }

  async function finish(save: boolean) {
    if (done.current) return;
    done.current = true;
    const next = value.trim();
    if (save && next && next !== title) {
      setBusy(true);
      const ok = await onSave(next);
      setBusy(false);
      if (!ok) {
        done.current = false;
        input.current?.focus();
        return;
      }
    }
    setEditing(false);
    requestAnimationFrame(() => button.current?.focus());
  }

  if (editing) {
    return (
      <input
        ref={input}
        aria-label={copy.titleLabel}
        value={value}
        maxLength={40}
        disabled={busy}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.nativeEvent.isComposing) {
            e.preventDefault();
            void finish(true);
          } else if (e.key === "Escape") {
            e.preventDefault();
            void finish(false);
          }
        }}
        onBlur={() => void finish(true)}
        className={cn(inputClasses, "min-h-control w-full max-w-sm text-ui-lg font-bold md:w-80")}
      />
    );
  }
  return (
    <div className="flex min-w-0 items-center gap-1">
      <h1 className="min-w-0 truncate text-ui-xl text-ink-900" title={title}>
        {title}
      </h1>
      <IconButton
        ref={button}
        aria-label={copy.titleEdit(title)}
        icon={<PencilLine size={16} strokeWidth={2} aria-hidden="true" />}
        onClick={open}
      />
    </div>
  );
}
