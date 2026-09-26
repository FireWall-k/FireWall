import { useEffect, useState } from "react";
import { KeyRound, Trash2, UserPlus, UserRound } from "lucide-react";
import { api, AuthError, type Worker } from "../api";

// 직접 정하는 코드는 6~12자리 숫자만 받는다(서버와 같은 규칙). 비우면 서버가 6자리를 만든다.
const CODE_RE = /^\d{6,12}$/;
// 예전에 만든 짧은 코드. 로그인은 되지만 대입으로 뚫리기 쉬워 새로 만들기를 권한다.
const isWeakCode = (code: string) => code.length < 6;

export default function WorkersPage() {
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    api.listWorkers()
      .then(setWorkers)
      .catch((e) =>
        setError(e instanceof AuthError ? "다시 로그인해 주세요." : e instanceof Error ? e.message : "근로자 목록을 불러오지 못했습니다.")
      )
      .finally(() => setLoading(false));
  }, []);

  async function addWorker() {
    if (!name.trim()) {
      setError("이름을 입력해 주세요.");
      return;
    }
    if (code.trim() && !CODE_RE.test(code.trim())) {
      setError("접속 코드는 6~12자리 숫자로 정해 주세요. 비워 두면 자동으로 만들어요.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const w = await api.createWorker(name.trim(), code.trim() || undefined);
      setWorkers((prev) => [...prev, w]);
      setName("");
      setCode("");
      setNotice(`근로자 '${w.display_name}'을(를) 추가했습니다. 접속 코드: ${w.access_code}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "근로자 추가에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  async function reissueCode(id: string, displayName: string) {
    if (!window.confirm(`'${displayName}'의 접속 코드를 새로 만들까요?\n예전 코드로는 더 이상 로그인할 수 없어요.`)) {
      return;
    }
    setError(null);
    setNotice(null);
    try {
      const w = await api.reissueAccessCode(id);
      setWorkers((prev) => prev.map((x) => (x.id === id ? w : x)));
      setNotice(`'${w.display_name}'의 새 접속 코드: ${w.access_code}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "접속 코드를 바꾸지 못했습니다.");
    }
  }

  async function removeWorker(id: string, displayName: string) {
    if (!window.confirm(`근로자 '${displayName}'을(를) 삭제할까요?\n이 근로자의 배정·수행 기록도 함께 삭제됩니다.`)) {
      return;
    }
    setError(null);
    setNotice(null);
    try {
      await api.deleteWorker(id);
      setWorkers((prev) => prev.filter((w) => w.id !== id));
      setNotice(`근로자 '${displayName}'을(를) 삭제했습니다.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "근로자 삭제에 실패했습니다.");
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-6">
        <h1 className="font-display text-2xl font-semibold text-ink-900">근로자 관리</h1>
        <p className="mt-1 text-sm text-ink-500">
          근로자를 추가·삭제하고 접속 코드를 확인합니다. 근로자는 이 코드로 로그인해요.
        </p>
      </header>

      {error && <div role="alert" className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</div>}
      {notice && <div role="status" className="mb-4 rounded-lg bg-green-50 p-3 text-sm text-green-800">{notice}</div>}

      <section className="mb-6 rounded-2xl border border-paper-200 bg-white p-5 shadow-sm">
        <h2 className="mb-3 text-sm font-bold text-ink-900">근로자 추가</h2>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="이름 (예: 홍길동)"
            aria-label="근로자 이름"
            className="rounded-lg border border-paper-200 px-3 py-2 text-sm focus:border-moss-500 focus:outline-none"
          />
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="접속 코드 (비우면 자동)"
            aria-label="접속 코드"
            inputMode="numeric"
            className="rounded-lg border border-paper-200 px-3 py-2 text-sm focus:border-moss-500 focus:outline-none"
          />
          <button
            onClick={addWorker}
            disabled={busy || !name.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-moss-500 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            <UserPlus size={15} />
            추가
          </button>
        </div>
        <p className="mt-2 text-xs text-ink-500">
          접속 코드를 비워 두면 겹치지 않는 6자리 숫자를 자동으로 만들어요. 직접 정할 때는 6~12자리 숫자로 입력해 주세요.
        </p>
      </section>

      <section className="rounded-2xl border border-paper-200 bg-white p-5 shadow-sm">
        <h2 className="mb-3 text-sm font-bold text-ink-900">
          등록된 근로자{workers.length > 0 && <span className="ml-1 text-ink-500">({workers.length}명)</span>}
        </h2>
        {loading ? (
          <p className="text-sm text-ink-500">불러오는 중…</p>
        ) : workers.length === 0 ? (
          <p className="text-sm text-ink-500">아직 등록된 근로자가 없습니다. 위에서 추가해 주세요.</p>
        ) : (
          <ul className="divide-y divide-paper-200">
            {workers.map((w) => (
              <li key={w.id} className="flex items-center justify-between py-3">
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 items-center justify-center rounded-full bg-paper-100 text-ink-500">
                    <UserRound size={17} />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-ink-900">{w.display_name}</p>
                    <p className="text-xs text-ink-500">
                      접속 코드 {w.access_code}
                      {isWeakCode(w.access_code) && (
                        <span className="ml-1.5 font-semibold text-signal-red">짧은 코드예요 — 새로 만들어 주세요</span>
                      )}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                <button
                  onClick={() => reissueCode(w.id, w.display_name)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-paper-200 px-3 py-1.5 text-sm font-medium text-ink-700 hover:bg-paper-100"
                  aria-label={`근로자 ${w.display_name} 접속 코드 새로 만들기`}
                >
                  <KeyRound size={14} />
                  코드 새로 만들기
                </button>
                <button
                  onClick={() => removeWorker(w.id, w.display_name)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-paper-200 px-3 py-1.5 text-sm font-medium text-signal-red hover:bg-signal-red/5"
                  aria-label={`근로자 ${w.display_name} 삭제`}
                >
                  <Trash2 size={14} />
                  삭제
                </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
