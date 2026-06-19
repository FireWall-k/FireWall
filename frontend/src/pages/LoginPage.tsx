import { useState } from "react";
import { auth, type AuthState } from "../api";

export default function LoginPage({ onLogin }: { onLogin: (a: AuthState) => void }) {
  const [tab, setTab] = useState<"employer" | "worker">("employer");
  const [loginId, setLoginId] = useState("demo");
  const [password, setPassword] = useState("demo1234");
  const [code, setCode] = useState("1234");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const state =
        tab === "employer"
          ? await auth.loginEmployer(loginId, password)
          : await auth.loginWorker(code);
      onLogin(state);
    } catch (e) {
      setError(e instanceof Error ? e.message : "로그인 실패");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto mt-10 max-w-sm rounded-2xl border border-slate-200 bg-white p-6">
      <h1 className="text-xl font-bold text-slate-900">잡카드 로그인</h1>
      <div className="mt-4 flex gap-1 rounded-lg bg-slate-100 p-1">
        {(["employer", "worker"] as const).map((t) => (
          <button
            key={t}
            onClick={() => { setTab(t); setError(null); }}
            className={"flex-1 rounded-md px-3 py-2 text-sm font-medium " +
              (tab === t ? "bg-white text-slate-900 shadow" : "text-slate-500")}
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
        <div className="mt-4">
          <input className="w-full rounded-lg border border-slate-300 px-3 py-3 text-center text-2xl tracking-widest"
            value={code} onChange={(e) => setCode(e.target.value)} aria-label="접속 코드" placeholder="접속 코드" inputMode="numeric" />
        </div>
      )}

      {error && <div role="alert" className="mt-3 rounded-lg bg-red-50 p-2 text-sm text-red-800">{error}</div>}

      <button onClick={submit} disabled={busy}
        className="mt-4 w-full rounded-lg bg-blue-700 py-2.5 font-semibold text-white disabled:opacity-50">
        {busy ? "확인 중…" : "로그인"}
      </button>
      <p className="mt-3 text-center text-xs text-slate-400">
        데모: 사업주 demo / demo1234 · 근로자 코드 1234
      </p>
    </div>
  );
}
