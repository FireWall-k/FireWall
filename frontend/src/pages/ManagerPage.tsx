import { useEffect, useState } from "react";
import { GripVertical, Plus, Trash2 } from "lucide-react";
import { api, type Task, type Worker } from "../api";
import { ActionChip } from "../actions";

const SAMPLE =
  "예: 택배 상자를 크기별로 분류하고, 큰 상자는 A구역으로 옮겨주세요. 그리고 5개씩 쌓아주세요. 마지막에 수량을 확인하세요.";

export default function ManagerPage() {
  const [rawInput, setRawInput] = useState("");
  const [businessType, setBusinessType] = useState("");
  const [workEnvironment, setWorkEnvironment] = useState("");
  const [workerNote, setWorkerNote] = useState("");
  const [task, setTask] = useState<Task | null>(null);
  const [arasaacTerm, setArasaacTerm] = useState("box");
  const [arasaacResult, setArasaacResult] = useState<{ term: string; matches: { language: string; pictogram_id: string; image_url: string }[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // 1:N — 사업주의 근로자 목록 + 배정 대상 선택 + 인라인 추가
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [selectedWorkerId, setSelectedWorkerId] = useState("");
  const [newWorkerName, setNewWorkerName] = useState("");
  const [newWorkerCode, setNewWorkerCode] = useState("");

  // 단계 드래그 정렬 + 단계 직접 추가
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const [newStepSentence, setNewStepSentence] = useState("");

  useEffect(() => {
    api.listWorkers()
      .then((ws) => {
        setWorkers(ws);
        if (ws.length) setSelectedWorkerId((cur) => cur || ws[0].id);
      })
      .catch(() => {
        // 근로자 목록 로드 실패는 직무 작성 자체를 막지 않는다.
      });
  }, []);

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

  async function handleDeleteStep(stepId: string) {
    if (!task) return;
    if (task.steps.length <= 1) {
      setError("마지막 단계는 삭제할 수 없습니다.");
      return;
    }
    if (!window.confirm("이 단계를 삭제할까요?")) return;
    setError(null);
    try {
      setTask(await api.deleteStep(task.id, stepId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "단계 삭제에 실패했습니다.");
    }
  }

  // 드래그로 놓았을 때: 로컬 순서를 즉시 반영(낙관적)하고 서버에 확정 요청.
  async function handleDropOn(toIndex: number) {
    const from = dragIndex;
    setDragIndex(null);
    setDragOverIndex(null);
    if (from === null || from === toIndex || !task) return;
    const reordered = [...task.steps];
    const [moved] = reordered.splice(from, 1);
    reordered.splice(toIndex, 0, moved);
    const prev = task;
    setTask({ ...task, steps: reordered.map((s, i) => ({ ...s, order: i + 1 })) });
    setError(null);
    try {
      setTask(await api.reorderSteps(task.id, reordered.map((s) => s.id)));
    } catch (e) {
      setTask(prev); // 실패 시 원래 순서로 원복
      setError(e instanceof Error ? e.message : "순서 변경에 실패했습니다.");
    }
  }

  async function handleAddStep() {
    if (!task || !newStepSentence.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setTask(await api.addStep(task.id, newStepSentence.trim()));
      setNewStepSentence("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "단계 추가에 실패했습니다.");
    } finally {
      setBusy(false);
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

  async function handleAddWorker() {
    if (!newWorkerName.trim() || !newWorkerCode.trim()) {
      setError("근로자 이름과 접속 코드를 입력해 주세요.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const w = await api.createWorker(newWorkerName.trim(), newWorkerCode.trim());
      setWorkers((prev) => [...prev, w]);
      setSelectedWorkerId(w.id);
      setNewWorkerName("");
      setNewWorkerCode("");
      setNotice(`근로자 '${w.display_name}'을(를) 추가했습니다.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "근로자 추가에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteWorker(workerId: string, name: string) {
    if (!window.confirm(`근로자 '${name}'을(를) 삭제할까요?\n이 근로자의 배정·수행 기록도 함께 삭제됩니다.`)) {
      return;
    }
    setError(null);
    setNotice(null);
    try {
      await api.deleteWorker(workerId);
      const remaining = workers.filter((w) => w.id !== workerId);
      setWorkers(remaining);
      if (selectedWorkerId === workerId) setSelectedWorkerId(remaining[0]?.id ?? "");
      setNotice(`근로자 '${name}'을(를) 삭제했습니다.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "근로자 삭제에 실패했습니다.");
    }
  }

  async function handlePublishAndAssign() {
    if (!task) return;
    if (!selectedWorkerId) {
      setError("보낼 근로자를 선택해 주세요.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (task.status !== "published") {
        await api.publish(task.id);
        setTask({ ...task, status: "published" });
      }
      await api.assign(task.id, selectedWorkerId);
      const w = workers.find((x) => x.id === selectedWorkerId);
      setNotice(`'${w?.display_name ?? "근로자"}'님에게 보냈습니다. 다른 근로자에게도 보낼 수 있어요.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "게시/배정에 실패했습니다.");
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
          placeholder={SAMPLE}
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
            근로자가 보게 될 화면과 같은 순서입니다. 손잡이를 끌어 순서를 바꾸고, 문장을 다듬거나 단계를 추가할 수 있습니다.
          </p>
          <ol className="mt-3 space-y-3">
            {task.steps.map((s, idx) => (
              <li
                key={s.id}
                onDragOver={(e) => {
                  e.preventDefault();
                  if (dragOverIndex !== idx) setDragOverIndex(idx);
                }}
                onDrop={() => handleDropOn(idx)}
                className={
                  "flex items-start gap-2 rounded-lg border bg-white p-3 transition-colors " +
                  (dragOverIndex === idx && dragIndex !== null && dragIndex !== idx
                    ? "border-blue-400 ring-2 ring-blue-200 "
                    : "border-slate-200 ") +
                  (dragIndex === idx ? "opacity-50" : "")
                }
              >
                <span
                  draggable
                  onDragStart={() => setDragIndex(idx)}
                  onDragEnd={() => {
                    setDragIndex(null);
                    setDragOverIndex(null);
                  }}
                  className="mt-1 cursor-grab text-slate-300 hover:text-slate-500 active:cursor-grabbing"
                  aria-label={`${s.order}단계 순서 이동 손잡이`}
                  title="드래그해서 순서 변경"
                >
                  <GripVertical size={18} />
                </span>
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
                <button
                  onClick={() => handleDeleteStep(s.id)}
                  disabled={task.steps.length <= 1}
                  className="mt-1 shrink-0 rounded p-1.5 text-slate-300 hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-slate-300"
                  aria-label={`${s.order}단계 삭제`}
                  title={task.steps.length <= 1 ? "마지막 단계는 삭제할 수 없습니다" : "이 단계 삭제"}
                >
                  <Trash2 size={16} />
                </button>
              </li>
            ))}
          </ol>

          {/* 단계 직접 추가 — 문장을 입력하면 서버가 상징·음성을 붙여 맨 끝에 추가한다 */}
          <div className="mt-3 flex items-center gap-2">
            <input
              className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-base"
              value={newStepSentence}
              onChange={(e) => setNewStepSentence(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleAddStep();
              }}
              placeholder="단계 문장을 입력해 추가 (예: 바닥을 쓸어주세요)"
              aria-label="새 단계 문장"
            />
            <button
              onClick={handleAddStep}
              disabled={busy || !newStepSentence.trim()}
              className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 disabled:opacity-50"
            >
              <Plus size={16} /> 단계 추가
            </button>
          </div>

          <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
            <h3 className="text-sm font-bold text-slate-900">근로자에게 보내기</h3>

            {workers.length > 0 ? (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <select
                  value={selectedWorkerId}
                  onChange={(e) => setSelectedWorkerId(e.target.value)}
                  className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                  aria-label="배정할 근로자 선택"
                >
                  {workers.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.display_name} (코드 {w.access_code})
                    </option>
                  ))}
                </select>
                <button
                  onClick={handlePublishAndAssign}
                  disabled={busy || !selectedWorkerId}
                  className="rounded-lg bg-green-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                >
                  {busy ? "처리 중…" : "게시하고 보내기"}
                </button>
              </div>
            ) : (
              <p className="mt-2 text-sm text-slate-500">
                등록된 근로자가 없습니다. 아래에서 먼저 추가해 주세요.
              </p>
            )}

            {/* 인라인 근로자 추가 (1:N) — 별도 관리 화면 없이 여기서 바로 등록 */}
            <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-200 pt-3">
              <input
                value={newWorkerName} onChange={(e) => setNewWorkerName(e.target.value)}
                placeholder="새 근로자 이름" aria-label="새 근로자 이름"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <input
                value={newWorkerCode} onChange={(e) => setNewWorkerCode(e.target.value)}
                placeholder="접속 코드 (예: 5678)" aria-label="새 근로자 접속 코드"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <button
                onClick={handleAddWorker}
                disabled={busy || !newWorkerName.trim() || !newWorkerCode.trim()}
                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 disabled:opacity-50"
              >
                + 근로자 추가
              </button>
            </div>

            {/* 등록된 근로자 목록 + 삭제 */}
            {workers.length > 0 && (
              <div className="mt-3 border-t border-slate-200 pt-3">
                <p className="mb-2 text-xs font-medium text-slate-500">등록된 근로자</p>
                <ul className="flex flex-wrap gap-2">
                  {workers.map((w) => (
                    <li
                      key={w.id}
                      className="flex items-center gap-1.5 rounded-full border border-slate-200 bg-white py-1 pl-3 pr-1.5 text-sm text-slate-700"
                    >
                      <span>
                        {w.display_name} <span className="text-slate-400">({w.access_code})</span>
                      </span>
                      <button
                        onClick={() => handleDeleteWorker(w.id, w.display_name)}
                        className="rounded-full p-0.5 text-slate-300 hover:bg-red-50 hover:text-red-600"
                        aria-label={`근로자 ${w.display_name} 삭제`}
                        title="근로자 삭제"
                      >
                        <Trash2 size={14} />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
