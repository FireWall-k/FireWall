// 그림 찾기·현장 사진 올리기(명세 5.5·6.5, tasks §4.3 PicturePicker). Dialog 하나에 두 모양:
// - search: 낱말로 그림 카드를 찾아(규칙 검색, 유료 모델 없음) 하나를 고르면 단계에 붙고 바로 확인함이 된다.
// - photo: 사진 안내 3줄 · 예시 2장 · 얼굴 안내 → [사진 고르기]. 올린 사진은 사업주가 고른 것이라 확인함이다.
import { useId, useState, type FormEvent } from "react";
import { Camera, Search } from "lucide-react";
import type { AacMatch } from "../../../api";
import { Button, Dialog, Field, Input, buttonClasses } from "../../../components/ui";
import { cn } from "../../../cn";
import { editorApi } from "../../api/editor";
import type { PictureCandidate } from "../../api/types";
import { picker as copy } from "../../copy";
import { errorMessage } from "../listHelpers";

export interface PicturePickerProps {
  open: boolean;
  mode: "search" | "photo";
  stepNo: number;
  /** 검색칸 처음 글(단계 문장). */
  initialQuery: string;
  onClose: () => void;
  /** 고른 그림을 붙인다. 성공하면 true(창을 닫는다). */
  onApply: (c: PictureCandidate) => Promise<boolean>;
  onUpload: (file: File) => Promise<boolean>;
}

export default function PicturePicker(props: PicturePickerProps) {
  if (!props.open) return null;
  return <PickerDialog {...props} />;
}

function PickerDialog({ mode, stepNo, initialQuery, onClose, onApply, onUpload }: PicturePickerProps) {
  const [query, setQuery] = useState(initialQuery);
  const [results, setResults] = useState<AacMatch[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileId = useId();

  async function search(e?: FormEvent) {
    e?.preventDefault();
    const q = query.trim();
    if (!q || searching) return;
    setSearching(true);
    setError(null);
    try {
      const r = await editorApi.searchPictures(q);
      setResults(r.matches);
    } catch (err) {
      setError(errorMessage(err) || copy.searchFailed);
    } finally {
      setSearching(false);
    }
  }

  async function pick(m: AacMatch) {
    if (busy) return;
    setBusy(true);
    const ok = await onApply({ card_id: m.asset_id, url: m.image_url, label: m.label });
    setBusy(false);
    if (ok) onClose();
  }

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    const ok = await onUpload(file);
    setBusy(false);
    if (ok) onClose();
    else setError(copy.uploadFailed);
  }

  return (
    <Dialog
      open
      onClose={onClose}
      busy={busy && mode === "photo"}
      title={mode === "search" ? copy.searchTitle(stepNo) : copy.photoTitle(stepNo)}
    >
      {mode === "search" ? (
        <div className="flex flex-col gap-4">
          <form onSubmit={search} className="flex items-end gap-2">
            <Field label={copy.searchLabel} hint={copy.searchHint} className="min-w-0 flex-1">
              <Input value={query} onChange={(e) => setQuery(e.target.value)} maxLength={100} data-autofocus />
            </Field>
            <Button type="submit" variant="primary" loading={searching} disabled={!query.trim()} icon={<Search size={16} strokeWidth={2} aria-hidden="true" />}>
              {copy.searchSubmit}
            </Button>
          </form>
          <div aria-live="polite" className="text-ui-sm text-ink-700">
            {searching ? copy.searching : results ? (results.length ? copy.results(results.length) : copy.noResults) : ""}
          </div>
          {error && (
            <p role="alert" className="text-ui-base font-semibold text-danger-700">
              {error}
            </p>
          )}
          {results && results.length > 0 && (
            <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3" data-testid="picker-results">
              {results.map((m) => (
                <li key={m.asset_id}>
                  <button
                    type="button"
                    onClick={() => void pick(m)}
                    aria-disabled={busy || undefined}
                    className="flex w-full flex-col items-center gap-1 rounded-card border border-paper-200 bg-white p-2 text-ui-sm text-ink-900 hover:border-moss-600 hover:bg-paper-50"
                  >
                    <img src={m.image_url} alt="" className="aspect-square w-full max-w-[120px] object-contain" />
                    <span className="line-clamp-2 text-center">{copy.apply(m.label)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <ol className="flex list-decimal flex-col gap-1 pl-5 text-ui-base text-ink-900">
            {copy.photoTips.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ol>
          <figure className="m-0 flex flex-col gap-2">
            <figcaption className="text-ui-sm font-semibold text-ink-700">{copy.examplesLabel}</figcaption>
            <div className="grid grid-cols-2 gap-2">
              {copy.examples.map((label, i) => (
                <div key={label} className="flex flex-col items-center gap-1 rounded-card border border-paper-200 bg-paper-50 p-2">
                  <ExamplePicture variant={i === 0 ? "close" : "clean"} />
                  <span className="text-center text-ui-sm text-ink-700">{label}</span>
                </div>
              ))}
            </div>
          </figure>
          <p className="rounded-control border border-warn-line/40 bg-warn-50 px-3 py-2 text-ui-base text-warn-700">{copy.photoFace}</p>
          {error && (
            <p role="alert" className="text-ui-base font-semibold text-danger-700">
              {error}
            </p>
          )}
          <div className="flex flex-col gap-1">
            <input
              id={fileId}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              className="peer sr-only"
              disabled={busy}
              data-testid="photo-input"
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) void upload(f);
              }}
            />
            <label
              htmlFor={fileId}
              className={cn(
                buttonClasses("primary", "md"),
                "cursor-pointer self-start peer-focus-visible:outline peer-focus-visible:outline-[3px] peer-focus-visible:outline-offset-[3px] peer-focus-visible:outline-clay-500",
                busy && "pointer-events-none opacity-50",
              )}
            >
              <Camera size={16} strokeWidth={2} aria-hidden="true" />
              {busy ? copy.uploading : copy.photoPick}
            </label>
          </div>
        </div>
      )}
    </Dialog>
  );
}

/** 사진 예시(꾸밈 그림): 손과 물건을 크게 / 뒤가 깨끗하게. 실제 사진을 저장소에 넣지 않으려고 단순한 그림으로 보인다. */
function ExamplePicture({ variant }: { variant: "close" | "clean" }) {
  return (
    <svg viewBox="0 0 120 90" aria-hidden="true" className="h-20 w-full max-w-[140px] text-ink-700">
      <rect x="1" y="1" width="118" height="88" rx="8" className="fill-white stroke-paper-200" strokeWidth="2" />
      {variant === "close" ? (
        <>
          <rect x="44" y="22" width="36" height="46" rx="6" className="fill-paper-100 stroke-current" strokeWidth="3" />
          <path d="M20 70 C30 52 40 50 46 52 L58 56 C62 58 60 64 56 64 L46 63" className="fill-none stroke-current" strokeWidth="4" strokeLinecap="round" />
        </>
      ) : (
        <>
          <rect x="34" y="30" width="28" height="36" rx="5" className="fill-paper-100 stroke-current" strokeWidth="3" />
          <path d="M70 66 C76 54 84 52 92 56" className="fill-none stroke-current" strokeWidth="4" strokeLinecap="round" />
          <line x1="12" y1="74" x2="108" y2="74" className="stroke-paper-200" strokeWidth="2" />
        </>
      )}
    </svg>
  );
}
