// 기기 연결(/worker/setup, 명세 3.2). 사업주(호칭은 사업장 설정)가 근로자 기기에 가게 코드를 한 번 넣어 둔다 — 그 뒤 근로자는
// 자기 번호 4자리만 누른다. 로그인 전에 가게 코드가 맞는지 알려 주는 공개 API는 없다(코드 엿보기 방지):
// 저장만 하고, 맞는지는 근로자가 처음 들어갈 때 알 수 있다.
// 이 화면도 근로자 기기에 뜨므로 근로자 화면 말투(금지어 없음)를 지킨다.
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { clearSavedWorkplaceCode, getSavedWorkplaceCode, normalizeWorkplaceCode, saveWorkplaceCode } from "../workerCodes";
import { IconDone, IconExit } from "../ui/icons";
import { PrimaryAction, SecondaryAction } from "./ui/WorkerButton";
import { BottomBar, TopBar, WorkerScreen } from "./WorkerScreen";
import { COPY } from "./copy";

const SETUP_COPY = COPY.setup;

export default function SetupScreen() {
  const navigate = useNavigate();
  const saved = getSavedWorkplaceCode();
  const [value, setValue] = useState(saved ?? "");
  const [error, setError] = useState(false);

  function save(e?: FormEvent) {
    e?.preventDefault();
    const code = normalizeWorkplaceCode(value);
    if (!code) {
      setError(true);
      return;
    }
    // 다른 가게로 바꾸면 예전 가게 이름이 남아 보이지 않게 지운다(이름은 첫 로그인 때 다시 받는다).
    if (code !== saved) clearSavedWorkplaceCode();
    saveWorkplaceCode(code);
    navigate("/worker", { replace: true });
  }

  return (
    <WorkerScreen
      testId="setup-screen"
      top={
        <TopBar
          left={
            saved ? (
              <SecondaryAction icon={IconExit} onPress={() => navigate("/worker")} className="!gap-2 !px-3">
                {SETUP_COPY.back}
              </SecondaryAction>
            ) : undefined
          }
        />
      }
      bottom={
        <BottomBar>
          <PrimaryAction icon={IconDone} onPress={() => save()} className="w-full">
            {SETUP_COPY.save}
          </PrimaryAction>
        </BottomBar>
      }
      mainClassName="gap-4 py-6 [justify-content:safe_center]"
    >
      <h1 className="text-worker-lg font-bold">{SETUP_COPY.title}</h1>
      <p className="text-worker text-worker-ink-soft hc:text-black">{SETUP_COPY.body}</p>
      <form onSubmit={save} className="flex flex-col gap-2">
        <label htmlFor="workplace-code" className="text-worker font-semibold">
          {SETUP_COPY.label}
        </label>
        <input
          id="workplace-code"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setError(false);
          }}
          autoCapitalize="characters"
          autoComplete="off"
          spellCheck={false}
          aria-invalid={error || undefined}
          aria-describedby={error ? "workplace-code-error" : undefined}
          className="min-h-touch rounded-worker-btn border-2 border-worker-line bg-worker-card px-4 text-worker-lg font-bold uppercase tracking-widest hc:border-black"
        />
        {error && (
          <p id="workplace-code-error" role="alert" className="text-worker font-semibold text-worker-caution-ink">
            {SETUP_COPY.empty}
          </p>
        )}
      </form>
    </WorkerScreen>
  );
}
