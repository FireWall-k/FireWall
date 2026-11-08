import { useEffect, useState } from "react";
import { auth, type AuthState } from "../api";
import { getSavedWorkplaceCode, normalizeWorkplaceCode, saveWorkplaceCode } from "../workerCodes";
import { cn } from "../cn";

// /login?tab=worker로 오면 근로자 탭을 연다(/w 키패드로 못 넣는 예전 긴 번호용 우회로).
function initialTab(): "employer" | "worker" {
  try {
    return new URLSearchParams(window.location.search).get("tab") === "worker" ? "worker" : "employer";
  } catch {
    return "employer";
  }
}

export default function LoginPage({ onLogin }: { onLogin: (a: AuthState) => void }) {
  const [tab, setTab] = useState<"employer" | "worker">(initialTab);
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
    return () => { cancelled = true; };
  }, []);

  const workplace = editingWorkplace ? normalizeWorkplaceCode(workplaceInput) : savedWorkplace ?? "";

  // 비어 있으면 서버 검증(422) 응답을 받게 되는데, 그 메시지는 사용자용 문장이 아니다.
  const ready = tab === "employer" ? !!loginId.trim() && !!password : !!code.trim() && !!workplace;

  async function submit() {
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      const state =
        tab === "employer"
          ? await auth.loginEmployer(loginId, password)
          : await auth.loginWorker(workplace, code);
      if (tab === "worker") {
        // 로그인에 성공한 사업장 코드만 저장한다. 실패한 값을 저장하면 오타가 기기에 남아
        // 근로자가 맞는 접속 코드를 눌러도 계속 실패하게 된다.
        saveWorkplaceCode(workplace);
        setSavedWorkplace(workplace);
        setEditingWorkplace(false);
      }
      onLogin(state);
    } catch (e) {
      // 번호·비밀번호가 틀렸을 때(401)는 서버 문장을 그대로 보인다(api.ts가 로그인 401을 AuthError로 바꾸지 않음).
      setError(e instanceof Error ? e.message : "로그인하지 못했어요. 다시 시도해 주세요.");
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
    <div className="mx-auto mt-10 max-w-sm break-keep rounded-2xl border border-slate-200 bg-white p-6 [overflow-wrap:anywhere]">
      <h1 className="text-xl font-bold text-slate-900">잡카드 로그인</h1>
      <div className="mt-4 flex gap-1 rounded-lg bg-slate-100 p-1">
        {(["employer", "worker"] as const).map((t) => (
          <button
            key={t}
            onClick={() => { setTab(t); setError(null); }}
            className={cn("min-h-12 flex-1 rounded-md px-3 py-2 text-base font-medium",
              tab === t ? "bg-white text-slate-900 shadow" : "text-slate-500")}
          >
            {t === "employer" ? "사업주" : "근로자"}
          </button>
        ))}
      </div>

      {tab === "employer" ? (
        <div className="mt-4 space-y-3">
          <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-base"
            value={loginId} onChange={(e) => setLoginId(e.target.value)} aria-label="아이디" placeholder="아이디" />
          <input type="password" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-base"
            value={password} onChange={(e) => setPassword(e.target.value)} aria-label="비밀번호" placeholder="비밀번호" />
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          {editingWorkplace ? (
            <div>
              <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-center text-lg uppercase tracking-widest"
                value={workplaceInput} onChange={(e) => setWorkplaceInput(e.target.value)}
                aria-label="사업장 코드" placeholder="사업장 코드" autoCapitalize="characters" autoComplete="off" />
              <p className="mt-1 text-xs text-slate-500">
                사업주에게 받은 사업장 코드를 넣어 주세요. 한 번 로그인하면 이 기기에 저장돼요.
              </p>
              {savedWorkplace && (
                <button type="button" onClick={() => { setEditingWorkplace(false); setError(null); }}
                  className="mt-1 text-xs text-slate-500 underline">
                  취소 (사업장 {savedWorkplace} 그대로 쓰기)
                </button>
              )}
            </div>
          ) : (
            <div className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">
              <span>
                사업장 <strong className="tracking-widest text-slate-900">{savedWorkplace}</strong>
              </span>
              <button type="button" onClick={changeWorkplace} className="text-xs text-slate-500 underline">
                이 기기 사업장 변경
              </button>
            </div>
          )}
          <input className="w-full rounded-lg border border-slate-300 px-3 py-3 text-center text-2xl tracking-widest"
            value={code} onChange={(e) => setCode(e.target.value)} aria-label="접속 코드" placeholder="접속 코드" inputMode="numeric" />
        </div>
      )}

      {demoFilled && (
        <p className="mt-3 text-xs text-slate-500">시연용 데모 계정이 미리 채워져 있어요. 로그인을 누르세요.</p>
      )}
      {error && <div role="alert" className="mt-3 rounded-lg bg-red-50 p-2 text-sm text-red-800">{error}</div>}

      <button onClick={submit} disabled={busy || !ready}
        className="mt-4 min-h-12 w-full rounded-lg bg-moss-600 py-2.5 font-semibold text-white hover:bg-moss-700 disabled:opacity-50">
        {busy ? "확인 중…" : "로그인"}
      </button>
      {/* 근로자는 번호 키패드 화면(/w)으로. Router 밖에서도 렌더되도록(테스트) 일반 링크를 쓴다. */}
      <p className="mt-4 text-center text-sm text-ink-700">
        근로자이신가요?{" "}
        <a href="/w" className="font-semibold text-info-700 underline underline-offset-2">
          근로자 화면으로 ›
        </a>
      </p>
    </div>
  );
}
