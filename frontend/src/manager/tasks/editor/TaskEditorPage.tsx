// 직무 편집기(/m/tasks/:id, 명세 5.5, tasks §4.3 TaskEditorPage). 사업주 화면의 중심.
// - 머리 64: 제목 바로 고치기 · 상태 배지 · SaveIndicator · ReviewQueueBar('확인할 것 n개 남음 · [다음 ▶]') ·
//   [그림 한눈에] · [보내기](확인할 것이 남으면 꺼짐 + 툴팁). 보낸 직무면 아래에 VersionNotice.
// - 넓은 화면(768 이상): 단계 목록 280~320 + 단계 상세. 390: 목록만 → 행을 누르면 상세 전체 화면, 아래 고정 줄에
//   ReviewQueueBar 요약과 [그림 한눈에]·[보내기]. 머리는 제목·저장 표시만.
// - 서버에 쓰는 일은 한 줄로 세워 차례로 보낸다(자동 저장과 확인이 엇갈려 expected_updated_at이 어긋나지 않게).
// 옛 ManagerPage에서 옮긴 것: 저장하며 나눈 단계 [되돌리기](activeUndo: 나눈 단계가 그대로 붙어 있을 때만),
// 문장을 마무리 저장하는 동안 다른 문장 칸은 읽기 전용, 같은 문장이면 다시 저장하지 않음(확인 유지),
// 칸 key(단계 id·새로 불러온 횟수), 초점 이동(누른 단추가 사라지면 다음 할 곳으로), 후보 실패 기록(무한 재조회 방지),
// 서명 URL 만료 시 다시 받기(useMediaRefresh).
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Images, Send } from "lucide-react";
import { ApiError } from "../../../apiErrors";
import { Badge, Button, Dialog, EmptyState, Tooltip, useToast } from "../../../components/ui";
import { cn } from "../../../cn";
import { mergeStepMedia, useMediaRefresh } from "../../../media";
import { editorApi } from "../../api/editor";
import { renameTask } from "../../api/tasks";
import type { EditorStep, EditorTask, PictureCandidate, SendResult } from "../../api/types";
import { editor as copy, errors, overview as overviewCopy, reviewQueue, sendSheet, taskRow, taskState } from "../../copy";
import { errorMessage } from "../listHelpers";
import { relativeDate } from "../relativeDate";
import EditorSkeleton from "./EditorSkeleton";
import { ReviewQueueBar, SaveIndicator, VersionNotice, type SaveStatus } from "./EditorBits";
import PicturePicker from "./PicturePicker";
import PictureOverview from "./PictureOverview";
import { fromMatches, latestUpdatedAt, needsReview, nextReviewId, reviewSteps } from "./review";
import SendSheet from "./SendSheet";
import StepDetail, { type CandidateState } from "./StepDetail";
import StepList from "./StepList";
import TitleEditor from "./TitleEditor";
import { TWO_PANE_QUERY, useMedia } from "./useMedia";

export interface TaskEditorPageProps {
  taskId: string;
  /** 방금 만든 초안(새 직무 화면이 넘김). 있으면 다시 불러오지 않는다. */
  initialTask: EditorTask | null;
  /** 초안을 받은 뒤 한 번 부른다 — 부모가 초안을 비워, 다시 만들어진 편집기가 옛 초안을 받지 않게(1회차 검증). */
  onInitialUsed?: () => void;
}

interface SplitUndo {
  stepIds: string[];
  sentence: string;
  actionType?: string;
}

function nowIso() {
  return new Date().toISOString().replace("Z", "");
}

export default function TaskEditorPage({ taskId, initialTask, onInitialUsed }: TaskEditorPageProps) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const toast = useToast();
  const wide = useMedia(TWO_PANE_QUERY);

  const [task, setTask] = useState<EditorTask | null>(initialTask);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadNonce, setLoadNonce] = useState(0);
  /** 다시 불러오면 문장 칸을 새로 만든다(다른 창에서 고친 문장이 보이게). */
  const [reloadCount, setReloadCount] = useState(0);
  const [view, setView] = useState<"edit" | "overview">("edit");
  const [selectedId, setSelectedId] = useState<string | null>(() => params.get("step"));
  const [pickFirstReview, setPickFirstReview] = useState(() => params.get("review") === "1");
  const [candidates, setCandidates] = useState<Record<string, CandidateState>>({});
  const [splitUndo, setSplitUndo] = useState<SplitUndo | null>(null);
  const [rewritingId, setRewritingId] = useState<string | null>(null);
  const [pendingConfirm, setPendingConfirm] = useState<Set<string>>(new Set());
  const [blockedIds, setBlockedIds] = useState<Set<string>>(new Set());
  const [picker, setPicker] = useState<{ stepId: string; mode: "search" | "photo" } | null>(null);
  const [toDelete, setToDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [sendOpen, setSendOpen] = useState(false);
  const [saving, setSaving] = useState(0);
  const [saveError, setSaveError] = useState<{ retry?: () => void } | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(() => initialTask?.updated_at ?? null);
  const [reorderBusy, setReorderBusy] = useState(false);

  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const updatedAt = useRef<string | null>(initialTask ? latestUpdatedAt(initialTask) : null);
  const deferred = useRef(new Set<string>());
  const requested = useRef(new Set<string>());
  const bulkAsked = useRef(false);
  const detailHeading = useRef<HTMLHeadingElement | null>(null);
  const overviewHeading = useRef<HTMLHeadingElement | null>(null);
  const nextButton = useRef<HTMLButtonElement | null>(null);
  const bottomBar = useRef<HTMLDivElement | null>(null);
  const sendButton = useRef<HTMLButtonElement | null>(null);
  const mobileSendButton = useRef<HTMLButtonElement | null>(null);
  const focusWant = useRef<"detail" | "caution" | "detailIfLost" | "overview" | "afterConfirm" | "list" | { row: string } | null>(
    // (2c 연결) 홈의 코칭 카드·도움 띠가 ?step=(&fix=)로 데려오면 불러온 뒤 그 단계 상세로 초점을 옮긴다.
    params.get("step") ? "detail" : null,
  );
  const listHeading = useRef<HTMLHeadingElement | null>(null);

  // ── 불러오기 ── 처음 받은 초안은 마운트 때 한 번만 쓴다(부모가 넘긴 뒤 비워도 다시 불러오지 않게 값을 붙잡아 둔다).
  const [initial] = useState(initialTask);
  const initialUsed = useRef(initial ? onInitialUsed : undefined);
  useEffect(() => {
    initialUsed.current?.();
    initialUsed.current = undefined;
  }, []);
  useEffect(() => {
    if (initial && loadNonce === 0) return;
    let alive = true;
    editorApi
      .getTask(taskId)
      .then((t) => {
        if (!alive) return;
        setTask(t);
        updatedAt.current = latestUpdatedAt(t);
        setSavedAt(t.updated_at ?? null);
        setLoadError(null);
      })
      .catch((e) => alive && setLoadError(errorMessage(e) || copy.loadFailed));
    return () => {
      alive = false;
    };
  }, [taskId, initial, loadNonce]);

  const reload = useCallback(() => {
    setReloadCount((n) => n + 1);
    setLoadNonce((n) => n + 1);
  }, []);

  // 업로드 사진·음성의 서명 URL은 만료된다. 못 불러오면 직무를 다시 받아 URL만 바꾼다.
  const onMediaError = useMediaRefresh(async () => {
    const fresh = await editorApi.getTask(taskId);
    setTask((cur) => (cur && cur.id === fresh.id ? mergeStepMedia([cur], [fresh])[0] : cur));
  });

  // ── 서버에 쓰기: 한 줄로 세운다 ──
  const mutate = useCallback(
    <T,>(op: () => Promise<T>, opts: { retry?: () => void; track?: boolean } = {}): Promise<T> => {
      const track = opts.track ?? true;
      if (track) setSaving((c) => c + 1);
      const p = queue.current.then(op);
      queue.current = p.catch(() => undefined);
      return p.then(
        (v) => {
          if (track) {
            setSavedAt(nowIso());
            setSaveError(null);
          }
          return v;
        },
        (e) => {
          if (track) setSaveError({ retry: opts.retry });
          if (e instanceof ApiError && e.status === 409) {
            toast.show({ tone: "error", message: errorMessage(e), action: { label: copy.reload, onClick: reload } });
          }
          throw e;
        },
      ).finally(() => {
        if (track) setSaving((c) => c - 1);
      });
    },
    [toast, reload],
  );

  const applyTask = useCallback((t: EditorTask) => {
    setTask((cur) => (cur ? { ...cur, ...t } : t));
    updatedAt.current = latestUpdatedAt(t) ?? updatedAt.current;
  }, []);

  const applyStep = useCallback((s: EditorStep) => {
    setTask((cur) => (cur ? { ...cur, steps: cur.steps.map((x) => (x.id === s.id ? { ...x, ...s } : x)) } : cur));
    if (s.task_updated_at) updatedAt.current = s.task_updated_at;
  }, []);

  const fail = useCallback(
    (e: unknown, fallback: string) => {
      if (e instanceof ApiError && e.status === 409) return; // mutate가 [새로 불러오기] 토스트를 띄웠다
      toast.show({ tone: "error", message: errorMessage(e) || fallback });
    },
    [toast],
  );

  // ── 후보: 처음엔 모든 단계를 한 번에, 그 뒤 새로 생기거나 문장이 바뀐 단계만. 실패도 기록한다(다시 묻지 않게) ──
  useEffect(() => {
    if (!task) return;
    const missing = task.steps.filter((s) => !candidates[s.id] && !requested.current.has(s.id));
    if (!missing.length) return;
    missing.forEach((s) => requested.current.add(s.id));
    const id = task.id;
    if (!bulkAsked.current) {
      bulkAsked.current = true;
      editorApi
        .candidates(id)
        .then((r) => {
          setCandidates((cur) => {
            const next = { ...cur };
            for (const s of missing) next[s.id] = { status: "ok", items: [] };
            for (const row of r.steps) next[row.step_id] = { status: "ok", items: row.candidates.slice(0, 3) };
            return next;
          });
        })
        .catch(() =>
          setCandidates((cur) => {
            const next = { ...cur };
            for (const s of missing) next[s.id] = { status: "failed", items: [] };
            return next;
          }),
        );
      return;
    }
    for (const s of missing) {
      editorApi
        .stepCandidates(id, s.id)
        .then((r) => setCandidates((cur) => ({ ...cur, [s.id]: { status: "ok", items: fromMatches(r.candidates) } })))
        .catch(() => setCandidates((cur) => ({ ...cur, [s.id]: { status: "failed", items: [] } })));
    }
  }, [task, candidates]);

  const forgetCandidates = (ids: string[]) => {
    ids.forEach((i) => requested.current.delete(i));
    setCandidates((cur) => {
      const next = { ...cur };
      ids.forEach((i) => delete next[i]);
      return next;
    });
  };

  // ── 고른 단계 ──
  const steps = useMemo(() => task?.steps ?? [], [task]);
  const reviews = task ? reviewSteps(task) : [];
  const firstReview = reviews[0]?.id ?? null;
  const selected =
    steps.find((s) => s.id === selectedId) ??
    (wide || pickFirstReview ? steps.find((s) => s.id === firstReview) ?? steps[0] ?? null : null);
  const selectedIndex = selected ? steps.findIndex((s) => s.id === selected.id) : -1;

  /** 넓은 화면은 고른 단계가 없으면 첫 확인할 단계를 보인다. 무언가를 고치면 그 단계를 고정해 둔다 —
   *  순서를 바꾸거나 확인해도 보던 단계가 다른 단계로 바뀌지 않게. */
  function pin() {
    if (!selectedId && selected) setSelectedId(selected.id);
  }

  function select(id: string | null, focus: "detail" | "caution" | null = null) {
    setSelectedId(id);
    setPickFirstReview(false);
    setView("edit");
    if (focus) focusWant.current = focus;
  }

  // 초점: 화면이 바뀐 커밋 바로 뒤에 한 번. 누른 단추가 사라졌을 때(확인 뒤)는 초점을 잃은 경우에만 옮긴다.
  useLayoutEffect(() => {
    const want = focusWant.current;
    if (!want) return;
    if (want === "detail") {
      if (detailHeading.current) {
        focusWant.current = null;
        detailHeading.current.focus();
      }
      return;
    }
    if (want === "caution") {
      // 보내기 시트의 '✦ 자동으로 켠 조심 표시' 줄 → 그 단계의 조심 스위치로(390에서는 화면 아래 밖이라 스크롤도).
      const sw = document.querySelector<HTMLElement>("[data-testid='step-detail'] [role='switch']");
      if (sw) {
        focusWant.current = null;
        sw.focus();
        sw.scrollIntoView?.({ block: "center" });
      }
      return;
    }
    if (want === "detailIfLost") {
      focusWant.current = null;
      const a = document.activeElement as HTMLElement | null;
      if (!a || a === document.body || !a.isConnected) detailHeading.current?.focus();
      return;
    }
    if (want === "list") {
      focusWant.current = null;
      listHeading.current?.focus();
      return;
    }
    if (want === "overview") {
      if (overviewHeading.current) {
        focusWant.current = null;
        overviewHeading.current.focus();
      }
      return;
    }
    if (want === "afterConfirm") {
      focusWant.current = null;
      const a = document.activeElement as HTMLElement | null;
      const lost = !a || a === document.body || !a.isConnected
        || (a instanceof HTMLButtonElement && a.getAttribute("aria-busy") === "true");
      if (!lost) return;
      const target = reviews.length > 0 ? nextButton.current : wide ? sendButton.current : mobileSendButton.current;
      (target ?? detailHeading.current)?.focus();
      return;
    }
    focusWant.current = null;
    document.querySelector<HTMLButtonElement>(`[data-step-id="${want.row}"] button[data-row-select]`)?.focus();
  });

  // 390: 토스트가 아래 고정 줄([다음 ▶]·[그림 한눈에]·[보내기])을 덮지 않게 토스트 층을 그 줄 위로 올린다(2회차 검증).
  const hasTask = !!task;
  useEffect(() => {
    const bar = bottomBar.current;
    if (wide || !bar) return;
    const root = document.documentElement;
    const place = () => root.style.setProperty("--toast-bottom", `${Math.max(0, window.innerHeight - bar.getBoundingClientRect().top) + 8}px`);
    place();
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(place);
    ro?.observe(bar);
    window.addEventListener("resize", place);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", place);
      root.style.removeProperty("--toast-bottom");
    };
  }, [wide, hasTask]);

  // [되돌리기]는 나눈 단계가 그대로 붙어 있을 때만 뜻이 있다(순서를 바꿨거나 하나를 지웠으면 내린다).
  const ids = steps.map((s) => s.id);
  const undoAt = splitUndo ? ids.indexOf(splitUndo.stepIds[0]) : -1;
  const activeUndo =
    splitUndo && undoAt >= 0 && splitUndo.stepIds.every((sid, k) => ids[undoAt + k] === sid) ? splitUndo : null;

  // ── 문장 ──
  function autosave(stepId: string, text: string) {
    if (!task) return;
    pin();
    const s = task.steps.find((x) => x.id === stepId);
    if (!s || s.sentence === text) return;
    const tid = task.id;
    mutate(
      () =>
        editorApi.patchStep(tid, stepId, {
          sentence: text,
          defer_media: true,
          ...(updatedAt.current ? { expected_updated_at: updatedAt.current } : {}),
        }),
      { retry: () => autosave(stepId, text) },
    )
      .then((step) => {
        deferred.current.add(stepId);
        applyStep(step);
      })
      .catch(() => {});
  }

  function commit(stepId: string, text: string) {
    if (!task) return;
    const before = task.steps.find((x) => x.id === stepId);
    if (!before) return;
    const changed = text !== before.sentence || deferred.current.has(stepId);
    if (!changed) return; // 같은 문장이면 저장하지 않는다(확인·후보를 그대로 둔다)
    const tid = task.id;
    setRewritingId(stepId);
    mutate(() => editorApi.rewriteStep(tid, stepId, text, updatedAt.current), { retry: () => commit(stepId, text) })
      .then((r) => {
        deferred.current.delete(stepId);
        applyTask(r.task);
        if (r.split_step_ids.length >= 2) {
          setSplitUndo({ stepIds: r.split_step_ids, sentence: r.sentence, actionType: before.action_type });
          setSelectedId(r.split_step_ids[0]);
          // 상세가 새 key로 다시 그려져 초점을 잃으면 새 상세 제목('n단계 고치기', 바로 아래 [되돌리기])으로.
          focusWant.current = "detailIfLost";
        } else {
          setSplitUndo(null);
          forgetCandidates([stepId]);
        }
      })
      .catch((e) => fail(e, errors.save))
      .finally(() => setRewritingId(null));
  }

  function undoSplit() {
    if (!task || !activeUndo) return;
    const tid = task.id;
    const at = undoAt;
    const u = activeUndo;
    mutate(() => editorApi.mergeSteps(tid, u.stepIds, u.sentence, u.actionType))
      .then((merged) => {
        applyTask(merged);
        setSplitUndo(null);
        const id = merged.steps[at]?.id ?? null;
        setSelectedId(id);
        focusWant.current = "detail";
      })
      .catch((e) => fail(e, copy.undoFailed));
  }

  // ── 그림 ──
  function confirmStep(stepId: string) {
    if (!task || pendingConfirm.has(stepId)) return;
    pin();
    const tid = task.id;
    setPendingConfirm((cur) => new Set(cur).add(stepId));
    mutate(() => editorApi.confirmPicture(tid, stepId), { track: false })
      .then((s) => {
        applyStep(s);
        setBlockedIds((cur) => {
          const next = new Set(cur);
          next.delete(stepId);
          return next;
        });
        focusWant.current = "afterConfirm";
      })
      .catch((e) => fail(e, copy.confirmFailed))
      .finally(() =>
        setPendingConfirm((cur) => {
          const next = new Set(cur);
          next.delete(stepId);
          return next;
        }),
      );
  }

  async function confirmAll(stepIds: string[]) {
    if (!task) return;
    const tid = task.id;
    try {
      const out = await mutate(() => editorApi.confirmPictures(tid, stepIds), { track: false });
      out.forEach(applyStep);
      toast.show({ tone: "success", message: overviewCopy.confirmed(out.length) });
    } catch (e) {
      fail(e, copy.confirmFailed);
      reload();
    }
  }

  async function applyCandidate(stepId: string, c: PictureCandidate): Promise<boolean> {
    if (!task) return false;
    pin();
    const tid = task.id;
    try {
      const s = await mutate(() => editorApi.applyPicture(tid, stepId, { card_id: c.card_id, url: c.url, label: c.label }));
      applyStep(s);
      setBlockedIds((cur) => {
        const next = new Set(cur);
        next.delete(stepId);
        return next;
      });
      return true;
    } catch (e) {
      fail(e, copy.pictureFailed);
      return false;
    }
  }

  async function upload(stepId: string, file: File): Promise<boolean> {
    if (!task) return false;
    const tid = task.id;
    try {
      const s = await mutate(() => editorApi.uploadPhoto(tid, stepId, file));
      applyStep(s);
      return true;
    } catch (e) {
      fail(e, copy.pictureFailed);
      return false;
    }
  }

  function removePhoto(stepId: string) {
    if (!task) return;
    const tid = task.id;
    mutate(() => editorApi.removePhoto(tid, stepId))
      .then((s) => {
        applyStep(s);
        toast.show({ tone: "info", message: copy.photoRemoved });
      })
      .catch((e) => fail(e, copy.pictureFailed));
  }

  // ── 조심·묶음 ──
  function patch(stepId: string, body: { safety_flag?: boolean; group_break?: boolean }, fallback: string) {
    if (!task) return;
    pin();
    const tid = task.id;
    mutate(
      () => editorApi.patchStep(tid, stepId, { ...body, ...(updatedAt.current ? { expected_updated_at: updatedAt.current } : {}) }),
      { retry: () => patch(stepId, body, fallback) },
    )
      .then(applyStep)
      .catch((e) => fail(e, fallback));
  }

  // ── 순서·추가·지우기 ──
  function move(from: number, to: number) {
    if (!task || to < 0 || to >= task.steps.length || from === to) return;
    pin();
    const tid = task.id;
    const prev = task;
    const next = [...task.steps];
    const [m] = next.splice(from, 1);
    next.splice(to, 0, m);
    setTask({ ...task, steps: next.map((s, i) => ({ ...s, order: i + 1 })) });
    setReorderBusy(true);
    mutate(() => editorApi.reorderSteps(tid, next.map((s) => s.id)))
      .then(applyTask)
      .catch((e) => {
        setTask(prev);
        fail(e, copy.reorderFailed);
      })
      .finally(() => setReorderBusy(false));
  }

  async function addStep(sentence: string): Promise<boolean> {
    if (!task) return false;
    const tid = task.id;
    try {
      const r = await mutate(() => editorApi.addStep(tid, sentence));
      applyTask(r);
      const split = r.split_step_ids ?? [];
      setSplitUndo(split.length >= 2 ? { stepIds: split, sentence: r.sentence || sentence } : null);
      const last = split[0] ?? r.steps[r.steps.length - 1]?.id ?? null;
      if (last) setSelectedId(last);
      return true;
    } catch (e) {
      fail(e, copy.addStepFailed);
      return false;
    }
  }

  async function confirmDelete() {
    if (!task || !toDelete) return;
    const tid = task.id;
    const sid = toDelete;
    const at = task.steps.findIndex((s) => s.id === sid);
    setDeleting(true);
    try {
      const t = await mutate(() => editorApi.deleteStep(tid, sid));
      applyTask(t);
      setToDelete(null);
      const neighbor = t.steps[Math.min(at, t.steps.length - 1)]?.id ?? null;
      setSelectedId(wide ? neighbor : null);
      // 390은 상세가 사라지고 대화상자가 돌려줄 [이 단계 지우기]도 사라진다 — 이웃 단계 행으로(없으면 목록 제목으로).
      if (wide && neighbor) focusWant.current = "detail";
      else if (!wide) focusWant.current = neighbor ? { row: neighbor } : "list";
    } catch (e) {
      setToDelete(null);
      fail(e, copy.deleteFailed);
    } finally {
      setDeleting(false);
    }
  }

  async function voice(stepId: string): Promise<string | null> {
    if (!task) return null;
    const s = task.steps.find((x) => x.id === stepId);
    if (s?.tts_audio_url && !deferred.current.has(stepId)) return s.tts_audio_url;
    const tid = task.id;
    const r = await mutate(() => editorApi.stepTts(tid, stepId), { track: false });
    return r.tts_url;
  }

  async function rename(title: string): Promise<boolean> {
    if (!task) return false;
    const tid = task.id;
    try {
      const r = await mutate(() => renameTask(tid, title));
      setTask((cur) => (cur ? { ...cur, title: r.title, updated_at: r.updated_at ?? cur.updated_at } : cur));
      if (r.updated_at) updatedAt.current = r.updated_at;
      return true;
    } catch (e) {
      fail(e, errors.save);
      return false;
    }
  }

  // ── 보내기 ──
  const remaining = reviews.length;
  const canSend = remaining === 0 && pendingConfirm.size === 0 && steps.length > 0;

  function openSend() {
    if (!canSend) return;
    setSendOpen(true);
  }

  function onSent(result: SendResult) {
    setSendOpen(false);
    setSplitUndo(null);
    const n = result.results.length;
    const busyNames = result.results.filter((r) => r.outcome === "kept_in_progress").map((r) => r.display_name);
    toast.show({
      tone: "success",
      message: (
        <>
          {sendSheet.sentMessage(n)}
          {busyNames.map((name) => (
            <span key={name} className="mt-1 block text-ui-sm text-ink-700">
              {sendSheet.inProgressNote(name)}
            </span>
          ))}
        </>
      ),
      action: { label: sendSheet.viewStatus, onClick: () => navigate("/m") },
    });
    reload();
  }

  function goToStep(stepId: string, code?: string) {
    setSendOpen(false);
    setBlockedIds((cur) => (needsReview(steps.find((s) => s.id === stepId) ?? { picture_state: "confirmed" }) ? new Set(cur).add(stepId) : cur));
    // 초점은 시트가 닫히며 [보내기]로 돌아가지 않고 그 단계로 간다(focus.ts는 이미 옮긴 초점을 덮지 않는다).
    select(stepId, code === "auto_caution" ? "caution" : "detail");
  }

  function nextReview() {
    const id = nextReviewId({ steps }, selected?.id ?? null) ?? firstReview;
    if (id) select(id, "detail");
  }

  function openOverview() {
    setView("overview");
    focusWant.current = "overview";
  }

  // ── 그리기 ──
  if (!task) {
    return loadError ? (
      <div className="flex flex-col gap-4">
        <h1 className="sr-only">{copy.loadFailed}</h1>
        <EmptyState kind="error" title={loadError} onRetry={() => setLoadNonce((n) => n + 1)} />
      </div>
    ) : (
      <div className="flex flex-col gap-4">
        <h1 className="sr-only">{copy.stepsHeading}</h1>
        <EditorSkeleton mode="loading" />
      </div>
    );
  }

  const saveStatus: SaveStatus = saving > 0 ? "saving" : saveError ? "error" : "saved";
  const when = savedAt ? relativeDate(savedAt) : relativeDate(nowIso());
  const published = task.status === "published" || !!task.version?.current_no;
  const showList = wide || !selected;
  const showDetail = !!selected && (wide || !!selected);
  const sendDisabledText = sendSheet.disabledTooltip(remaining);

  // 꺼진 [보내기]를 누르면(휴대폰은 툴팁이 터치로 뜨지 않는다) 같은 이유를 토스트로 알리고 [다음 ▶]로 데려간다.
  function explainDisabledSend() {
    if (pendingConfirm.size > 0 && remaining === 0) return;
    toast.show({
      tone: "info",
      message: sendDisabledText,
      ...(remaining > 0 ? { action: { label: reviewQueue.next, onClick: nextReview } } : {}),
    });
  }

  const sendBtn = (ref: typeof sendButton, testId: string, className?: string) =>
    canSend ? (
      <Button
        ref={ref}
        variant="primary"
        onClick={openSend}
        className={className}
        icon={<Send size={16} strokeWidth={2} aria-hidden="true" />}
        data-testid={testId}
      >
        {copy.send}
      </Button>
    ) : (
      <Tooltip content={sendDisabledText} side={wide ? "bottom" : "top"} align={wide ? "center" : "end"} className={className}>
        <Button
          ref={ref}
          variant="primary"
          aria-disabled
          className={className}
          onClickCapture={explainDisabledSend}
          icon={<Send size={16} strokeWidth={2} aria-hidden="true" />}
          data-testid={testId}
        >
          {copy.send}
        </Button>
      </Tooltip>
    );

  return (
    <div className="flex flex-col gap-4 pb-32 md:pb-0" data-testid="task-editor">
      <header className="flex min-h-16 flex-wrap items-center gap-x-4 gap-y-2 rounded-card border border-paper-200 bg-white px-4 py-3 shadow-ui-sm">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
          <TitleEditor title={task.title} onSave={rename} />
          <span className="hidden flex-wrap items-center gap-1.5 md:flex">
            <Badge tone={published ? "success" : "neutral"} icon={false}>
              {published ? taskState.published : taskState.draft}
            </Badge>
            {task.version?.has_unsent_changes && <Badge tone="warning">{taskRow.unsentChanges}</Badge>}
          </span>
          <SaveIndicator status={saveStatus} when={when} onRetry={saveError?.retry} />
        </div>
        <div className="hidden items-center gap-3 md:flex">
          <ReviewQueueBar
            remaining={remaining}
            total={steps.length}
            onNext={nextReview}
            nextRef={(el) => {
              if (wide) nextButton.current = el;
            }}
          />
          <Button variant="secondary" onClick={openOverview} icon={<Images size={16} strokeWidth={2} aria-hidden="true" />}>
            {copy.overview}
          </Button>
          {sendBtn(sendButton, "editor-send")}
        </div>
      </header>

      {published && <VersionNotice recipients={task.recipients_count ?? 0} working={task.in_progress_count ?? 0} changed={!!task.version?.has_unsent_changes} />}

      {view === "overview" ? (
        <PictureOverview
          ref={overviewHeading}
          steps={steps}
          onBack={() => {
            setView("edit");
            focusWant.current = "detail";
          }}
          onOpenStep={(id) => select(id, "detail")}
          onConfirmAll={confirmAll}
          onSend={openSend}
          onMediaError={onMediaError}
        />
      ) : (
        <div className={cn("grid items-start gap-4", wide && "grid-cols-[280px_minmax(0,1fr)] xl:grid-cols-[320px_minmax(0,1fr)]")}>
          {showList && (
            <StepList
              steps={steps}
              selectedId={wide ? selected?.id ?? null : null}
              onSelect={(id) => select(id, wide ? null : "detail")}
              onMove={move}
              onAddStep={addStep}
              onToggleGroupBreak={(id, v) => patch(id, { group_break: v }, copy.reorderFailed)}
              blockedIds={blockedIds}
              busy={reorderBusy}
              onMediaError={onMediaError}
              headingRef={listHeading}
            />
          )}
          {showDetail && selected && (
            <StepDetail
              key={`${selected.id}:${reloadCount}`}
              ref={detailHeading}
              step={selected}
              index={selectedIndex}
              total={steps.length}
              candidates={candidates[selected.id]}
              confirming={pendingConfirm.has(selected.id)}
              blocked={blockedIds.has(selected.id)}
              readOnly={rewritingId !== null && rewritingId !== selected.id}
              rewriting={rewritingId === selected.id}
              onUndo={activeUndo && activeUndo.stepIds.includes(selected.id) ? undoSplit : undefined}
              onConfirm={() => confirmStep(selected.id)}
              onApplyCandidate={(c) => void applyCandidate(selected.id, c)}
              onOpenPicker={(mode) => setPicker({ stepId: selected.id, mode })}
              onRemovePhoto={() => removePhoto(selected.id)}
              onAutosave={(t) => autosave(selected.id, t)}
              onCommit={(t) => commit(selected.id, t)}
              onToggleCaution={(v) => patch(selected.id, { safety_flag: v }, copy.cautionFailed)}
              onDelete={() => setToDelete(selected.id)}
              onVoice={() => voice(selected.id)}
              onMediaError={onMediaError}
              onBack={
                wide
                  ? undefined
                  : () => {
                      const id = selected.id;
                      setSelectedId(null);
                      setPickFirstReview(false);
                      focusWant.current = { row: id };
                    }
              }
            />
          )}
        </div>
      )}

      {/* 390: 아래 고정 줄(아래 탭바 위) */}
      {!wide && (
        // 두 줄: 위는 '확인할 것 n개 남음 · [다음 ▶]', 아래는 [그림 한눈에][보내기]. 한 줄이면 390에서 [다음 ▶]가
        // [그림 한눈에]에 가려지고 320(200% 확대)에서는 아예 보이지 않았다(1회차 검증).
        <div
          data-testid="editor-bottom-bar"
          ref={bottomBar}
          className="fixed inset-x-0 bottom-tabbar z-20 flex flex-col gap-2 border-t border-paper-200 bg-white px-4 py-2"
        >
          <ReviewQueueBar
            remaining={remaining}
            total={steps.length}
            compact
            onNext={nextReview}
            nextRef={(el) => {
              if (!wide) nextButton.current = el;
            }}
          />
          <div className="grid grid-cols-2 gap-2">
            <Button
              variant="secondary"
              onClick={openOverview}
              className="w-full"
              icon={<Images size={16} strokeWidth={2} aria-hidden="true" />}
            >
              {copy.overview}
            </Button>
            {sendBtn(mobileSendButton, "editor-send-mobile", "w-full")}
          </div>
        </div>
      )}

      <PicturePicker
        open={!!picker}
        mode={picker?.mode ?? "search"}
        stepNo={picker ? steps.findIndex((s) => s.id === picker.stepId) + 1 : 0}
        initialQuery={picker ? steps.find((s) => s.id === picker.stepId)?.sentence ?? "" : ""}
        onClose={() => setPicker(null)}
        onApply={(c) => (picker ? applyCandidate(picker.stepId, c) : Promise.resolve(false))}
        onUpload={(f) => (picker ? upload(picker.stepId, f) : Promise.resolve(false))}
      />

      <Dialog
        open={!!toDelete}
        onClose={() => setToDelete(null)}
        tone="danger"
        title={copy.deleteTitle(Math.max(1, steps.findIndex((s) => s.id === toDelete) + 1))}
        description={copy.deleteBody}
        confirmLabel={copy.deleteConfirm}
        onConfirm={() => void confirmDelete()}
        busy={deleting}
      />

      <SendSheet
        open={sendOpen}
        onClose={() => setSendOpen(false)}
        taskId={task.id}
        hasUnsentChanges={!!task.version?.has_unsent_changes}
        versionNo={task.version?.current_no ?? null}
        onGoToStep={goToStep}
        onSent={onSent}
      />
    </div>
  );
}
