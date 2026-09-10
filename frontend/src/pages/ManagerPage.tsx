import { useEffect, useState } from "react";
import { GripVertical, Plus, Trash2 } from "lucide-react";
import { api, type AacMatch, type StepSymbolCandidates, type Task, type Worker } from "../api";
import { ActionChip } from "../actions";

const SAMPLE =
  "예: 택배 상자를 크기별로 분류하고, 큰 상자는 A구역으로 옮겨주세요. 그리고 5개씩 쌓아주세요. 마지막에 수량을 확인하세요.";

export default function ManagerPage() {
  const [rawInput, setRawInput] = useState("");
  const [businessType, setBusinessType] = useState("");
  const [workEnvironment, setWorkEnvironment] = useState("");
  const [workerNote, setWorkerNote] = useState("");
  const [task, setTask] = useState<Task | null>(null);
  const [aacQuery, setAacQuery] = useState("상품을 선반에 놓는다");

  const [aacResult, setAacResult] = useState<{
    query: string;
    matches: {
      asset_id: string;
      group_id: string;
      job: string;
      asset_type: string;
      label: string;
      image_url: string;
      score: number;
    }[];
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // 1:N — 사업주의 근로자 목록 + 배정 대상 선택 + 인라인 추가
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [selectedWorkerId, setSelectedWorkerId] = useState("");
  const [newWorkerName, setNewWorkerName] = useState("");
  const [newWorkerCode, setNewWorkerCode] = useState("");

  // 그림을 자동으로 못 고른 단계의 후보 목록 (stepId -> 후보/사유)
  const [stepCandidates, setStepCandidates] = useState<Record<string, StepSymbolCandidates>>({});

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

  // 그림이 안 붙은 단계의 후보를 가져온다. 서버가 자동 채택을 못 한 경우
  // (후보 점수가 붙어 있어 고르지 못함) 사업주가 직접 고를 수 있게 한다.
  useEffect(() => {
    if (!task) return;
    let cancelled = false;
    const pending = task.steps.filter((s) => s.needs_fallback && !stepCandidates[s.id]);
    if (pending.length === 0) return;

    (async () => {
      const fetched = await Promise.all(
        pending.map((s) =>
          api.stepSymbolCandidates(task.id, s.id).catch(
            // 실패해도 빈 결과를 기록해 둔다. 기록하지 않으면 이 단계가 계속
            // pending으로 남아 effect가 무한히 다시 조회한다.
            (): StepSymbolCandidates => ({
              step_id: s.id,
              reason: "no_candidate",
              candidates: [],
            }),
          ),
        ),
      );
      if (cancelled) return;
      setStepCandidates((prev) => {
        const next = { ...prev };
        fetched.forEach((c) => {
          next[c.step_id] = c;
        });
        return next;
      });
    })();

    return () => {
      cancelled = true;
    };
  }, [task, stepCandidates]);

  async function handleEditSentence(stepId: string, sentence: string) {
    if (!task) return;
    const updated = await api.updateStep(task.id, stepId, { sentence });
    setTask({
      ...task,
      steps: task.steps.map((s) => (s.id === stepId ? updated : s)),
    });
    // 문장이 바뀌면 후보도 달라진다. 캐시를 버려 다시 받아오게 한다.
    setStepCandidates((prev) => {
      const next = { ...prev };
      delete next[stepId];
      return next;
    });
  }

  async function handlePickCandidate(stepId: string, match: AacMatch) {
    if (!task) return;
    setError(null);
    try {
      const updated = await api.updateStep(task.id, stepId, {
        symbol_url: match.image_url,
        symbol_source: "LOCAL_AAC",
      });
      setTask({ ...task, steps: task.steps.map((s) => (s.id === stepId ? updated : s)) });
    } catch (e) {
      setError(e instanceof Error ? e.message : "그림 선택에 실패했습니다.");
    }
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

  async function handleAacSearch() {
    if (!aacQuery.trim()) return;

    try {
      setBusy(true);
      setError(null);

      const result = await api.searchAac(
        aacQuery.trim(),
        undefined,
        5,
      );

      setAacResult(result);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "AAC 검색에 실패했습니다.",
      );
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
        <h2 className="text-lg font-bold text-slate-900">
          자체 AAC 검색
        </h2>

        <p className="mt-1 text-sm text-slate-600">
          프로젝트에서 제작한 직무 AAC 이미지 중
          작업 문장과 가장 가까운 이미지를 검색합니다.
        </p>

        <div className="mt-3 flex gap-2">
          <input
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-base"
            value={aacQuery}
            onChange={(e) => setAacQuery(e.target.value)}
            aria-label="AAC 검색어"
            placeholder="예: 상품을 선반에 놓는다"
          />

          <button
            onClick={handleAacSearch}
            disabled={busy || !aacQuery.trim()}
            className="rounded-lg bg-slate-900 px-4 py-2 font-semibold text-white disabled:opacity-50"
          >
            검색
          </button>
        </div>

        {aacResult && (
          <div className="mt-4 space-y-3">
            <div className="text-sm text-slate-600">
              검색어: {aacResult.query}
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {aacResult.matches.map((match) => (
                <a
                  key={match.asset_id}
                  href={match.image_url}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-lg border border-slate-200 p-3 hover:bg-slate-50"
                >
                  <img
                    src={match.image_url}
                    alt={match.label}
                    className="h-32 w-full rounded border border-slate-100 object-contain"
                  />

                  <div className="mt-2 text-xs text-slate-500">
                    {match.job}
                  </div>

                  <div className="text-sm font-medium text-slate-900">
                    {match.label}
                  </div>

                  <div className="mt-1 text-xs text-slate-400">
                    {match.asset_id}
                  </div>

                  <div className="text-xs text-slate-400">
                    유사도 {Math.round(match.score * 100)}%
                  </div>
                </a>
              ))}

              {aacResult.matches.length === 0 && (
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
                    // 아래 후보 영역이 "그림 고르기"를 안내하는 동안에는 "사진 권장"을
                    // 함께 띄우지 않는다(상충). 후보가 없을 때만 사진을 권한다.
                    <div className={
                      "flex h-16 w-16 items-center justify-center rounded border border-dashed text-center text-[10px] "
                      + (stepCandidates[s.id]?.candidates.length
                         ? "border-slate-300 bg-slate-50 text-slate-400"
                         : "border-amber-400 bg-amber-50 text-amber-700")
                    }>
                      {stepCandidates[s.id]?.candidates.length ? "그림 선택" : "사진 권장"}
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

                  {/* 자동으로 못 고른 단계 — 재조회 결과에 따라 다르게 안내한다.
                      accepted : 쓸 만한 매칭을 찾음 → 한 번에 적용
                      low_margin: 비슷한 게 여럿 → 사업주가 선택
                      그 외    : 쓸 만한 그림 없음 → 현장 사진 권장 */}
                  {s.needs_fallback && stepCandidates[s.id] && (() => {
                    const sc = stepCandidates[s.id];
                    if (sc.reason === "accepted" && sc.candidates.length === 1) {
                      const c = sc.candidates[0];
                      return (
                        <div className="mt-2 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-2">
                          <img src={c.image_url} alt={c.label}
                               className="h-14 w-14 shrink-0 rounded border border-slate-200 object-contain" />
                          <div className="min-w-0 flex-1">
                            <p className="text-[11px] font-medium text-emerald-800">
                              찾은 그림이 있어요: {c.label}
                            </p>
                            <button type="button" onClick={() => handlePickCandidate(s.id, c)}
                                    className="mt-1 rounded bg-emerald-600 px-2 py-0.5 text-[11px] font-medium text-white hover:bg-emerald-700">
                              이 그림 적용
                            </button>
                          </div>
                        </div>
                      );
                    }
                    if (sc.candidates.length > 0) {
                      // low_margin: 후보들이 다 그럴듯한데 순위만 못 매김
                      // low_score : 딱 맞는 건 없지만 비슷한 걸 보여주고 판단을 맡김
                      const tie = sc.reason === "low_margin";
                      return (
                        <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2">
                          <p className="text-[11px] font-medium text-amber-800">
                            {tie
                              ? "비슷한 그림이 여러 개예요. 맞는 것을 골라 주세요."
                              : "딱 맞는 그림이 없어요. 아래에서 고르거나 현장 사진을 올리세요."}
                          </p>
                          <div className="mt-1.5 flex flex-wrap gap-2">
                            {sc.candidates.map((c) => (
                              <button key={c.asset_id} type="button"
                                      onClick={() => handlePickCandidate(s.id, c)}
                                      className="w-20 rounded border border-slate-200 bg-white p-1 text-left hover:border-blue-400 hover:ring-2 hover:ring-blue-200"
                                      title={`${c.label} 선택`}>
                                <img src={c.image_url} alt={c.label}
                                     className="h-16 w-full rounded object-contain" />
                                <span className="mt-0.5 block text-[10px] leading-tight text-slate-600">
                                  {c.label}
                                </span>
                              </button>
                            ))}
                          </div>
                        </div>
                      );
                    }
                    return (
                      <p className="mt-2 text-[11px] text-amber-700">
                        맞는 그림이 없어요. 실제 현장 사진을 올리면 가장 잘 전달됩니다.
                      </p>
                    );
                  })()}
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
