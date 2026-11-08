import { useEffect, useState } from "react";
import { Download, KeyRound, Trash2, UserPlus, UserRound } from "lucide-react";
import { api, AuthError, type ConsentSubject, type ConsentType, type Worker } from "../api";
import { ACCESS_CODE_UNKNOWN_HINT, accessCodeText } from "../workerCodes";

// 직접 정하는 코드는 4~12자리 숫자만 받는다(서버와 같은 규칙). 비우면 서버가 4자리를 만든다.
// 4자리가 기본이다(창업자 결정 3: 근로자는 번호 키패드로 4자리만 누른다). 대입 공격은 서버의 로그인 시도 제한
// (IP별·사업장별)이 막으므로, 예전처럼 6자리 미만을 '짧은 코드'로 경고하지 않는다.
const CODE_RE = /^\d{4,12}$/;

// 내보낸 JSON을 파일로 저장한다. 서버는 사본을 남기지 않으므로 이 파일이 사업주가 가진 유일한 사본이다.
// 파일 이름에 근로자 이름을 넣지 않는다(다운로드 폴더·브라우저 기록에 남는다).
function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

const SUBJECT_LABEL: Record<ConsentSubject, string> = { self: "당사자", guardian: "보호자" };

// 동의 종류별 화면 문구와 목록 응답의 상태 필드. 개인정보 처리방침(docs/privacy)의 두 항목과 맞춘다.
// 예전 화면은 AI 처리 동의만 기록할 수 있어, 서비스 제공의 기본 근거인 수집·이용 동의는 API로만 남길 수 있었다.
const CONSENT_UI: Record<ConsentType, {
  label: string;
  field: "ai_consent" | "personal_info_consent";
  confirm: string;
  revokeConfirm: string;
}> = {
  personal_info: {
    label: "개인정보 수집·이용 동의",
    field: "personal_info_consent",
    confirm: "동의서 원본은 사업장에서 보관해 주세요.",
    revokeConfirm: "철회 후에는 이 근로자의 개인정보를 더 쓰지 말고, 필요하면 내보내기 후 삭제해 주세요.",
  },
  ai_processing: {
    label: "AI 처리(국외 이전) 동의",
    field: "ai_consent",
    confirm: "동의서 원본은 사업장에서 보관해 주세요. 동의하면 AI 코칭에 이 근로자의 수행 기록이 쓰입니다.",
    revokeConfirm: "이후 AI 코칭은 기본 규칙 제안만 나와요.",
  },
};

export default function WorkersPage() {
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // 근로자 추가 결과는 추가 폼 바로 아래에 보여 준다. 화면 위쪽 배너에 띄우면 폼을 보고 있는 사업주가
  // 오류를 못 보고 "추가가 안 된다"고 느꼈다(사용자 피드백). 다른 동작의 결과는 위쪽 배너를 그대로 쓴다.
  const [addError, setAddError] = useState<string | null>(null);
  const [addNotice, setAddNotice] = useState<string | null>(null);
  const [workplaceCode, setWorkplaceCode] = useState<string | null>(null);
  // 근로자별 메모 입력 중인 값. 저장 버튼을 누를 때만 서버로 보낸다.
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});

  useEffect(() => {
    // 사업장 코드는 근로자 기기에 한 번 입력해 두는 값이다. 못 불러와도 근로자 관리는 계속 쓸 수 있게
    // 목록 오류와 분리해 조용히 넘긴다.
    api.workplace()
      .then((wp) => setWorkplaceCode(wp.workplace_code))
      .catch(() => setWorkplaceCode(null));
  }, []);

  useEffect(() => {
    api.listWorkers()
      .then(setWorkers)
      .catch((e) =>
        setError(e instanceof AuthError ? "다시 로그인해 주세요." : e instanceof Error ? e.message : "근로자 목록을 불러오지 못했습니다.")
      )
      .finally(() => setLoading(false));
  }, []);

  async function addWorker() {
    setAddNotice(null);
    if (!name.trim()) {
      setAddError("이름을 입력해 주세요.");
      return;
    }
    if (code.trim() && !CODE_RE.test(code.trim())) {
      setAddError("접속 코드는 4~12자리 숫자로 정해 주세요. 비워 두면 자동으로 만들어요.");
      return;
    }
    setBusy(true);
    setAddError(null);
    try {
      const w = await api.createWorker(name.trim(), code.trim() || undefined);
      setWorkers((prev) => [...prev, w]);
      setName("");
      setCode("");
      setAddNotice(`근로자 '${w.display_name}'을(를) 추가했습니다. 접속 코드: ${w.access_code} (근로자에게 알려 주세요)`);
    } catch (e) {
      setAddError(e instanceof Error ? e.message : "근로자 추가에 실패했습니다.");
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
      setNotice(`'${w.display_name}'의 새 접속 코드: ${w.access_code} (근로자에게 알려 주세요)`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "접속 코드를 바꾸지 못했습니다.");
    }
  }

  function replaceWorker(w: Worker) {
    setWorkers((prev) => prev.map((x) => (x.id === w.id ? { ...x, ...w } : x)));
  }

  async function exportWorker(id: string, displayName: string) {
    setError(null);
    setNotice(null);
    try {
      const data = await api.exportWorker(id);
      downloadJson(`worker-${id.slice(0, 8)}.json`, data);
      setNotice(`'${displayName}'의 데이터를 내보냈어요. 파일에 개인정보가 들어 있으니 안전하게 보관해 주세요.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "내보내기에 실패했습니다.");
    }
  }

  async function recordConsent(w: Worker, subject: ConsentSubject, type: ConsentType = "ai_processing") {
    const ui = CONSENT_UI[type];
    if (!window.confirm(
      `${SUBJECT_LABEL[subject]}에게서 '${w.display_name}'의 ${ui.label}를 받으셨나요?\n${ui.confirm}`,
    )) {
      return;
    }
    setError(null);
    setNotice(null);
    try {
      await api.grantConsent(w.id, type, subject);
      replaceWorker({ ...w, [ui.field]: true });
      setNotice(`'${w.display_name}'의 ${ui.label}(${SUBJECT_LABEL[subject]})를 기록했어요.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "동의를 기록하지 못했습니다.");
    }
  }

  async function revokeConsent(w: Worker, type: ConsentType = "ai_processing") {
    const ui = CONSENT_UI[type];
    if (!window.confirm(`'${w.display_name}'의 ${ui.label} 철회를 기록할까요?\n${ui.revokeConfirm}`)) {
      return;
    }
    setError(null);
    setNotice(null);
    try {
      const consents = await api.listConsents(w.id);
      const active = consents.filter((c) => c.consent_type === type && !c.revoked_at);
      await Promise.all(active.map((c) => api.revokeConsent(w.id, c.id)));
      replaceWorker({ ...w, [ui.field]: false });
      setNotice(`'${w.display_name}'의 ${ui.label} 철회를 기록했어요.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "동의 철회를 기록하지 못했습니다.");
    }
  }

  async function toggleAiNote(w: Worker, allowed: boolean) {
    setError(null);
    try {
      replaceWorker(await api.updateWorker(w.id, { ai_note_allowed: allowed }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "설정을 바꾸지 못했습니다.");
    }
  }

  // 단계에 들어가면 소리를 한 번 자동으로 읽을지(창업자 결정 4, 기본 켬). 근로자마다 끌 수 있다.
  async function toggleAutoplay(w: Worker, on: boolean) {
    setError(null);
    try {
      replaceWorker(await api.updateWorker(w.id, { a11y_prefs: { autoplay_sound: on } }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "설정을 바꾸지 못했습니다.");
    }
  }

  async function saveNote(w: Worker) {
    const note = noteDrafts[w.id] ?? w.note ?? "";
    setError(null);
    setNotice(null);
    try {
      replaceWorker(await api.updateWorker(w.id, { note }));
      setNoteDrafts(({ [w.id]: _saved, ...rest }) => {
        void _saved;
        return rest;
      });
      setNotice(`'${w.display_name}'의 메모를 저장했어요.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "메모를 저장하지 못했습니다.");
    }
  }

  async function removeWorker(id: string, displayName: string) {
    if (!window.confirm(
      `근로자 '${displayName}'을(를) 삭제할까요?\n이 근로자의 배정·수행 기록·동의 기록도 함께 지워지고 되돌릴 수 없어요.\n`
      + "직무 문장에 적은 이름은 지워지지 않아요 — 직무를 고치거나 지워야 사라져요.\n"
      + "필요하면 먼저 '내보내기'로 데이터를 받아 두세요.",
    )) {
      return;
    }
    setError(null);
    setNotice(null);
    try {
      const result = await api.deleteWorker(id);
      setWorkers((prev) => prev.filter((w) => w.id !== id));
      // 직무 원문·문장·음성은 사업주 데이터라 근로자 삭제로 지우지 않는다. 이름이 남은 직무를 알려 고치게 한다.
      const mentions = result.name_mentions ?? [];
      let message = `근로자 '${displayName}'을(를) 삭제했습니다.`;
      if (mentions.length > 0) {
        const titles = mentions.map((m) => `'${m.title}'`).join(", ");
        message += ` 이 이름이 아직 직무 ${mentions.length}개에 남아 있어요: ${titles}. 직무를 고치거나 지워 주세요.`;
      }
      if (result.wal_checkpointed === false) {
        message += " 다른 화면이 데이터를 읽는 중이라 디스크 정리는 다음 정리 작업 때 끝나요.";
      }
      setNotice(message);
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

      {workplaceCode && (
        <section className="mb-6 rounded-2xl border border-paper-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-bold text-ink-900">사업장 코드</h2>
          <p className="mt-2 font-display text-3xl font-semibold tracking-[0.3em] text-ink-900">{workplaceCode}</p>
          <p className="mt-2 text-xs text-ink-500">
            근로자 기기의 로그인 화면(근로자 탭)에 이 코드를 한 번 입력해 두세요. 그다음부터 근로자는 자기 접속 코드만 누르면 돼요.
          </p>
        </section>
      )}

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
          접속 코드를 비워 두면 겹치지 않는 4자리 숫자를 자동으로 만들어요. 직접 정할 때는 4~12자리 숫자로 입력해 주세요.
        </p>
        {addError && <div role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{addError}</div>}
        {addNotice && <div role="status" className="mt-3 rounded-lg bg-green-50 p-3 text-sm text-green-800">{addNotice}</div>}
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
              <li key={w.id} className="py-3">
                <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 items-center justify-center rounded-full bg-paper-100 text-ink-500">
                    <UserRound size={17} />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-ink-900">{w.display_name}</p>
                    <p className="text-xs text-ink-500">
                      접속 코드 <span className="font-semibold tracking-widest text-ink-900">{accessCodeText(w)}</span>
                      {!w.access_code && <span className="ml-1.5">({ACCESS_CODE_UNKNOWN_HINT})</span>}
                    </p>
                    {w.name_ambiguous && (
                      // 일반 낱말과 같은 이름은 "컵 하나"의 '하나'까지 바꾸지 않으려고 호칭이 붙은 경우만 가린다.
                      <p className="text-xs text-signal-red">
                        이름이 일반 낱말과 같아요. AI에 보낼 직무 문장에는 이름 대신 '근로자'라고 쓰거나 '{w.display_name} 씨'처럼 호칭을 붙여 주세요.
                      </p>
                    )}
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
                  onClick={() => exportWorker(w.id, w.display_name)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-paper-200 px-3 py-1.5 text-sm font-medium text-ink-700 hover:bg-paper-100"
                  aria-label={`근로자 ${w.display_name} 데이터 내보내기`}
                >
                  <Download size={14} />
                  내보내기
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
                </div>
                {/* 개인정보·AI 설정. 동의가 없으면 이 근로자의 기록은 해외 AI로 보내지 않는다(서버가 막는다). */}
                <div className="mt-3 space-y-2 rounded-xl bg-paper-100 px-3 py-2 text-xs text-ink-700">
                  {/* 서비스 이용의 기본 근거. 상태 문구를 AI 처리 줄("기록됨/없음")과 다르게 둬 두 줄을 헷갈리지 않게 한다. */}
                  <div className="flex flex-wrap items-center gap-2">
                    <span>
                      개인정보 수집·이용 동의:{" "}
                      <strong className={w.personal_info_consent ? "text-moss-600" : "text-ink-500"}>
                        {w.personal_info_consent ? "받음" : "미기록"}
                      </strong>
                    </span>
                    {w.personal_info_consent ? (
                      <button
                        onClick={() => revokeConsent(w, "personal_info")}
                        className="rounded-lg border border-paper-200 bg-white px-2 py-1 font-medium"
                        aria-label={`근로자 ${w.display_name} 개인정보 수집·이용 동의 철회 기록`}
                      >
                        동의 철회 기록
                      </button>
                    ) : (
                      (["self", "guardian"] as const).map((subject) => (
                        <button
                          key={subject}
                          onClick={() => recordConsent(w, subject, "personal_info")}
                          className="rounded-lg border border-paper-200 bg-white px-2 py-1 font-medium"
                          aria-label={`근로자 ${w.display_name} ${SUBJECT_LABEL[subject]} 개인정보 수집·이용 동의 기록`}
                        >
                          {SUBJECT_LABEL[subject]} 동의 받음
                        </button>
                      ))
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span>
                      AI 처리 동의:{" "}
                      <strong className={w.ai_consent ? "text-moss-600" : "text-ink-500"}>
                        {w.ai_consent ? "기록됨" : "없음"}
                      </strong>
                    </span>
                    {w.ai_consent ? (
                      <button
                        onClick={() => revokeConsent(w)}
                        className="rounded-lg border border-paper-200 bg-white px-2 py-1 font-medium"
                        aria-label={`근로자 ${w.display_name} AI 처리 동의 철회 기록`}
                      >
                        동의 철회 기록
                      </button>
                    ) : (
                      (["self", "guardian"] as const).map((subject) => (
                        <button
                          key={subject}
                          onClick={() => recordConsent(w, subject)}
                          className="rounded-lg border border-paper-200 bg-white px-2 py-1 font-medium"
                          aria-label={`근로자 ${w.display_name} ${SUBJECT_LABEL[subject]} 동의 기록`}
                        >
                          {SUBJECT_LABEL[subject]} 동의 받음
                        </button>
                      ))
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      value={noteDrafts[w.id] ?? w.note ?? ""}
                      onChange={(e) => setNoteDrafts((prev) => ({ ...prev, [w.id]: e.target.value }))}
                      placeholder="근로자 특성 메모 (예: 그림을 선호함)"
                      aria-label={`근로자 ${w.display_name} 메모`}
                      maxLength={300}
                      className="min-w-0 flex-1 rounded-lg border border-paper-200 bg-white px-2 py-1"
                    />
                    <button
                      onClick={() => saveNote(w)}
                      disabled={noteDrafts[w.id] === undefined}
                      className="rounded-lg border border-paper-200 bg-white px-2 py-1 font-medium disabled:opacity-50"
                      aria-label={`근로자 ${w.display_name} 메모 저장`}
                    >
                      메모 저장
                    </button>
                    <label className="inline-flex items-center gap-1">
                      <input
                        type="checkbox"
                        checked={!!w.ai_note_allowed}
                        onChange={(e) => toggleAiNote(w, e.target.checked)}
                        aria-label={`근로자 ${w.display_name} AI 코칭에 메모 사용`}
                      />
                      AI 코칭에 메모 사용
                    </label>
                    <label className="inline-flex items-center gap-1">
                      <input
                        type="checkbox"
                        role="switch"
                        checked={w.a11y_prefs?.autoplay_sound ?? true}
                        onChange={(e) => toggleAutoplay(w, e.target.checked)}
                        aria-label={`근로자 ${w.display_name} 소리 자동 재생`}
                      />
                      소리 자동 재생
                    </label>
                  </div>
                  {w.ai_note_allowed && !w.ai_consent && (
                    <p className="text-ink-500">AI 처리 동의가 기록되기 전에는 메모를 AI에 보내지 않아요.</p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
