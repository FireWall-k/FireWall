import React, { useState } from "react";
import { useApp } from "../store/AppStore";
import type { Task, Step } from "../types";
import { StatusBadge } from "../components/StatusBadge";
import { symbolFor } from "../components/Symbols";
import { Sparkles, Pencil, Check, ImageOff, AlertTriangle, Send } from "lucide-react";

export const AdminTasksPage: React.FC = () => {
  const { tasks, createTask, updateStep, publishTask } = useApp();
  const [rawInput, setRawInput] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(tasks[0]?.id ?? null);
  const [isDecomposing, setIsDecomposing] = useState(false);

  const selectedTask = tasks.find((t) => t.id === selectedTaskId);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!rawInput.trim()) return;
    setIsDecomposing(true);
    // POST /api/tasks 의 지연을 흉내냄 (AI 하네스 분해 시간)
    setTimeout(() => {
      const t = createTask(rawInput.trim());
      setSelectedTaskId(t.id);
      setRawInput("");
      setIsDecomposing(false);
    }, 900);
  };

  return (
    <div className="mx-auto max-w-6xl">
      <header className="mb-7">
        <h1 className="font-display text-2xl font-semibold text-ink-900">직무 입력 · 검토</h1>
        <p className="mt-1 text-sm text-ink-500">
          오늘 할 일을 자연어로 입력하면 AI가 단계별 카드로 분해해요. 게시 전에 꼭 확인하고 수정하세요.
        </p>
      </header>

      <div className="grid grid-cols-[380px_1fr] gap-6">
        {/* 좌측: 입력 + 작업 목록 */}
        <div className="flex flex-col gap-5">
          <form
            onSubmit={handleSubmit}
            className="rounded-2xl border border-paper-200 bg-white p-5 shadow-sm"
          >
            <label htmlFor="raw-input" className="mb-2 block text-sm font-semibold text-ink-900">
              오늘의 직무 입력
            </label>
            <textarea
              id="raw-input"
              value={rawInput}
              onChange={(e) => setRawInput(e.target.value)}
              placeholder="예: 택배 상자를 크기별로 분류하고, 큰 상자는 A구역, 작은 상자는 B구역에 5개씩 쌓아주세요."
              rows={5}
              className="w-full resize-none rounded-xl border border-paper-200 bg-paper-50 p-3 text-sm text-ink-900 placeholder:text-ink-500/60 focus:border-moss-500 focus:bg-white focus:outline-none"
            />
            <button
              type="submit"
              disabled={!rawInput.trim() || isDecomposing}
              className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-moss-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-moss-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isDecomposing ? (
                <>
                  <Sparkles size={16} className="animate-pulse" />
                  AI가 단계를 분해하는 중…
                </>
              ) : (
                <>
                  <Sparkles size={16} />
                  AI 분해 요청
                </>
              )}
            </button>
          </form>

          <div className="rounded-2xl border border-paper-200 bg-white p-2 shadow-sm">
            <p className="px-3 pb-2 pt-2 text-xs font-semibold uppercase tracking-wide text-ink-500">
              등록된 직무 ({tasks.length})
            </p>
            <ul className="flex flex-col gap-1">
              {tasks.map((t) => (
                <li key={t.id}>
                  <button
                    onClick={() => setSelectedTaskId(t.id)}
                    className={`w-full rounded-xl px-3 py-2.5 text-left transition-colors ${
                      t.id === selectedTaskId ? "bg-paper-100" : "hover:bg-paper-50"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium text-ink-900">{t.title}</span>
                    </div>
                    <div className="mt-1.5 flex items-center justify-between">
                      <span className="text-xs text-ink-500">{t.steps.length}단계</span>
                      <StatusBadge status={t.status} />
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* 우측: 검토/수정 영역 */}
        <div>
          {selectedTask ? (
            <TaskReview
              task={selectedTask}
              onUpdateStep={(stepId, patch) => updateStep(selectedTask.id, stepId, patch)}
              onPublish={() => publishTask(selectedTask.id)}
            />
          ) : (
            <div className="flex h-64 items-center justify-center rounded-2xl border border-dashed border-paper-200 text-sm text-ink-500">
              왼쪽에서 직무를 입력하거나 선택하세요.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const TaskReview: React.FC<{
  task: Task;
  onUpdateStep: (stepId: string, patch: Partial<Step>) => void;
  onPublish: () => void;
}> = ({ task, onUpdateStep, onPublish }) => {
  const [editingStepId, setEditingStepId] = useState<string | null>(null);
  const [draftSentence, setDraftSentence] = useState("");

  const startEdit = (step: Step) => {
    setEditingStepId(step.id);
    setDraftSentence(step.sentence);
  };

  const saveEdit = (stepId: string) => {
    onUpdateStep(stepId, { sentence: draftSentence });
    setEditingStepId(null);
  };

  return (
    <div className="rounded-2xl border border-paper-200 bg-white p-6 shadow-sm">
      <div className="mb-1 flex items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-lg font-semibold text-ink-900">{task.title}</h2>
          <p className="mt-1 text-sm text-ink-500">원문: {task.rawInput}</p>
        </div>
        <StatusBadge status={task.status} />
      </div>

      <div className="mt-6 flex flex-col gap-3">
        {task.steps.map((step) => {
          const SymbolIcon = symbolFor(step.actionType);
          const isEditing = editingStepId === step.id;
          return (
            <div
              key={step.id}
              className="flex items-start gap-4 rounded-xl border border-paper-200 bg-paper-50/60 p-4"
            >
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-paper-200 text-xs font-bold text-ink-700">
                {step.orderIndex}
              </div>

              <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-lg border border-paper-200 bg-white">
                {step.needsFallback ? (
                  <ImageOff size={22} className="text-ink-500/50" />
                ) : (
                  <SymbolIcon className="h-11 w-11" />
                )}
              </div>

              <div className="flex-1">
                {isEditing ? (
                  <div className="flex items-center gap-2">
                    <input
                      autoFocus
                      value={draftSentence}
                      onChange={(e) => setDraftSentence(e.target.value)}
                      className="flex-1 rounded-lg border border-moss-500 bg-white px-3 py-1.5 text-sm focus:outline-none"
                      onKeyDown={(e) => e.key === "Enter" && saveEdit(step.id)}
                    />
                    <button
                      onClick={() => saveEdit(step.id)}
                      className="flex items-center gap-1 rounded-lg bg-moss-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-moss-600"
                    >
                      <Check size={14} /> 저장
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-medium text-ink-900">{step.sentence}</p>
                    <button
                      onClick={() => startEdit(step)}
                      className="flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-ink-500 hover:bg-paper-200 hover:text-ink-900"
                    >
                      <Pencil size={13} /> 수정
                    </button>
                  </div>
                )}

                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {step.keywords.map((k, i) => (
                    <span key={i} className="rounded-md bg-paper-200 px-2 py-0.5 text-[11px] text-ink-700">
                      {k.term}
                    </span>
                  ))}
                  {step.needsFallback && (
                    <span className="flex items-center gap-1 rounded-md bg-signal-amber/15 px-2 py-0.5 text-[11px] font-medium text-clay-600">
                      <ImageOff size={11} /> 상징 매핑 실패 · 사진 등록 필요
                    </span>
                  )}
                  {step.safetyFlags.includes("hazardous") && (
                    <span className="flex items-center gap-1 rounded-md bg-signal-red/15 px-2 py-0.5 text-[11px] font-medium text-signal-red">
                      <AlertTriangle size={11} /> 위험 동작 확인 필요
                    </span>
                  )}
                  {step.safetyFlags.includes("unclear") && (
                    <span className="flex items-center gap-1 rounded-md bg-signal-amber/15 px-2 py-0.5 text-[11px] font-medium text-clay-600">
                      <AlertTriangle size={11} /> 모호한 표현
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-6 flex items-center justify-between border-t border-paper-200 pt-5">
        <p className="text-xs text-ink-500">
          게시하면 근로자 태블릿에 즉시 노출되고 TTS 음성이 생성돼요.
        </p>
        <button
          onClick={onPublish}
          disabled={task.status === "published"}
          className="flex items-center gap-2 rounded-xl bg-clay-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-clay-600 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Send size={15} />
          {task.status === "published" ? "게시 완료" : "근로자에게 게시"}
        </button>
      </div>
    </div>
  );
};
