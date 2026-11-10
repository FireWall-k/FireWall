// 근로자 화면 설정 7항목(명세 4.12 표 그대로). 근로자 상세 '화면 설정'과 설정의 '근로자 화면 기본값'이 함께 쓴다.
// 바꾸면 바로 저장한다(onChange에 바뀐 키 하나만 넘김). 고르는 칸은 라디오 묶음(fieldset + legend), 켜고 끄는 칸은 Switch.
import { useId } from "react";
import type { A11yPrefs } from "../../api";
import { Switch } from "../../components/ui";
import { cn } from "../../cn";
import { prefs as copy } from "../copy";

interface Option<V> {
  value: V;
  label: string;
}

function Segmented<V extends string | number>({
  legend,
  hint,
  name,
  value,
  options,
  onChange,
  disabled,
}: {
  legend: string;
  hint?: string;
  name: string;
  value: V;
  options: Option<V>[];
  onChange: (v: V) => void;
  disabled?: boolean;
}) {
  const hintId = useId();
  return (
    <fieldset className="flex flex-col gap-2" aria-describedby={hint ? hintId : undefined} disabled={disabled}>
      <legend className="text-ui-base font-semibold text-ink-900">{legend}</legend>
      {hint && (
        <p id={hintId} className="-mt-1 text-ui-sm text-ink-500">
          {hint}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {options.map((o) => {
          const checked = o.value === value;
          return (
            <label key={String(o.value)} className="relative">
              <input
                type="radio"
                name={name}
                value={String(o.value)}
                checked={checked}
                onChange={() => onChange(o.value)}
                className="peer sr-only"
              />
              <span
                className={cn(
                  "inline-flex min-h-control cursor-pointer items-center whitespace-nowrap rounded-control border px-3 text-ui-base font-semibold coarse:min-h-control-coarse",
                  "peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-moss-600",
                  checked ? "border-moss-600 bg-moss-600 text-white" : "border-line-strong bg-white text-ink-900 hover:bg-paper-100",
                )}
              >
                {o.label}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

export interface PrefsFormProps {
  value: A11yPrefs;
  onChange: (patch: Partial<A11yPrefs>) => void;
  /** 라디오 name이 화면 안에서 겹치지 않게. */
  idPrefix: string;
  disabled?: boolean;
}

export default function PrefsForm({ value, onChange, idPrefix, disabled }: PrefsFormProps) {
  const n = (k: string) => `${idPrefix}-${k}`;
  return (
    <div className="flex flex-col gap-5">
      <Segmented
        legend={copy.font_size.label}
        name={n("font")}
        value={value.font_size}
        disabled={disabled}
        options={[
          { value: "normal", label: copy.font_size.normal },
          { value: "large", label: copy.font_size.large },
        ]}
        onChange={(v) => onChange({ font_size: v })}
      />
      <Switch
        label={copy.autoplay_sound.label}
        hint={copy.autoplay_sound.hint}
        checked={value.autoplay_sound}
        disabled={disabled}
        onChange={(v) => onChange({ autoplay_sound: v })}
      />
      <Segmented
        legend={copy.tts_rate.label}
        name={n("rate")}
        value={value.tts_rate}
        disabled={disabled}
        options={[
          { value: 0.8, label: `${copy.tts_rate.slow} 0.8` },
          { value: 0.9, label: `${copy.tts_rate.normal} 0.9` },
          { value: 1.0, label: `${copy.tts_rate.fast} 1.0` },
        ]}
        onChange={(v) => onChange({ tts_rate: v as A11yPrefs["tts_rate"] })}
      />
      <div className="flex flex-col gap-2">
        <p className="text-ui-base font-semibold text-ink-900">{copy.sound.label}</p>
        <Switch label={copy.sfx.label} checked={value.sfx} disabled={disabled} onChange={(v) => onChange({ sfx: v })} />
        <Switch
          label={copy.vibration.label}
          checked={value.vibration}
          disabled={disabled}
          onChange={(v) => onChange({ vibration: v })}
        />
      </div>
      <Segmented
        legend={copy.praise.label}
        name={n("praise")}
        value={value.praise}
        disabled={disabled}
        options={[
          { value: "normal", label: copy.praise.normal },
          { value: "quiet", label: copy.praise.quiet },
        ]}
        onChange={(v) => onChange({ praise: v })}
      />
      <Segmented
        legend={copy.hand.label}
        hint={copy.hand.hint}
        name={n("hand")}
        value={value.hand}
        disabled={disabled}
        options={[
          { value: "right", label: copy.hand.right },
          { value: "left", label: copy.hand.left },
        ]}
        onChange={(v) => onChange({ hand: v })}
      />
      <Segmented
        legend={copy.contrast.label}
        name={n("contrast")}
        value={value.contrast}
        disabled={disabled}
        options={[
          { value: "normal", label: copy.contrast.normal },
          { value: "high", label: copy.contrast.high },
        ]}
        onChange={(v) => onChange({ contrast: v })}
      />
    </div>
  );
}
