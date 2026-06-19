import { useState } from "react";
import { api, type Task } from "../api";
import { ActionChip } from "../actions";

const SAMPLE =
  "택배 상자를 크기별로 분류하고, 큰 상자는 A구역으로 옮겨주세요. 그리고 5개씩 쌓아주세요. 마지막에 수량을 확인하세요.";

export default function ManagerPage() {
  const [rawInput, setRawInput] = useState(SAMPLE);
  const [businessType, setBusinessType] = useState("");
  const [workEnvironment, setWorkEnvironment] = useState("");
  const [workerNote, setWorkerNote] = useState("");
  const [task, setTask] = useState<Task | null>(null);
  const [arasaacTerm, setArasaacTerm] = useState("box");
  const [arasaacResult, setArasaacResult] = useState<{ term: string; matches: { language: string; pictogram_id: string; image_url: string }[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function handleDecompose() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setTask(await api.createTask(rawInput, {
        business_type: businessType.trim() || undefined,
        work_environment: workEnvironment.trim() || undefined,
        worker_note: workerNote.trim() || undefined,
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "분해에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  async function handleEditSentence(stepId: string, sentence: string) {
    if (!task) return;
    const updated = await api.updateStep(task.id, stepId, { sentence });
    setTask({
      ...task,
      steps: task.steps.map((s) => (s.id === stepId ? updated : s)),
    });
  }

  async function handleUploadPhoto(stepId: string, file: File) {
    if (!task) return;
    setError(null);
    try {
      const updated = await api.uploadStepPhoto(task.id, stepId, file);
      setTask({ ...task, steps: task.steps.map((s) => (s.id === stepId ? updated : s)) });
    } catch (e) {
      setError(e instanceof Error ? e.message : "사진 업로드에 실패했습니다.");
    }
  }

  async function handleRemovePhoto(stepId: string) {
    if (!task) return;
    setError(null);
    try {
      const updated = await api.removeStepPhoto(task.id, stepId);
      setTask({ ...task, steps: task.steps.map((s) => (s.id === stepId ? updated : s)) });
    } catch (e) {
      setError(e instanceof Error ? e.message : "사진 제거에 실패했습니다.");
    }
  }

  async function handlePublishAndAssign() {
    if (!task) return;
    setBusy(true);
    setError(null);
    try {
      await api.publish(task.id);
      await api.assign(task.id);
      setNotice("게시하고 근로자에게 배정했습니다. ‘근로자 · 오늘 할 일’ 탭에서 확인하세요.");
      setTask({ ...task, status: "published" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "게시에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  async function handleArasaacSearch() {
    setBusy(true);
    setError(null);
    try {
      setArasaacResult(await api.searchArasaac(arasaacTerm));
    } catch (e) {
      setError(e instanceof Error ? e.message : "ARASAAC 조회에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <section>
        <h1 className="text-xl font-bold text-slate-900">오늘 직무 입력</h1>
        <p className="mt-1 text-sm text-slate-600">
          평소 말하듯 적으면, 각 단계로 나눠 그림과 음성을 붙입니다.
        </p>
        <textarea
          className="mt-3 w-full rounded-lg border border-slate-300 p-3 text-base"
          rows={4}
          value={rawInput}
          onChange={(e) => setRawInput(e.target.value)}
          aria-label="직무 내용"
        />
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
          <input
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            value={businessType} onChange={(e) => setBusinessType(e.target.value)}
            placeholder="업종 (예: 물류, 카페)" aria-label="업종"
          />
          <input
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            value={workEnvironment} onChange={(e) => setWorkEnvironment(e.target.value)}
            placeholder="작업 환경 (예: 창고, 미끄러운 바닥)" aria-label="작업 환경"
          />
          <input
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
            value={workerNote} onChange={(e) => setWorkerNote(e.target.value)}
            placeholder="근로자 특성 (예: 그림 선호)" aria-label="근로자 특성"
          />
        </div>
        <p className="mt-1 text-xs text-slate-400">
          업종·환경·근로자 특성을 적으면 AI가 더 맞춤형으로 단계를 나눕니다(선택).
        </p>
        <button
          onClick={handleDecompose}
          disabled={busy || !rawInput.trim()}
          className="mt-3 rounded-lg bg-blue-700 px-4 py-2 font-semibold text-white disabled:opacity-50"
        >
          {busy ? "처리 중…" : "단계로 나누기"}
        </button>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="text-lg font-bold text-slate-900">ARASAAC 조회</h2>
        <p className="mt-1 text-sm text-slate-600">
          백엔드를 거쳐 ARASAAC pictogram 검색을 직접 확인합니다.
        </p>
        <div className="mt-3 flex gap-2">
          <input
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-base"
            value={arasaacTerm}
            onChange={(e) => setArasaacTerm(e.target.value)}
            aria-label="ARASAAC 검색어"
          />
          <button
            onClick={handleArasaacSearch}
            disabled={busy || !arasaacTerm.trim()}
            className="rounded-lg bg-slate-900 px-4 py-2 font-semibold text-white disabled:opacity-50"
          >
            검색
          </button>
        </div>
        {arasaacResult && (
          <div className="mt-4 space-y-3">
            <div className="text-sm text-slate-600">검색어: {arasaacResult.term}</div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {arasaacResult.matches.map((match) => (
                <a key={`${match.language}-${match.pictogram_id}`} href={match.image_url} target="_blank" rel="noreferrer" className="rounded-lg border border-slate-200 p-3 hover:bg-slate-50">
                  <img src={match.image_url} alt="" className="h-24 w-full rounded border border-slate-100 object-contain" />
                  <div className="mt-2 text-xs text-slate-500">{match.language}</div>
                  <div className="text-sm font-medium text-slate-900">ID {match.pictogram_id}</div>
                </a>
              ))}
              {arasaacResult.matches.length === 0 && (
                <div className="rounded-lg border border-dashed border-slate-300 p-3 text-sm text-slate-500">
                  결과가 없습니다.
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      {error && (
        <div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}
      {notice && (
        <div role="status" className="rounded-lg bg-green-50 p-3 text-sm text-green-800">
          {notice}
        </div>
      )}

      {task && (
        <section>
          <h2 className="text-lg font-bold text-slate-900">
            검토 · 수정 <span className="text-sm font-normal text-slate-500">({task.steps.length}단계)</span>
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            근로자가 보게 될 화면과 같은 순서입니다. 문장을 다듬을 수 있습니다.
          </p>
          <ol className="mt-3 space-y-3">
            {task.steps.map((s) => (
              <li
                key={s.id}
                className="flex items-start gap-3 rounded-lg border border-slate-200 bg-white p-3"
              >
                <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-100 text-sm font-bold text-slate-700">
                  {s.order}
                </span>
                <div className="flex w-16 shrink-0 flex-col items-center gap-1">
                  {s.symbol_url ? (
                    <img src={s.symbol_url} alt={s.sentence}
                         className="h-16 w-16 rounded border border-slate-200 object-contain" />
                  ) : (
                    <div className="flex h-16 w-16 items-center justify-center rounded border border-dashed border-amber-400 bg-amber-50 text-center text-[10px] text-amber-700">
                      사진 권장
                    </div>
                  )}
                  <label className="cursor-pointer text-[11px] font-medium text-blue-700 hover:underline">
                    {s.symbol_source === "photo" ? "사진 교체" : "사진 올리기"}
                    <input
                      type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="hidden"
                      aria-label={`${s.order}단계 사진 업로드`}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) handleUploadPhoto(s.id, f);
                        e.target.value = "";
                      }}
                    />
                  </label>
                  {s.symbol_source === "photo" && (
                    <button onClick={() => handleRemovePhoto(s.id)}
                            className="text-[11px] text-slate-400 hover:text-slate-600 hover:underline">
                      되돌리기
                    </button>
                  )}
                </div>
                <div className="flex-1">
                  <input
                    className="w-full rounded border border-slate-200 px-2 py-1 text-base"
                    defaultValue={s.sentence}
                    aria-label={`${s.order}단계 문장`}
                    onBlur={(e) => {
                      if (e.target.value !== s.sentence) handleEditSentence(s.id, e.target.value);
                    }}
                  />
                  <div className="mt-1 flex items-center gap-2 text-xs text-slate-400">
                    <ActionChip action={s.action_type} className="text-[11px] !px-2 !py-0.5" />
                    <span>상징: {s.symbol_source === "photo" ? "직접 등록한 사진" : s.symbol_source}</span>
                  </div>
                </div>
              </li>
            ))}
          </ol>
          <button
            onClick={handlePublishAndAssign}
            disabled={busy || task.status === "published"}
            className="mt-4 rounded-lg bg-green-700 px-4 py-2 font-semibold text-white disabled:opacity-50"
          >
            {task.status === "published" ? "배정 완료됨" : "게시하고 근로자에게 보내기"}
          </button>
        </section>
      )}
    </div>
  );
}
