// 새 직무(/m/tasks/new, 명세 5.4·3.4-A, tasks §4.3). 가운데 720 한 칸.
// '어떤 일을 시킬까요?'에 평소 말투로 적고 [단계로 나누기] → 같은 화면 아래 나눈 단계 목록에서 합치기·더 나누기·고치기 →
// [이대로 그림 고르기]를 누르면 초안을 만들고(서버가 그림·목소리를 붙임) 편집기(/m/tasks/:id)로 간다.
// 초안을 만드는 동안은 편집기 모양 스켈레톤을 보인다. 원문과 '더 알려 주기'는 이 기기에 임시 저장한다(새로고침해도 남음).
// 옛 ManagerPage에서 옮긴 것: 나누는 동안 단추 잠금·초점 이동(나눈 뒤 '이렇게 나눴어요' 제목, 실패하면 [단계로 나누기]),
// 목록을 고쳤으면 다시 나누기 전에 묻기(Dialog), 원문을 고치면 다시 나누라는 알림, 맞춤 대상 근로자 worker_id.
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronDown, Info } from "lucide-react";
import type { Worker } from "../../../api";
import { Button, Dialog, Field, Input, Select, Textarea } from "../../../components/ui";
import { cn } from "../../../cn";
import { editorApi } from "../../api/editor";
import type { EditorTask } from "../../api/types";
import { newTask as copy } from "../../copy";
import EditorSkeleton from "../editor/EditorSkeleton";
import { EXAMPLE_TASK } from "../example";
import { errorMessage } from "../listHelpers";
import { clearDraft, EMPTY_DRAFT, readDraft, readSavedPreview, writeDraft, writeSavedPreview, type NewTaskDraft } from "./draft";
import SplitPreviewList from "./SplitPreviewList";
import { rowsFromPreview, toCreateSteps, type SplitRow } from "./splitRows";
import { useLeaveGuard } from "./useLeaveGuard";

/** 원문 최대 글자 수(서버 MAX_RAW_INPUT). */
export const MAX_RAW_INPUT = 2000;

interface Preview {
  title: string;
  job: string;
  /** 이 목록을 만든 원문 — 원문을 고치면 다시 나누라고 알린다. */
  input: string;
  rows: SplitRow[];
  /** 서버가 준 처음 줄 글(사업주가 목록을 고쳤는지 보려고 둔다). */
  initial: string[];
}

export interface NewTaskPageProps {
  /** 주소에 ?example=1이 있으면 예시로 채운다(직무 목록 빈 상태 [예시로 만들어 보기]). */
  example?: boolean;
  /** 초안을 만든 뒤. 같은 Route가 편집기로 바꿔 그린다(contract §2.2). */
  onCreated: (task: EditorTask) => void;
}

function isPreview(v: unknown): v is Preview {
  if (!v || typeof v !== "object") return false;
  const p = v as Partial<Preview>;
  return (
    typeof p.title === "string" && typeof p.job === "string" && typeof p.input === "string" &&
    Array.isArray(p.initial) && p.initial.every((t) => typeof t === "string") &&
    Array.isArray(p.rows) && p.rows.length > 0 &&
    p.rows.every((r) => !!r && typeof r === "object" && typeof r.key === "string" && typeof r.text === "string" &&
      typeof r.original === "string" && typeof r.actionType === "string")
  );
}

function initialDraft(example: boolean): { draft: NewTaskDraft; restored: boolean } {
  if (example) return { draft: { ...EMPTY_DRAFT, rawInput: EXAMPLE_TASK.rawInput, businessType: EXAMPLE_TASK.businessType }, restored: false };
  const saved = readDraft();
  return saved ? { draft: saved, restored: true } : { draft: EMPTY_DRAFT, restored: false };
}

export default function NewTaskPage({ example = false, onCreated }: NewTaskPageProps) {
  const navigate = useNavigate();
  const [start] = useState(() => initialDraft(example));
  const [draft, setDraft] = useState<NewTaskDraft>(start.draft);
  const [moreOpen, setMoreOpen] = useState(
    () => !!(start.draft.businessType || start.draft.workEnvironment || start.draft.workerNote || start.draft.noteWorkerId),
  );
  const [workers, setWorkers] = useState<Worker[]>([]);
  // 이 기기에 둔 나눈 목록은 원문이 함께 돌아왔을 때만 되살린다(예시로 열면 버린다).
  const [preview, setPreview] = useState<Preview | null>(() => (start.restored ? readSavedPreview(isPreview) : null));
  const [splitting, setSplitting] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [askResplit, setAskResplit] = useState(false);
  const decomposeButton = useRef<HTMLButtonElement | null>(null);
  const focusAfterSplit = useRef(false);
  const hintId = useId();
  const countId = useId();

  const set = (k: keyof NewTaskDraft) => (v: string) => setDraft((d) => ({ ...d, [k]: v }));

  // 적는 대로 이 기기에 둔다(예시로 채운 글은 사업주가 고칠 때부터).
  const firstWrite = useRef(true);
  useEffect(() => {
    if (firstWrite.current) {
      firstWrite.current = false;
      if (example) return;
    }
    writeDraft(draft);
  }, [draft, example]);
  const firstPreviewWrite = useRef(true);
  useEffect(() => {
    if (firstPreviewWrite.current) {
      firstPreviewWrite.current = false;
      if (example) return;
    }
    writeSavedPreview(preview);
  }, [preview, example]);

  useEffect(() => {
    let alive = true;
    editorApi
      .listWorkers()
      .then((ws) => alive && setWorkers(ws))
      .catch(() => {
        // 근로자 목록을 못 불러와도 직무 만들기는 막지 않는다(맞춤 대상 고르기만 숨는다).
      });
    return () => {
      alive = false;
    };
  }, []);

  const dirty = !!draft.rawInput.trim() || !!preview;
  const leave = useLeaveGuard(dirty && !creating);

  const previewEdited =
    !!preview && (preview.rows.length !== preview.initial.length || preview.rows.some((r, i) => r.text !== preview.initial[i]));
  const previewStale = !!preview && draft.rawInput !== preview.input;

  const context = () => ({
    business_type: draft.businessType.trim() || undefined,
    work_environment: draft.workEnvironment.trim() || undefined,
    worker_note: draft.workerNote.trim() || undefined,
    worker_id: draft.noteWorkerId || undefined,
  });

  // 키보드로 누른 단추가 꺼지는 동안 초점이 body로 빠지지 않게: 나누기가 끝난 커밋 바로 뒤에, 초점을 잃었을 때만 옮긴다.
  useLayoutEffect(() => {
    if (!focusAfterSplit.current || splitting) return;
    focusAfterSplit.current = false;
    const active = document.activeElement as HTMLElement | null;
    const lost = !active || active === document.body || !active.isConnected
      || (active instanceof HTMLButtonElement && (active.disabled || active.getAttribute("aria-disabled") === "true"));
    if (!lost) return;
    const heading = preview ? document.getElementById("split-preview-title") : null;
    (heading ?? decomposeButton.current)?.focus();
  });

  function requestSplit() {
    if (previewEdited) {
      setAskResplit(true);
      return;
    }
    void runSplit();
  }

  async function runSplit() {
    setAskResplit(false);
    focusAfterSplit.current = true;
    setSplitting(true);
    setError(null);
    setConfirmError(null);
    try {
      const input = draft.rawInput;
      const result = await editorApi.splitPreview(input, context());
      if (!result.steps.length) {
        setPreview(null);
        setError(copy.splitEmpty);
        return;
      }
      const rows = rowsFromPreview(result.steps);
      setPreview({ title: result.task_title, job: result.job, input, rows, initial: rows.map((r) => r.text) });
    } catch (e) {
      setError(errorMessage(e) || copy.splitFailed);
    } finally {
      setSplitting(false);
    }
  }

  async function handleCreate() {
    if (!preview) return;
    setCreating(true);
    setConfirmError(null);
    setError(null);
    try {
      const created = await editorApi.createTask(preview.input, {
        ...context(),
        title: preview.title,
        job: preview.job || undefined,
        steps: toCreateSteps(preview.rows),
      });
      clearDraft();
      onCreated(created);
    } catch (e) {
      setCreating(false);
      setConfirmError(errorMessage(e) || copy.createFailed);
    }
  }

  function fillExample() {
    setDraft((d) => ({ ...d, rawInput: EXAMPLE_TASK.rawInput, businessType: d.businessType || EXAMPLE_TASK.businessType }));
  }

  if (creating) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="sr-only">{copy.heading}</h1>
        <EditorSkeleton mode="creating" rows={preview?.rows.length} />
      </div>
    );
  }

  const canSplit = !!draft.rawInput.trim() && !splitting && !(preview && !previewStale && !previewEdited);

  return (
    <div className="mx-auto flex w-full max-w-[720px] flex-col gap-5">
      <h1 className="text-ui-xl text-ink-900">{copy.heading}</h1>

      {example && !preview && (
        <p data-testid="example-note" role="status" className="rounded-control bg-paper-100 px-3 py-2 text-ui-base text-ink-900">
          {copy.exampleNote}
        </p>
      )}
      {start.restored && !example && !preview && (
        <p role="status" className="rounded-control bg-paper-100 px-3 py-2 text-ui-base text-ink-900">
          {copy.restored}
        </p>
      )}

      <section className="flex flex-col gap-2">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <label htmlFor="new-task-input" className="text-ui-md font-bold text-ink-900">
            {copy.label}
          </label>
          <button
            type="button"
            onClick={fillExample}
            className="min-h-control text-ui-base font-semibold text-info-700 underline underline-offset-2 coarse:min-h-control-coarse"
          >
            {copy.fillExample}
          </button>
        </div>
        <p id={hintId} className="text-ui-sm text-ink-700">
          {copy.hint}
        </p>
        <Textarea
          id="new-task-input"
          rows={8}
          value={draft.rawInput}
          maxLength={MAX_RAW_INPUT}
          onChange={(e) => set("rawInput")(e.target.value)}
          placeholder={copy.placeholder}
          aria-describedby={`${hintId} ${countId}`}
          className="resize-y text-ui-md"
        />
        <p id={countId} className="self-end text-ui-sm tabular-nums text-ink-700">
          {copy.charCount(draft.rawInput.length, MAX_RAW_INPUT)}
        </p>
      </section>

      <section className="rounded-card border border-paper-200 bg-white">
        <button
          type="button"
          aria-expanded={moreOpen}
          aria-controls="new-task-more"
          onClick={() => setMoreOpen((v) => !v)}
          className="flex min-h-11 w-full items-center justify-between gap-2 px-4 text-left text-ui-md font-semibold text-ink-900"
        >
          {copy.more}
          <ChevronDown size={20} strokeWidth={2} aria-hidden="true" className={cn("shrink-0 transition-transform duration-hover", moreOpen && "rotate-180")} />
        </button>
        <div id="new-task-more" hidden={!moreOpen} className="flex flex-col gap-4 border-t border-paper-200 p-4">
          <Field label={copy.businessType} hint={copy.businessTypeHint}>
            <Input value={draft.businessType} maxLength={100} onChange={(e) => set("businessType")(e.target.value)} />
          </Field>
          <Field label={copy.workEnvironment} hint={copy.workEnvironmentHint}>
            <Input value={draft.workEnvironment} maxLength={300} onChange={(e) => set("workEnvironment")(e.target.value)} />
          </Field>
          <Field label={copy.workerNote} hint={copy.workerNoteHint}>
            <Input value={draft.workerNote} maxLength={300} onChange={(e) => set("workerNote")(e.target.value)} />
          </Field>
          {workers.length > 0 && (
            <Field label={copy.noteWorker} hint={copy.noteWorkerHint}>
              <Select value={draft.noteWorkerId} onChange={(e) => set("noteWorkerId")(e.target.value)}>
                <option value="">{copy.noteWorkerNone}</option>
                {workers.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.display_name}
                  </option>
                ))}
              </Select>
            </Field>
          )}
        </div>
      </section>

      <p className="flex items-start gap-2 rounded-control border border-info-700/20 bg-white px-3 py-2 text-ui-sm text-ink-700">
        <Info size={16} strokeWidth={2} aria-hidden="true" className="mt-0.5 shrink-0 text-info-700" />
        {copy.privacy}
      </p>

      <div className="flex flex-col gap-3">
        <Button
          ref={decomposeButton}
          variant="primary"
          onClick={requestSplit}
          disabled={!canSplit && !splitting}
          loading={splitting}
          className="!min-h-11 self-start px-5 text-ui-md"
        >
          {copy.split}
        </Button>
        {splitting && (
          <p role="status" className="text-ui-base font-semibold text-ink-700">
            {copy.splitting}
          </p>
        )}
        {error && (
          <p role="alert" className="rounded-control bg-danger-50 p-3 text-ui-base font-semibold text-danger-700">
            {error}
          </p>
        )}
      </div>

      {preview && !splitting && (
        <SplitPreviewList
          rows={preview.rows}
          onChange={(rows) => setPreview((cur) => (cur ? { ...cur, rows } : cur))}
          onConfirm={handleCreate}
          confirming={creating}
          stale={previewStale}
          confirmError={confirmError}
        />
      )}

      <Dialog
        open={askResplit}
        onClose={() => setAskResplit(false)}
        title={copy.resplitTitle}
        description={copy.resplitBody}
        confirmLabel={copy.resplitConfirm}
        onConfirm={() => void runSplit()}
      />
      <Dialog
        open={!!leave.pending}
        onClose={leave.cancel}
        title={copy.leaveTitle}
        description={copy.leaveBody}
        cancelLabel={copy.leaveCancel}
        confirmLabel={copy.leaveConfirm}
        onConfirm={() => {
          const p = leave.pending;
          leave.clear();
          clearDraft();
          if (p?.to) navigate(p.to);
          else p?.go?.();
        }}
      />
    </div>
  );
}
