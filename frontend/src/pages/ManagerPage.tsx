import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { GripVertical, Plus, Trash2 } from "lucide-react";
import { IconHide, IconShow } from "../ui/icons";
import { maskedCode } from "../workerCodes";
import { api, type AacMatch, type Step, type StepSymbolCandidates, type Task, type Worker } from "../api";
import { ActionChip } from "../actions";
import { accessCodeText } from "../workerCodes";
import { mergeStepMedia, useMediaRefresh } from "../media";
import { cn } from "../cn";
import SplitPreviewList from "../components/SplitPreviewList";
import { rowsFromPreview, toConfirmed, type SplitRow } from "../splitRows";
import { blockedStepIdsAfterSendError, sendApi } from "../manager/api/send";
import { EXAMPLE_TASK } from "../manager/tasks/example";

// 문장 칸 높이를 내용에 맞춘다(SplitPreviewList와 같은 방식).
function fitHeight(el: HTMLTextAreaElement) {
  el.style.height = "auto";
  // border-box라 높이에 테두리를 더해야 글 칸(clientHeight)이 글 높이(scrollHeight)와 같아진다.
  if (el.scrollHeight > 0) el.style.height = `${el.scrollHeight + el.offsetHeight - el.clientHeight}px`;
}

const SAMPLE =
  "예: 택배 상자를 크기별로 분류하고, 큰 상자는 A구역으로 옮겨주세요. 그리고 5개씩 쌓아주세요. 마지막에 수량을 확인하세요.";

// 주소에 ?example=1이 있으면 예시로 채운다. 옛 화면 시험은 라우터 없이 그리므로 useSearchParams 대신 location을 읽는다.
function wantsExample(): boolean {
  try {
    return new URLSearchParams(window.location.search).get("example") === "1";
  } catch {
    return false;
  }
}

export default function ManagerPage() {
  const [fromExample] = useState(wantsExample);
  const [rawInput, setRawInput] = useState(() => (fromExample ? EXAMPLE_TASK.rawInput : ""));
  const [businessType, setBusinessType] = useState(() => (fromExample ? EXAMPLE_TASK.businessType : ""));
  const [workEnvironment, setWorkEnvironment] = useState("");
  const [workerNote, setWorkerNote] = useState("");
  // 맞춤 대상 근로자. 근로자 특성 메모는 이 근로자가 "AI 코칭에 메모 사용"을 허용하고 AI 처리 동의가
  // 기록된 경우에만 서버가 AI로 보낸다(그 밖에는 서버가 메모를 버린다).
  const [noteWorkerId, setNoteWorkerId] = useState("");
  const [task, setTask] = useState<Task | null>(null);
  // 업로드 사진의 서명 URL은 만료된다(검토 화면을 오래 열어 둔 경우). 못 불러오면 직무를 다시 받아 URL만 바꾼다.
  const onMediaError = useMediaRefresh(async () => {
    if (!task) return;
    const fresh = await api.getTask(task.id);
    setTask((cur) => (cur && cur.id === fresh.id ? mergeStepMedia([cur], [fresh])[0] : cur));
  });
  const [aacQuery, setAacQuery] = useState("");

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

  // 입력 화면 나누기 결과(직무를 만들기 전). 한 줄 = 한 동작 = 그림 1장. [이대로 그림 고르기]를 눌러야
  // 이 목록으로 초안을 만든다. input은 이 목록을 만든 원문 — 원문을 고치면 다시 나누라고 알려 준다.
  // initial: 서버가 준 처음 줄 글(사업주가 목록을 고쳤는지 보려고 둔다 — 다시 나누면 고친 것이 사라진다).
  const [preview, setPreview] = useState<{
    title: string; job: string; input: string; rows: SplitRow[]; initial: string[];
  } | null>(null);
  const [splitting, setSplitting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  // [이대로 그림 고르기] 실패 이유 — 목록의 확인 버튼 바로 아래에 보인다.
  const [confirmError, setConfirmError] = useState<string | null>(null);
  // 편집기에서 문장을 고쳐 저장하거나 단계를 추가하며 두 단계로 나눈 경우 [되돌리기]용
  // (새 단계 id들 + 사업주가 적은 문장 + 나누기 전 동작 종류).
  const [splitUndo, setSplitUndo] = useState<{ stepIds: string[]; sentence: string; actionType?: string } | null>(null);
  // 편집기 문장을 저장(나누기 확인 포함)하는 중인 단계. 그동안 다른 문장 칸은 읽기 전용이다 — 응답이 직무 전체를
  // 바꾸므로, 기다리는 사이 고친 다른 줄이 덮어써지지 않게.
  const [rewritingId, setRewritingId] = useState<string | null>(null);
  const errorBox = useRef<HTMLDivElement | null>(null);
  const editorHeading = useRef<HTMLHeadingElement | null>(null);

  // 1:N — 사업주의 근로자 목록 + 배정 대상(여러 명) 선택 + 인라인 추가
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [selectedWorkerIds, setSelectedWorkerIds] = useState<Set<string>>(new Set());
  const [newWorkerName, setNewWorkerName] = useState("");
  const [newWorkerCode, setNewWorkerCode] = useState("");
  // 인라인 근로자 추가 결과는 그 입력칸 바로 아래에 보여 준다. 화면 맨 위 배너에 띄우면 아래쪽 폼을 보고 있는
  // 사업주에게 보이지 않았다(사용자 피드백). 배정 결과(assignFeedback)와 같은 방식이다.
  const [addWorkerFeedback, setAddWorkerFeedback] = useState<{ ok: boolean; text: string } | null>(null);

  // "보내기" 결과를 버튼 바로 아래에도 보여준다 — 상단 배너(notice)는 직무 내용이 길면
  // 스크롤 밖으로 벗어나 눈에 안 띄기 때문에(실사용에서 발견), 버튼 옆에 한 번 더 알려준다.
  const [assignFeedback, setAssignFeedback] = useState<{ ok: boolean; text: string } | null>(null);
  const assignFeedbackTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (assignFeedbackTimer.current) clearTimeout(assignFeedbackTimer.current); }, []);

  function flashAssignFeedback(ok: boolean, text: string) {
    setAssignFeedback({ ok, text });
    if (assignFeedbackTimer.current) clearTimeout(assignFeedbackTimer.current);
    // 성공 메시지는 잠시 후 저절로 사라진다(계속 남아 있으면 "또 보낸 건가?" 헷갈릴 수 있어서).
    // 실패 메시지는 사용자가 알아챌 때까지 남겨둔다.
    if (ok) assignFeedbackTimer.current = setTimeout(() => setAssignFeedback(null), 5000);
  }

  function toggleWorkerSelected(id: string) {
    setSelectedWorkerIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // 그림을 자동으로 못 고른 단계의 후보 목록 (stepId -> 후보/사유)
  const [stepCandidates, setStepCandidates] = useState<Record<string, StepSymbolCandidates>>({});
  // 사업주가 "맞다"고 확인한 단계. 자동으로 고른 그림은 최종 평가에서 약 10%가 틀렸다 —
  // 확인 없이 게시하면 틀린 그림이 그대로 근로자에게 간다. 직접 고른 후보·사진은 이미 본 것이라 확인으로 친다.
  // (2a-0) 확인 여부는 서버의 그림 상태(picture_state='confirmed')를 따른다 — 처음 값도 서버 값이다. 서버가 확인 안 한
  // 자동 그림을 보내기에서 막으므로(422), 화면만 확인함으로 알고 있으면 보내기가 서버에서 막혔다. 서버가 그림 상태를
  // 주지 않는 단계(예전 서버·목)만 이 화면에서 누른 기록(confirmedSteps)을 쓴다.
  const [confirmedSteps, setConfirmedSteps] = useState<Set<string>>(new Set());
  // 확인 API를 기다리는 단계(누르자마자 확인함으로 보인다).
  const [pendingConfirm, setPendingConfirm] = useState<Set<string>>(new Set());
  // 이 화면에서 문장을 고친 단계 — 서버는 그림이 그대로면 확인함을 유지하지만, 문장이 바뀌었으니 그림이 여전히
  // 맞는지 사업주가 다시 보게 한다(예전 동작 유지). [그림 확인]을 다시 누르면 빠진다.
  const [recheckSteps, setRecheckSteps] = useState<Set<string>>(new Set());
  // (2a-0) 보내기가 서버 검사(422·409)에 막혔을 때 그 이유가 된 단계. 서버가 막았으니 이 화면이 확인함으로 알고 있어도
  // 확인하지 않은 것으로 보고 다시 확인하게 한다. 그 단계를 고치면(그림 확인·후보 고르기·사진) 강조를 내린다.
  const [blockedStepIds, setBlockedStepIds] = useState<Set<string>>(new Set());
  const isConfirmed = (s: Step) => !recheckSteps.has(s.id) && !blockedStepIds.has(s.id) && (s.picture_state
    ? s.picture_state === "confirmed" || pendingConfirm.has(s.id)
    : confirmedSteps.has(s.id));
  const withId = (prev: Set<string>, id: string) => (prev.has(id) ? prev : new Set(prev).add(id));
  const withoutId = (prev: Set<string>, id: string) => {
    if (!prev.has(id)) return prev;
    const next = new Set(prev);
    next.delete(id);
    return next;
  };
  // 후보를 고르거나 사진을 올린 단계: 서버도 확인함으로 적었다.
  const confirmStep = (stepId: string) => {
    setBlockedStepIds((prev) => withoutId(prev, stepId));
    setRecheckSteps((prev) => withoutId(prev, stepId));
    setConfirmedSteps((prev) => withId(prev, stepId));
  };
  // 문장을 고친 단계: 그림을 다시 확인하게 한다.
  const unconfirmStep = (stepId: string) => {
    setRecheckSteps((prev) => withId(prev, stepId));
    setConfirmedSteps((prev) => withoutId(prev, stepId));
  };
  // [그림 확인]: 서버에 확인을 적고(POST …/picture/confirm), 돌려받은 단계로 바꾼다. 실패하면 확인하지 않은 채로 두고
  // 오류를 보인다(화면만 확인함이 되면 보내기가 서버에서 막힌다).
  async function handleConfirmPicture(stepId: string) {
    if (!task) return;
    const taskId = task.id;
    const wasRecheck = recheckSteps.has(stepId);
    const wasBlocked = blockedStepIds.has(stepId);
    setError(null);
    // 누른 단추가 곧 사라진다 — 초점은 아래 useLayoutEffect가 다음 확인 단추(없으면 이 단계 문장 칸)로 옮긴다.
    focusAfterConfirm.current = { stepId, back: false };
    setPendingConfirm((prev) => withId(prev, stepId));
    confirmStep(stepId);
    try {
      const updated = await sendApi.confirmPicture(taskId, stepId);
      setTask((cur) => (cur && cur.id === taskId
        ? { ...cur, steps: cur.steps.map((s) => (s.id === stepId ? { ...s, ...updated } : s)) }
        : cur));
      // 서버가 확인함으로 적었다. 그사이 보내기가 막혀(422) 이 단계를 강조했어도 이제 내린다(1회차 검증 — 확인 요청보다
      // 보내기가 먼저 도착하면 이미 확인한 그림을 다시 확인하라고 했다).
      if (updated.picture_state === undefined || updated.picture_state === "confirmed") {
        setBlockedStepIds((prev) => withoutId(prev, stepId));
      }
    } catch (e) {
      if (wasRecheck) setRecheckSteps((prev) => withId(prev, stepId));
      if (wasBlocked) setBlockedStepIds((prev) => withId(prev, stepId));
      setConfirmedSteps((prev) => withoutId(prev, stepId));
      focusAfterConfirm.current = { stepId, back: true }; // 실패하면 다시 나타난 그 단추로 돌아간다.
      setError(e instanceof Error ? e.message : "그림을 확인하지 못했어요. 잠시 뒤 다시 눌러 주세요.");
    } finally {
      setPendingConfirm((prev) => withoutId(prev, stepId));
    }
  }

  // 단계 드래그 정렬 + 단계 직접 추가
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const [newStepSentence, setNewStepSentence] = useState("");

  useEffect(() => {
    api.listWorkers()
      .then((ws) => {
        setWorkers(ws);
        if (ws.length) setSelectedWorkerIds((cur) => (cur.size ? cur : new Set([ws[0].id])));
      })
      .catch(() => {
        // 근로자 목록 로드 실패는 직무 작성 자체를 막지 않는다.
      });
  }, []);

  // 자동으로 고른 그림 중 아직 확인하지 않은 단계. (2a-0) 서버 그림 상태가 있으면 그대로 따른다 — 서버는 다시 보낼
  // 때도(게시한 직무) 확인 안 한 자동 그림(auto_high·choose)을 막는다. 상태가 없는 예전 응답만 옛 규칙을 쓴다.
  const needsConfirm = (s: Step) => {
    if (!task || isConfirmed(s)) return false;
    if (s.picture_state) {
      if (s.picture_state === "none" || !s.symbol_url) return false;
      return s.picture_state !== "confirmed" || blockedStepIds.has(s.id)
        || (recheckSteps.has(s.id) && s.symbol_source === "LOCAL_AAC");
    }
    return task.status !== "published" && !!s.symbol_url && s.symbol_source === "LOCAL_AAC";
  };
  const isBlocked = (s: Step) => blockedStepIds.has(s.id);
  const unconfirmedCount = task ? task.steps.filter(needsConfirm).length : 0;

  const taskContext = () => ({
    business_type: businessType.trim() || undefined,
    work_environment: workEnvironment.trim() || undefined,
    worker_note: workerNote.trim() || undefined,
    worker_id: noteWorkerId || undefined,
  });

  // 위쪽 오류 알림이 생기면 화면 안으로 끌어온다 — 긴 목록을 내려 본 뒤의 실패가 보이지 않던 문제(1차 검증).
  useEffect(() => {
    if (error) errorBox.current?.scrollIntoView?.({ block: "nearest" });
  }, [error]);

  // 편집기를 연 뒤·되돌린 뒤 초점을 둘 곳. 렌더가 끝난 뒤(task가 바뀐 커밋 뒤) 한 번 쓰고 비운다. 예전에는
  // setTimeout으로 제목에 초점을 줬는데, 누른 버튼이 사라지며 초점이 body로 떨어지고 제목으로 가지 않았다(2차 검증).
  const focusAfterTask = useRef<{ kind: "heading" } | { kind: "step"; index: number } | null>(null);
  const stepInputs = useRef<Map<string, HTMLTextAreaElement>>(new Map());
  useEffect(() => {
    const want = focusAfterTask.current;
    if (!want || !task) return;
    focusAfterTask.current = null;
    const id = want.kind === "step" ? task.steps[want.index]?.id : undefined;
    const el = id ? stepInputs.current.get(id) : undefined;
    if (el) el.focus();
    else editorHeading.current?.focus();
  }, [task]);

  // 2a-1 2회차 검증: 키보드로 누른 단추가 사라지거나 꺼지면 초점이 body로 빠졌다(이 화면이 /manager일 때부터 있던 문제).
  // 화면이 반영된 커밋 바로 뒤에, 초점을 잃었을 때만(다른 곳으로 옮겼으면 그대로) 다음 할 곳으로 옮긴다.
  const focusAfterSplit = useRef(false);
  const focusAfterConfirm = useRef<{ stepId: string; back: boolean } | null>(null);
  const decomposeButton = useRef<HTMLButtonElement | null>(null);
  useLayoutEffect(() => {
    const active = document.activeElement as HTMLElement | null;
    const lost = !active || active === document.body || !active.isConnected
      || (active instanceof HTMLButtonElement && active.disabled);
    if (focusAfterSplit.current && !splitting) {
      focusAfterSplit.current = false;
      if (lost) {
        // 나눴으면 '이렇게 나눴어요' 제목으로, 못 나눴으면(오류) 다시 누를 수 있는 [단계로 나누기]로.
        const heading = preview ? document.getElementById("split-preview-title") : null;
        (heading ?? decomposeButton.current)?.focus();
      }
    }
    const want = focusAfterConfirm.current;
    if (want && task) {
      const buttons = Array.from(document.querySelectorAll<HTMLButtonElement>("[data-confirm-step]"));
      const own = buttons.find((b) => b.dataset.confirmStep === want.stepId);
      if (want.back) {
        // 실패: 단추가 다시 나타나면 그리로(초점을 잃었거나 다음 확인 단추로 옮겨 둔 경우에만).
        if (!own) return;
        focusAfterConfirm.current = null;
        if (lost || (active instanceof HTMLButtonElement && active.dataset.confirmStep)) own.focus();
        return;
      }
      if (own) return; // 아직 단추가 그대로다 — 사라진 커밋에서 옮긴다.
      focusAfterConfirm.current = null;
      if (!lost) return;
      const order = task.steps.findIndex((s) => s.id === want.stepId);
      const after = buttons.find((b) => task.steps.findIndex((s) => s.id === b.dataset.confirmStep) > order);
      const next = after ?? buttons[0] ?? stepInputs.current.get(want.stepId);
      next?.focus();
    }
  });
  // 편집기 문장 칸은 내용만큼 높이를 늘린다(390px에서 한 줄 칸이 나눈 문장을 잘라 보여 줬다).
  useLayoutEffect(() => {
    stepInputs.current.forEach(fitHeight);
  });
  useEffect(() => {
    const onResize = () => stepInputs.current.forEach(fitHeight);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // [되돌리기]는 나눈 단계가 그대로 붙어 있을 때만 뜻이 있다. 순서를 바꿨거나 그중 하나를 지웠으면 내린다(남겨 두면
  // 눌렀을 때 404가 난다). (2a-0) 보낸 직무도 서버가 문장을 나누고 합치므로(고친 내용은 다음 배정부터) 게시 상태와
  // 상관없이 띄운다 — 예전에는 보낸 직무에서 나뉘어도 [되돌리기]가 숨어 되돌릴 방법이 없었다(1회차 검증).
  const undoIds = task?.steps.map((s) => s.id) ?? [];
  const undoAt = splitUndo ? undoIds.indexOf(splitUndo.stepIds[0]) : -1;
  const activeUndo = splitUndo && task && undoAt >= 0
    && splitUndo.stepIds.every((id, k) => undoIds[undoAt + k] === id)
    ? splitUndo : null;

  const previewEdited = !!preview
    && (preview.rows.length !== preview.initial.length || preview.rows.some((r, i) => r.text !== preview.initial[i]));
  const previewStale = !!preview && rawInput !== preview.input;

  // [단계로 나누기] — 직무는 아직 만들지 않는다. 나눈 결과를 입력칸 바로 아래에 보여 주고 사업주가 그 자리에서 고친다.
  // 목록을 고쳤으면 다시 나누기 전에 묻는다(새로 나누면 고친 줄이 사라지고 GPT를 다시 부른다).
  async function handleDecompose() {
    if (previewEdited && !window.confirm("고친 줄이 있어요. 새로 나눌까요? 고친 내용은 사라져요.")) return;
    focusAfterSplit.current = true; // 나누는 동안 단추가 꺼진다 — 끝나면 위 useLayoutEffect가 초점을 옮긴다.
    setSplitting(true);
    setConfirmError(null);
    setError(null);
    setNotice(null);
    try {
      const input = rawInput;
      const result = await api.splitPreview(input, taskContext());
      if (!result.steps.length) {
        setPreview(null);
        setError("나눌 문장을 찾지 못했어요. 할 일을 조금 더 자세히 적어 주세요.");
        return;
      }
      // 새로 나누면 앞서 열어 둔 편집기는 닫는다(그 초안은 서버에 그대로 남는다).
      setTask(null);
      setSplitUndo(null);
      const rows = rowsFromPreview(result.steps);
      setPreview({ title: result.task_title, job: result.job, input, rows, initial: rows.map((r) => r.text) });
    } catch (e) {
      setError(e instanceof Error ? e.message : "문장을 나누지 못했어요. 잠시 뒤 다시 눌러 주세요.");
    } finally {
      setSplitting(false);
    }
  }

  // [이대로 그림 고르기] — 사업주가 확인한 줄로 초안을 만들고(그림·음성은 서버가 붙인다) 편집기를 연다.
  async function handleConfirmSplit() {
    if (!preview) return;
    setConfirming(true);
    setError(null);
    setConfirmError(null);
    setNotice(null);
    try {
      setConfirmedSteps(new Set());
      setStepCandidates({});
      const created = await api.createTask(preview.input, {
        ...taskContext(),
        title: preview.title,
        job: preview.job || undefined,
        steps: toConfirmed(preview.rows),
      });
      // 편집기 제목으로 초점을 옮겨 화면 읽기 프로그램·키보드 사용자가 다음 할 일로 바로 간다(위 effect).
      focusAfterTask.current = { kind: "heading" };
      setTask(created);
      setPreview(null);
    } catch (e) {
      setConfirmError(e instanceof Error ? e.message : "초안을 만들지 못했어요. 잠시 뒤 다시 눌러 주세요.");
    } finally {
      setConfirming(false);
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

  // 편집기에서 문장을 고쳐 저장. 고친 문장에 동작이 둘이면 서버가 경고 없이 두 단계로 나누고, 여기서 [되돌리기]를 띄운다.
  async function handleEditSentence(stepId: string, sentence: string) {
    if (!task) return;
    const text = sentence.trim();
    if (!text) {
      setError("문장이 비어 있어요. 할 일을 적어 주세요.");
      return;
    }
    setError(null);
    const before = task.steps.find((s) => s.id === stepId);
    setRewritingId(stepId);
    try {
      const result = await api.rewriteStep(task.id, stepId, text);
      setTask(result.task);
      setSplitUndo(result.split_step_ids.length >= 2
        ? { stepIds: result.split_step_ids, sentence: result.sentence, actionType: before?.action_type }
        : null);
      // 저장된 문장이 그대로면(앞뒤 빈칸만 다름) 그림 확인·후보를 버리지 않는다(2차 검증 — 칸을 지나갈 때마다
      // '이 그림이 맞아요' 확인이 풀렸다).
      const saved = result.task.steps.find((st) => st.id === stepId);
      if (result.split_step_ids.length < 2 && saved && before && saved.sentence === before.sentence) return;
    } catch (e) {
      setError(e instanceof Error ? e.message : "문장을 저장하지 못했어요. 잠시 뒤 다시 해 주세요.");
      return;
    } finally {
      setRewritingId(null);
    }
    // 문장이 바뀌면 그림이 여전히 맞는지 다시 봐야 한다.
    unconfirmStep(stepId);
    // 문장이 바뀌면 후보도 달라진다. 캐시를 버려 다시 받아오게 한다.
    setStepCandidates((prev) => {
      const next = { ...prev };
      delete next[stepId];
      return next;
    });
  }

  // 저장하며 나눈 단계를 사업주가 적은 문장 한 단계로 되돌린다.
  async function handleUndoSplit() {
    if (!task || !activeUndo) return;
    setError(null);
    const at = undoAt;
    try {
      const merged = await api.mergeSteps(task.id, activeUndo.stepIds, activeUndo.sentence, activeUndo.actionType);
      // [되돌리기] 버튼과 나눈 줄이 사라지므로 합친 단계의 문장 칸으로 초점을 옮긴다.
      focusAfterTask.current = { kind: "step", index: at };
      setTask(merged);
      setSplitUndo(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "되돌리지 못했어요. 잠시 뒤 다시 해 주세요.");
    }
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
      confirmStep(stepId);
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
      confirmStep(stepId);
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
      const result = await api.addStep(task.id, newStepSentence.trim());
      setTask(result);
      // 새 문장에 동작이 둘이라 서버가 두 단계로 넣었으면 문장 고치기와 같이 [되돌리기]를 띄운다.
      setSplitUndo(result.split_step_ids && result.split_step_ids.length >= 2
        ? { stepIds: result.split_step_ids, sentence: result.sentence || newStepSentence.trim() }
        : null);
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
    if (!newWorkerName.trim()) {
      setAddWorkerFeedback({ ok: false, text: "근로자 이름을 입력해 주세요." });
      return;
    }
    if (newWorkerCode.trim() && !/^\d{4,12}$/.test(newWorkerCode.trim())) {
      setAddWorkerFeedback({ ok: false, text: "접속 코드는 4~12자리 숫자로 정해 주세요. 비워 두면 자동으로 만들어요." });
      return;
    }
    setBusy(true);
    setAddWorkerFeedback(null);
    try {
      const w = await api.createWorker(newWorkerName.trim(), newWorkerCode.trim() || undefined);
      setWorkers((prev) => [...prev, w]);
      setSelectedWorkerIds((prev) => new Set(prev).add(w.id));
      setNewWorkerName("");
      setNewWorkerCode("");
      setAddWorkerFeedback({ ok: true, text: `근로자 '${w.display_name}'을(를) 추가했습니다. 접속 코드: ${w.access_code} (근로자에게 알려 주세요)` });
    } catch (e) {
      setAddWorkerFeedback({ ok: false, text: e instanceof Error ? e.message : "근로자 추가에 실패했습니다." });
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteWorker(workerId: string, name: string) {
    // (2d) 서버는 이름을 그대로 다시 적어야 지운다(POST /delete, contract §6.2). 옛 화면은 2b-1이 지울 때까지
    // 확인 창 대신 이름을 적는 창을 띄워 그 이름을 함께 보낸다(이름 없이 보내면 늘 422였다 — 2d 검증 1회차).
    const typed = window.prompt(
      `근로자 '${name}'을(를) 지우려면 이름을 그대로 적어 주세요.\n이 근로자의 배정·수행 기록도 함께 지워져요.`,
      "",
    );
    if (typed === null) return;
    setError(null);
    setNotice(null);
    try {
      await api.deleteWorker(workerId, typed);
      const remaining = workers.filter((w) => w.id !== workerId);
      setWorkers(remaining);
      setSelectedWorkerIds((prev) => {
        if (!prev.has(workerId)) return prev;
        const next = new Set(prev);
        next.delete(workerId);
        return next;
      });
      setNotice(`근로자 '${name}'을(를) 삭제했습니다.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "근로자 삭제에 실패했습니다.");
    }
  }

  async function handlePublishAndAssign() {
    if (!task) return;
    // [그림 확인] 요청이 아직 서버에 닿지 않았으면 보내기가 먼저 도착해 422로 막힌다(1회차 검증). 끝날 때까지 기다리게 한다.
    if (pendingConfirm.size > 0) return;
    if (unconfirmedCount > 0) {
      flashAssignFeedback(false, `자동으로 고른 그림 ${unconfirmedCount}장이 문장과 맞는지 먼저 확인해 주세요.`);
      return;
    }
    if (selectedWorkerIds.size === 0) {
      flashAssignFeedback(false, "보낼 근로자를 한 명 이상 선택해 주세요.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    setAssignFeedback(null);
    setBlockedStepIds(new Set());
    // 보내면 나눈 단계가 그대로 근로자에게 간다 — 보낸 뒤에 [되돌리기]가 남아 있으면 무엇을 되돌리는지 헷갈리므로 내린다.
    setSplitUndo(null);
    try {
      if (task.status !== "published") {
        await api.publish(task.id);
        setTask({ ...task, status: "published" });
      }
      const ids = [...selectedWorkerIds];
      const result = await api.assign(task.id, ids);
      const names = workers.filter((w) => selectedWorkerIds.has(w.id)).map((w) => w.display_name);
      const text = `✓ ${names.join(", ")}님에게 보냈습니다(${result.length}명). 다른 근로자에게도 더 보낼 수 있어요.`;
      setNotice(text);
      flashAssignFeedback(true, text);
    } catch (e) {
      const text = e instanceof Error ? e.message : "게시/배정에 실패했습니다.";
      setError(text);
      flashAssignFeedback(false, text);
      // 서버 검사에 막혔으면(422·409) 어느 단계 때문인지 표시한다. 문장(detail)은 위에서 그대로 보였다.
      const ids = await blockedStepIdsAfterSendError(task.id, e);
      if (ids.length) {
        // 다른 기기·탭에서 고쳐 이 화면의 단계(그림 상태·사진)가 낡았을 수 있다. 새로 읽어 맞춰야 '그림 없음'으로 막힌
        // 단계에 [그림 확인]이 아니라 '그림을 고르거나 사진을 올려 주세요'가 뜬다(1회차 검증).
        try {
          const fresh = await api.getTask(task.id);
          if (fresh && fresh.id === task.id) {
            setTask((cur) => (cur && cur.id === fresh.id ? fresh : cur));
          }
        } catch {
          // 다시 읽지 못해도 강조와 서버 문장은 그대로 보인다.
        }
        setBlockedStepIds(new Set(ids));
        Array.from(document.querySelectorAll<HTMLElement>("[data-step-id]"))
          .find((el) => el.dataset.stepId === ids[0])?.scrollIntoView?.({ block: "nearest" });
      }
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
          : "그림 검색에 실패했습니다.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      {error && (
        <div ref={errorBox} role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}
      {notice && (
        <div role="status" className="rounded-lg bg-green-50 p-3 text-sm text-green-800">
          {notice}
        </div>
      )}

      {/* 단계로 나누기 전에는 2단 그리드가 오른쪽을 빈 채로 예약해 화면 오른쪽이 통째로 비어 보였다.
          직무가 생기기 전에는 입력·검색이 전체 폭을 쓰고, 생긴 뒤에만 왼쪽 380px + 오른쪽 검토로 나눈다. */}
      <div className={task
        ? "grid grid-cols-1 gap-6 lg:grid-cols-[380px_1fr] lg:items-start"
        : "flex flex-col gap-6"}
      >
        <div className="space-y-6">
      {/* break-keep: 한국어 낱말 중간에서 줄이 바뀌지 않게(390px에서 '붙입 / 니다'로 잘렸다). */}
      <section className="break-keep">
        <h1 className="text-xl font-bold text-slate-900">오늘 직무 입력</h1>
        <p className="mt-1 text-sm text-slate-600">
          평소 말하듯 적어 주세요. 단계는 잡카드가 나눠요. 단계마다 그림과 음성을 붙여요.
        </p>
        {fromExample && !preview && !task && (
          <p data-testid="example-note" role="status" className="mt-2 rounded-lg bg-paper-100 px-3 py-2 text-sm text-ink-900">
            예시를 채워 두었어요. 고쳐도 되고, 그대로 [단계로 나누기]를 눌러 봐도 돼요.
          </p>
        )}
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
        {workers.length > 0 && (
          <select
            className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            value={noteWorkerId}
            onChange={(e) => setNoteWorkerId(e.target.value)}
            aria-label="맞춤 대상 근로자"
          >
            <option value="">맞춤 대상 근로자 (선택)</option>
            {workers.map((w) => (
              <option key={w.id} value={w.id}>{w.display_name}</option>
            ))}
          </select>
        )}
        {/* 'AI'라고 쓰지 않는다(창업자 결정 2: 자동 결과는 '✦ 자동'). 글자색은 흰 바탕 4.5:1 이상인 slate-600. */}
        <p className="mt-1 text-xs text-slate-600">
          업종·환경·근로자 특성을 적으면 ✦ 자동 나누기가 더 맞춤형으로 단계를 나눠요(선택).
          근로자 특성은 근로자 화면에서 그 근로자의 메모 사용 설정을 켜고 처리 동의를 기록한 경우에만 자동 나누기에 쓰여요.
          근로자 이름은 보내기 전에 '근로자 A'처럼 바꿔 보내요.
        </p>
        <button
          ref={decomposeButton}
          onClick={handleDecompose}
          // 목록이 지금 원문 그대로면(원문도 목록도 안 고침) 다시 나눌 것이 없다 — GPT를 다시 부르지 않는다.
          disabled={busy || splitting || confirming || !rawInput.trim() || (!!preview && !previewStale && !previewEdited)}
          className="mt-3 min-h-11 rounded-lg bg-blue-700 px-4 py-2 font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:opacity-50"
        >
          단계로 나누기
        </button>
        {splitting && (
          <p role="status" className="mt-3 break-keep text-sm font-semibold text-slate-700">
            문장을 나누고 있어요…
          </p>
        )}
        {preview && !splitting && (
          <SplitPreviewList
            rows={preview.rows}
            onChange={(rows) => setPreview((cur) => (cur ? { ...cur, rows } : cur))}
            onConfirm={handleConfirmSplit}
            confirming={confirming}
            stale={previewStale}
            confirmError={confirmError}
          />
        )}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="text-lg font-bold text-slate-900">
          그림 카드 검색
        </h2>

        <p className="mt-1 text-sm text-slate-600">
          직무별 그림 카드 중 작업 문장과 가장 가까운 그림을 찾아 줍니다.
        </p>

        <div className="mt-3 flex gap-2">
          <input
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-base"
            value={aacQuery}
            onChange={(e) => setAacQuery(e.target.value)}
            aria-label="그림 검색어"
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

                  <div className="mt-2 text-sm font-medium text-slate-900">
                    {match.label}
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
      </div>

      {task && (
        <section>
          <h2 ref={editorHeading} tabIndex={-1} className="text-lg font-bold text-slate-900 focus:outline-none">
            검토 · 수정 <span className="text-sm font-normal text-slate-600">({task.steps.length}단계)</span>
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            근로자가 보게 될 화면과 같은 순서입니다. 손잡이를 끌어 순서를 바꾸고, 문장을 다듬거나 단계를 추가할 수 있습니다.
          </p>
          {activeUndo && (
            <div role="status" className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 p-2 text-sm text-slate-700">
              <span className="break-keep">동작이 둘이라 두 단계로 나눴어요.</span>
              <button
                type="button"
                onClick={handleUndoSplit}
                className="min-h-11 rounded-lg border border-slate-300 bg-white px-3 font-semibold text-slate-800 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
              >
                되돌리기
              </button>
            </div>
          )}
          <ol className="mt-3 space-y-3">
            {task.steps.map((s, idx) => (
              <li
                key={s.id}
                data-step-id={s.id}
                data-send-blocked={isBlocked(s) || undefined}
                onDragOver={(e) => {
                  e.preventDefault();
                  if (dragOverIndex !== idx) setDragOverIndex(idx);
                }}
                onDrop={() => handleDropOn(idx)}
                className={cn(
                  // 좁은 화면(sm 미만)에서는 손잡이·번호·그림 줄 아래로 문장 칸이 전체 폭을 쓴다.
                  "flex flex-wrap items-start gap-2 rounded-lg border bg-white p-3 transition-colors sm:flex-nowrap",
                  dragOverIndex === idx && dragIndex !== null && dragIndex !== idx
                    ? "border-blue-400 ring-2 ring-blue-200"
                    : isBlocked(s) ? "border-danger-700 bg-danger-50 ring-2 ring-danger-700" : "border-slate-200",
                  dragIndex === idx && "opacity-50",
                )}
              >
                <span
                  draggable
                  onDragStart={() => setDragIndex(idx)}
                  onDragEnd={() => {
                    setDragIndex(null);
                    setDragOverIndex(null);
                  }}
                  className="mt-1 cursor-grab text-slate-500 hover:text-slate-700 active:cursor-grabbing"
                  // 마우스 끌기 전용 손잡이(장식). 이름은 title로만 보인다
                  // (role 없는 span의 aria-label은 axe aria-prohibited-attr).
                  aria-hidden="true"
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
                         onError={() => onMediaError(s.symbol_url)}
                         className="h-16 w-16 rounded border border-slate-200 object-contain" />
                  ) : (
                    // 아래 후보 영역이 "그림 고르기"를 안내하는 동안에는 "사진 권장"을
                    // 함께 띄우지 않는다(상충). 후보가 없을 때만 사진을 권한다.
                    <div className={cn(
                      "flex h-16 w-16 items-center justify-center rounded border border-dashed text-center text-xs",
                      stepCandidates[s.id]?.candidates.length
                        ? "border-slate-300 bg-slate-50 text-slate-600"
                        : "border-amber-400 bg-amber-50 text-amber-700",
                    )}>
                      {stepCandidates[s.id]?.candidates.length ? "그림 선택" : "사진 권장"}
                    </div>
                  )}
                  <label className="cursor-pointer text-xs font-medium text-blue-700 hover:underline">
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
                            className="text-xs text-slate-600 hover:text-slate-800 hover:underline">
                      되돌리기
                    </button>
                  )}
                </div>
                <div className="min-w-0 basis-full sm:basis-0 sm:flex-1">
                  <textarea
                    rows={1}
                    // 저장한 문장(앞뒤 빈칸을 뺀 것)이 바뀌면 칸을 새로 만들어 화면 글자를 맞춘다. 안 맞추면 칸을 지나갈
                    // 때마다 다시 저장을 보냈다(2차 검증).
                    key={s.sentence}
                    ref={(el) => {
                      if (el) stepInputs.current.set(s.id, el);
                      else stepInputs.current.delete(s.id);
                    }}
                    className="block w-full resize-none overflow-hidden break-keep rounded border border-slate-200 px-2 py-1 text-base leading-6 read-only:bg-slate-50"
                    defaultValue={s.sentence}
                    aria-label={`${s.order}단계 문장`}
                    readOnly={rewritingId !== null}
                    aria-busy={rewritingId === s.id || undefined}
                    onInput={(e) => fitHeight(e.currentTarget)}
                    onKeyDown={(e) => {
                      // 한 단계 = 한 문장. Enter는 줄바꿈 대신 저장(칸 떠나기)이다.
                      if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                        e.preventDefault();
                        e.currentTarget.blur();
                      }
                    }}
                    onBlur={(e) => {
                      const text = e.target.value.replace(/\s*[\r\n]+\s*/g, " ").trim();
                      if (rewritingId === null && text !== s.sentence) handleEditSentence(s.id, text);
                    }}
                  />
                  {isBlocked(s) && (
                    <p className="mt-1 break-keep text-sm font-semibold text-danger-700">
                      이 단계 때문에 보내지 못했어요. {s.picture_state === "none" || !s.symbol_url
                        ? "그림을 고르거나 사진을 올려 주세요." : "그림이 맞는지 확인해 주세요."}
                    </p>
                  )}
                  {rewritingId === s.id && (
                    <p role="status" className="mt-1 break-keep text-sm font-semibold text-slate-700">
                      저장하는 중… 동작이 둘이면 두 단계로 나눠요.
                    </p>
                  )}
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                    <ActionChip action={s.action_type} className="whitespace-nowrap text-xs !px-2 !py-0.5" />
                    {/* 그림이 붙은 단계만 출처를 보여준다. 폴백 상태는 아래 후보 영역이
                        이미 설명하므로 "상징: fallback"은 중복 노이즈였다. */}
                    {s.symbol_url && (
                      <span className="whitespace-nowrap">
                        그림: {s.symbol_source === "photo" ? "직접 올린 사진" : "그림 카드"}
                      </span>
                    )}
                    {needsConfirm(s) && (
                      <button type="button" onClick={() => handleConfirmPicture(s.id)} data-confirm-step={s.id}
                              // 접근 이름은 보이는 글자로 시작한다(axe label-content-name-mismatch).
                              aria-label={`✦ 자동 · 그림이 맞으면 누르세요, ${s.order}단계 그림 확인`}
                              className="rounded border border-auto-700/40 bg-auto-50 px-2 py-0.5 text-xs font-semibold text-auto-700 hover:bg-white">
                        {/* 자동 결과 표기는 '✦ 자동'(창업자 결정 2, 'AI'라고 쓰지 않는다). */}
                        ✦ 자동 · 그림이 맞으면 누르세요
                      </button>
                    )}
                    {task.status !== "published" && s.symbol_url && s.symbol_source === "LOCAL_AAC"
                      && isConfirmed(s) && (
                      <span className="text-xs font-semibold text-emerald-700">✓ 확인함</span>
                    )}
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
                               className="h-14 w-14 shrink-0 rounded border border-slate-200 bg-white object-contain" />
                          <div className="min-w-0 flex-1">
                            <p className="break-keep text-xs font-medium text-emerald-800">
                              찾은 그림: {c.label}
                            </p>
                            <button type="button" onClick={() => handlePickCandidate(s.id, c)}
                                    className="mt-1 rounded bg-emerald-600 px-2 py-0.5 text-xs font-medium text-white hover:bg-emerald-700">
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
                          <p className="text-xs font-medium text-amber-800">
                            {tie
                              ? "비슷한 그림이 여러 개예요. 맞는 것을 골라 주세요."
                              : "딱 맞는 그림이 없어요. 아래에서 고르거나 현장 사진을 올리세요."}
                          </p>
                          <div className="mt-1.5 grid max-w-sm grid-cols-3 gap-2">
                            {sc.candidates.map((c) => (
                              <button key={c.asset_id} type="button"
                                      onClick={() => handlePickCandidate(s.id, c)}
                                      className="rounded border border-slate-200 bg-white p-1 hover:border-blue-400 hover:ring-2 hover:ring-blue-200"
                                      title={`${c.label} 선택`}>
                                <img src={c.image_url} alt={c.label}
                                     className="aspect-square w-full rounded object-contain" />
                                <span className="mt-0.5 block whitespace-normal text-center text-xs leading-tight text-slate-600">
                                  {c.label}
                                </span>
                              </button>
                            ))}
                          </div>
                        </div>
                      );
                    }
                    return (
                      <p className="mt-2 text-xs text-amber-700">
                        맞는 그림이 없어요. 실제 현장 사진을 올리면 가장 잘 전달됩니다.
                      </p>
                    );
                  })()}
                </div>
                <button
                  onClick={() => handleDeleteStep(s.id)}
                  disabled={task.steps.length <= 1}
                  className="mt-1 shrink-0 rounded p-1.5 text-slate-500 hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-slate-300"
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
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-900">근로자에게 보내기</h3>
              {workers.length > 1 && (
                <div className="flex gap-2 text-xs font-medium text-blue-700">
                  <button type="button" onClick={() => setSelectedWorkerIds(new Set(workers.map((w) => w.id)))}>
                    전체 선택
                  </button>
                  <button type="button" onClick={() => setSelectedWorkerIds(new Set())}>
                    선택 해제
                  </button>
                </div>
              )}
            </div>

            {workers.length > 0 ? (
              <>
                {/* 체크박스 — 여러 근로자를 한 번에 고를 수 있다(기존엔 한 명만 고를 수 있었음). */}
                <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label="배정할 근로자 선택(여러 명 가능)">
                  {workers.map((w) => {
                    const checked = selectedWorkerIds.has(w.id);
                    return (
                      <label key={w.id}
                        className={cn("flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm",
                          checked
                            ? "border-green-600 bg-green-50 text-green-900"
                            : "border-slate-300 bg-white text-slate-700")}>
                        <input type="checkbox" className="h-4 w-4" checked={checked}
                          onChange={() => toggleWorkerSelected(w.id)} />
                        {/* 보내기 목록에는 이름만(명세 5.6). 번호가 어깨 너머로 보이면 다른 사람이 그 근로자로 들어갈 수 있다. */}
                        {w.display_name}
                      </label>
                    );
                  })}
                </div>
                <button
                  onClick={handlePublishAndAssign}
                  disabled={busy || pendingConfirm.size > 0 || selectedWorkerIds.size === 0 || unconfirmedCount > 0
                    || missingPictureOrders(task).length > 0}
                  className="mt-2 rounded-lg bg-green-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                >
                  {busy ? "처리 중…" : selectedWorkerIds.size > 1
                    ? `게시하고 ${selectedWorkerIds.size}명에게 보내기`
                    : "게시하고 보내기"}
                </button>
                {/* 그림 없는 단계는 보낼 수 없다(0차 7번·창업자 결정 9: 단계마다 그림 1장). 서버도 422로 막는다. */}
                {missingPictureOrders(task).length > 0 && (
                  <p className="mt-2 text-sm font-semibold text-danger-700">
                    그림이 없는 단계가 있어요({missingPictureOrders(task).join(", ")}단계). 그림을 고른 뒤 보내 주세요.
                  </p>
                )}
                {unconfirmedCount > 0 && (
                  <p className="mt-2 text-sm font-semibold text-amber-700">
                    자동으로 고른 그림 {unconfirmedCount}장을 확인해야 보낼 수 있어요. 틀린 그림은 후보에서 다시 고르거나 사진을 올려 주세요.
                  </p>
                )}
                {/* 버튼 바로 아래에 결과를 보여준다 — 위쪽 배너는 내용이 길면 화면 밖으로 벗어난다. */}
                {assignFeedback && (
                  <p role="status"
                    className={cn("mt-2 text-sm font-semibold",
                      assignFeedback.ok ? "text-green-700" : "text-red-700")}>
                    {assignFeedback.text}
                  </p>
                )}
              </>
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
                placeholder="접속 코드 (비우면 자동)" aria-label="새 근로자 접속 코드"
                inputMode="numeric"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <button
                onClick={handleAddWorker}
                disabled={busy || !newWorkerName.trim()}
                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 disabled:opacity-50"
              >
                + 근로자 추가
              </button>
            </div>
            {addWorkerFeedback && (
              <p role={addWorkerFeedback.ok ? "status" : "alert"}
                className={cn("mt-2 text-sm font-semibold",
                  addWorkerFeedback.ok ? "text-green-700" : "text-red-700")}>
                {addWorkerFeedback.text}
              </p>
            )}

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
                        {w.display_name} <MaskedAccessCode worker={w} />
                      </span>
                      <button
                        onClick={() => handleDeleteWorker(w.id, w.display_name)}
                        className="rounded-full p-0.5 text-slate-500 hover:bg-red-50 hover:text-red-600"
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
    </div>
  );
}

/** 그림이 없는 단계 번호(보내기 막음). 서버의 picture_state가 없으면(예전 서버) 그림 주소로 판단한다. */
function missingPictureOrders(task: Task): number[] {
  return task.steps.filter((s) => s.picture_state === "none" || !s.symbol_url).map((s) => s.order);
}

/** 번호를 가린 채(●●●●) 보이고, 눈 단추를 누르면 5초 동안만 보인다(명세 5.6 — 어깨 너머로 번호가 새지 않게). */
const CODE_REVEAL_MS = 5_000;
function MaskedAccessCode({ worker }: { worker: Worker }) {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (!shown) return;
    const t = window.setTimeout(() => setShown(false), CODE_REVEAL_MS);
    return () => window.clearTimeout(t);
  }, [shown]);
  return (
    <span className="inline-flex items-center gap-1 text-slate-500">
      <span className="tabular-nums" data-testid={`code-${worker.id}`}>
        ({shown ? accessCodeText(worker) : maskedCode(worker.access_code_length)})
      </span>
      <button
        type="button"
        onClick={() => setShown((v) => !v)}
        aria-pressed={shown}
        aria-label={shown ? `${worker.display_name} 번호 가리기` : `${worker.display_name} 번호 보기`}
        title={shown ? "번호 가리기" : "번호 보기(5초)"}
        className="rounded p-0.5 text-slate-500 hover:bg-slate-100"
      >
        {shown ? <IconHide size={14} strokeWidth={2} /> : <IconShow size={14} strokeWidth={2} />}
      </button>
    </span>
  );
}
