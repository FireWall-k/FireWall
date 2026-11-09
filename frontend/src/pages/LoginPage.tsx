// 로그인(명세 5.1, R12). /m/login·/login·/ 이 함께 쓴다.
// - 768 이상: 좌우 반반. 왼쪽 paper-100 패널(잡카드 로고 Gmarket Sans 28 · 소개 문구 · 단계 카드 예시 3장), 오른쪽 400 폼.
// - 768 미만(390 휴대폰): 왼쪽 패널을 위쪽 120 띠로 접는다.
// - form이라 Enter로 제출되고, 라벨은 눈에 보인다(KWCAG 7.3.2). [로그인]은 44 moss-600.
// - 사업주/근로자 탭: 근로자 탭은 /w 키패드로 못 넣는 예전 긴 번호용 우회로다(/login?tab=worker).
import { useEffect, useState, type FormEvent } from "react";
import { GlassWater, Shirt, SoapDispenserDroplet, type LucideIcon } from "lucide-react";
import { auth, type AuthState } from "../api";
import { getSavedWorkplaceCode, normalizeWorkplaceCode, saveWorkplaceCode } from "../workerCodes";
import { Button, Field, Input, Tabs } from "../components/ui";
import { login as copy } from "../manager/copy";

type LoginTab = "employer" | "worker";

// /login?tab=worker로 오면 근로자 탭을 연다(/w 키패드로 못 넣는 예전 긴 번호용 우회로).
function initialTab(): LoginTab {
  try {
    return new URLSearchParams(window.location.search).get("tab") === "worker" ? "worker" : "employer";
  } catch {
    return "employer";
  }
}

// 예시 문장과 뜻이 맞는 그림(손 씻기 → 비누, 앞치마 → 옷, 컵 → 물컵). AAC 그림 파일은 서버 그림 사전에만 있어
// 로그인 전 화면에서 부를 수 없으므로 선 아이콘으로 대신한다(실제 그림 카드는 3차 그림 사전 화면에서).
const EXAMPLE_ICONS: LucideIcon[] = [SoapDispenserDroplet, Shirt, GlassWater];

export default function LoginPage({ onLogin }: { onLogin: (a: AuthState) => void }) {
  const [tab, setTab] = useState<LoginTab>(initialTab);
  const [loginId, setLoginId] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  // 이 기기에 저장된 사업장 코드. 있으면 근로자는 자기 접속 코드만 누른다.
  const [savedWorkplace, setSavedWorkplace] = useState<string | null>(() => getSavedWorkplaceCode());
  const [editingWorkplace, setEditingWorkplace] = useState(() => !getSavedWorkplaceCode());
  const [workplaceInput, setWorkplaceInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [demoFilled, setDemoFilled] = useState(false);

  // 시연용 데모 계정을 미리 채워 '로그인'만 누르면 들어가게 한다. 데모 계정이 없는 서버(운영)는 null이라
  // 아무것도 채우지 않는다. 빈칸에만 채운다 — 응답이 오기 전에 사용자가 입력한 값을 덮어쓰지 않는다.
  useEffect(() => {
    let cancelled = false;
    auth.demoCredentials().then((d) => {
      if (cancelled || !d) return;
      if (d.employer) {
        const { login_id, password: pw } = d.employer;
        setLoginId((v) => v || login_id);
        setPassword((v) => v || pw);
      }
      if (d.worker) {
        const { workplace_code, access_code } = d.worker;
        const saved = getSavedWorkplaceCode();
        // 이 기기에 다른 사업장이 저장돼 있으면 그 사업장의 근로자용 기기다 — 데모 코드를 넣지 않는다.
        if (!saved) setWorkplaceInput((v) => v || workplace_code);
        if (!saved || saved === workplace_code) setCode((v) => v || access_code);
      }
      if (d.employer || d.worker) setDemoFilled(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const workplace = editingWorkplace ? normalizeWorkplaceCode(workplaceInput) : savedWorkplace ?? "";

  // 비어 있으면 서버 검증(422) 응답을 받게 되는데, 그 메시지는 사용자용 문장이 아니다.
  const ready = tab === "employer" ? !!loginId.trim() && !!password : !!code.trim() && !!workplace;

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      const state = tab === "employer" ? await auth.loginEmployer(loginId, password) : await auth.loginWorker(workplace, code);
      if (tab === "worker") {
        // 로그인에 성공한 사업장 코드만 저장한다. 실패한 값을 저장하면 오타가 기기에 남아
        // 근로자가 맞는 접속 코드를 눌러도 계속 실패하게 된다.
        saveWorkplaceCode(workplace);
        setSavedWorkplace(workplace);
        setEditingWorkplace(false);
      }
      onLogin(state);
    } catch (err) {
      // 번호·비밀번호가 틀렸을 때(401)는 서버 문장을 그대로 보인다(api.ts가 로그인 401을 AuthError로 바꾸지 않음).
      setError(err instanceof Error ? err.message : copy.failed);
    } finally {
      setBusy(false);
    }
  }

  function changeWorkplace() {
    // 저장된 값은 새 사업장으로 로그인에 성공할 때 바뀐다. 그 전까지는 지우지 않는다
    // (변경을 눌렀다가 그만둬도 원래 사업장으로 돌아갈 수 있게).
    setWorkplaceInput("");
    setEditingWorkplace(true);
    setError(null);
  }

  return (
    // break-keep: 한국어 안내 문장을 낱말 중간에서 끊지 않는다(근로자도 이 화면에서 로그인한다).
    <div className="flex min-h-screen flex-col break-keep bg-white font-body text-ink-900 md:grid md:grid-cols-2">
      {/* 왼쪽 소개 패널(390에서는 위쪽 120 띠). */}
      <section
        data-testid="login-intro"
        aria-label={copy.intro}
        className="flex h-login-band shrink-0 flex-col justify-center gap-1 bg-paper-100 px-6 md:h-auto md:min-h-screen md:gap-6 md:px-12 lg:px-16"
      >
        <p className="font-display text-ui-logo font-bold text-moss-600">잡카드</p>
        <p className="text-ui-base text-ink-700 md:text-ui-lg">{copy.intro}</p>
        <ol aria-label={copy.examplesLabel} className="hidden max-w-sm flex-col gap-3 md:flex">
          {copy.examples.map((sentence, i) => {
            const Icon = EXAMPLE_ICONS[i];
            return (
              <li key={sentence} className="flex items-center gap-3 rounded-card border border-paper-200 bg-white p-3 shadow-ui-sm">
                <span className="flex size-14 shrink-0 items-center justify-center rounded-control border border-worker-line-soft bg-white text-worker-primary">
                  <Icon size={28} strokeWidth={2} aria-hidden="true" />
                </span>
                <span className="min-w-0">
                  <span className="block text-ui-xs font-semibold tabular-nums text-ink-500">{i + 1}단계</span>
                  <span className="block text-ui-md font-bold text-ink-900">{sentence}</span>
                </span>
              </li>
            );
          })}
        </ol>
      </section>

      {/* 오른쪽 400 폼. */}
      <main className="flex flex-1 items-start justify-center px-4 py-8 md:items-center md:px-8">
        <div className="w-full max-w-form">
          <h1 className="text-ui-xl text-ink-900">{copy.title}</h1>
          <Tabs<LoginTab>
            className="mt-4"
            fill
            label={copy.tabsLabel}
            value={tab}
            onChange={(t) => {
              setTab(t);
              setError(null);
            }}
            items={[
              { id: "employer", label: copy.employerTab },
              { id: "worker", label: copy.workerTab },
            ]}
          />

          <form onSubmit={submit} noValidate className="mt-5 flex flex-col gap-4">
            {tab === "employer" ? (
              <>
                <Field label={copy.loginId}>
                  <Input value={loginId} onChange={(e) => setLoginId(e.target.value)} autoComplete="username" />
                </Field>
                <Field label={copy.password}>
                  <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
                </Field>
              </>
            ) : (
              <>
                {editingWorkplace ? (
                  <div className="flex flex-col gap-1">
                    <Field label={copy.workplaceCode} hint={copy.workplaceHint}>
                      <Input
                        className="text-center uppercase tracking-widest"
                        value={workplaceInput}
                        onChange={(e) => setWorkplaceInput(e.target.value)}
                        autoCapitalize="characters"
                        autoComplete="off"
                      />
                    </Field>
                    {savedWorkplace && (
                      <button
                        type="button"
                        onClick={() => {
                          setEditingWorkplace(false);
                          setError(null);
                        }}
                        className="min-h-8 self-start text-ui-sm text-ink-700 underline underline-offset-2 coarse:min-h-control-coarse"
                      >
                        {copy.keepWorkplace(savedWorkplace)}
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-control bg-paper-50 px-3 py-2 text-ui-base text-ink-700">
                    <span>
                      {copy.workplaceSaved} <strong className="tracking-widest text-ink-900">{savedWorkplace}</strong>
                    </span>
                    <button
                      type="button"
                      onClick={changeWorkplace}
                      className="min-h-8 text-ui-sm text-ink-700 underline underline-offset-2 coarse:min-h-control-coarse"
                    >
                      {copy.changeWorkplace}
                    </button>
                  </div>
                )}
                <Field label={copy.accessCode}>
                  <Input
                    className="text-center text-ui-xl tracking-widest"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    inputMode="numeric"
                    autoComplete="off"
                  />
                </Field>
              </>
            )}

            {demoFilled && <p className="text-ui-sm text-ink-500">{copy.demoFilled}</p>}
            {error && (
              <div role="alert" className="rounded-control border border-danger-700/20 bg-danger-50 p-3 text-ui-base text-danger-700">
                {error}
              </div>
            )}

            <Button
              type="submit"
              variant="primary"
              disabled={!ready}
              loading={busy}
              className="min-h-control-coarse w-full text-ui-md"
            >
              {busy ? copy.submitting : copy.submit}
            </Button>
          </form>

          {/* 근로자는 번호 키패드 화면(/w)으로. Router 밖에서도 렌더되도록(테스트) 일반 링크를 쓴다. */}
          <p className="mt-6 text-center text-ui-base text-ink-700">
            {copy.workerQuestion}{" "}
            <a href="/w" className="font-semibold text-info-700 underline underline-offset-2">
              {copy.workerLink}
            </a>
          </p>
        </div>
      </main>
    </div>
  );
}
