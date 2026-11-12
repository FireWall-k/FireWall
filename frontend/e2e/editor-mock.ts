import type { Page, Route } from "@playwright/test";
import { API, makeHelp } from "./employer-mock";

// 2b-1 새 직무·편집기·보내기 e2e용 가짜 백엔드(page.route). contract §3.3·3.4·1.4 모양을 흉내 낸다 — 실제 서버·GPT 없이.
// 그림은 1×1 PNG로 준다(실제로 decode되어 [보이는 자동 그림 모두 맞아요]가 켜진다). 목에 없는 요청은 599.
// 실제 서버 흐름은 e2e-real/clicks-real.spec.ts·real-flow.spec.ts가 본다.

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET,POST,PATCH,DELETE,OPTIONS",
};
const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

/** 고정 문장(p2/b1_fixed_sentence.txt): 규칙 엔진만으로 6단계 모두 auto_high, 1단계는 '칼'로 자동 조심. */
export const FIXED_SENTENCE =
  "커터칼로 상자를 열어요. 상품을 선반에 놓아요. 같은 상품끼리 모아요. 테이블을 행주로 닦아요. 바닥을 빗자루로 쓸어요. 손을 씻어요.";
export const FIXED_STEPS = [
  "커터칼로 상자를 열어요.",
  "상품을 선반에 놓아요.",
  "같은 상품끼리 모아요.",
  "테이블을 행주로 닦아요.",
  "바닥을 빗자루로 쓸어요.",
  "손을 씻어요.",
];

type PictureState = "confirmed" | "auto_high" | "choose" | "none";

export interface MockStep {
  id: string;
  sentence: string;
  state: PictureState;
  url: string | null;
  source: "auto" | "manual" | "photo";
  safety: boolean;
  safetySource: "auto" | "manual" | "";
  groupBreak: boolean;
  span: string;
}

export interface MockEditorTask {
  id: string;
  title: string;
  raw: string;
  steps: MockStep[];
  updatedAt: string;
  versionNo: number | null;
  sentSnapshot: string | null;
  recipients: string[];
  lastBatch: string[];
  archived: boolean;
  createdAt: string;
}

export interface EditorMock {
  tasks: MockEditorTask[];
  workers: { id: string; display_name: string; access_code: string }[];
  calls: string[];
  sends: { taskId: string; workerIds: string[]; day: string }[];
  /** 그림 주소 요청을 이만큼 늦춘다(ms). */
  imageDelayMs: number;
  /** POST /api/tasks로 받은 본문(만든 순서). */
  creates: { raw_input: string; steps: { sentence: string }[] }[];
}

export interface EditorMockOptions {
  tasks?: MockEditorTask[];
  workers?: EditorMock["workers"];
  /** split-preview 응답을 이것으로(애매한 줄·묶음 시험). 없으면 문장마다 한 단계. */
  preview?: unknown;
  /** POST /api/tasks를 502로 실패시킨다. */
  createFails?: boolean;
}

const SAFETY_WORDS = ["칼", "가위", "뜨거운", "세제", "락스", "기계", "칼날", "사다리", "전기"];
const isSafety = (s: string) => SAFETY_WORDS.some((w) => s.includes(w));
let seq = 0;
const nid = (p: string) => `${p}${++seq}`;
const now = () => new Date(Date.now() + seq).toISOString().replace("Z", "");
const pic = (id: string) => `${API}/api/aac/images/e2e/${id}.webp`;

function newStep(sentence: string, state: PictureState = "auto_high", over: Partial<MockStep> = {}): MockStep {
  const id = nid("s");
  return {
    id, sentence, state, url: state === "none" ? null : pic(id), source: "auto",
    safety: isSafety(sentence), safetySource: isSafety(sentence) ? "auto" : "", groupBreak: false, span: "", ...over,
  };
}

export function makeTask(steps: MockStep[], over: Partial<MockEditorTask> = {}): MockEditorTask {
  return {
    id: nid("task-"), title: "상자 정리", raw: FIXED_SENTENCE, steps, updatedAt: now(), versionNo: null, sentSnapshot: null,
    recipients: [], lastBatch: [], archived: false, createdAt: now(), ...over,
  };
}

/** 고정 문장 6단계 초안(모두 ✦ 자동). */
export function fixedDraft(over: Partial<MockEditorTask> = {}): MockEditorTask {
  return makeTask(FIXED_STEPS.map((s) => newStep(s)), over);
}

/** 그림 4상태가 다 있는 초안. */
export function fourStateDraft(): MockEditorTask {
  return makeTask([
    newStep("앞치마를 입어요.", "confirmed"),
    newStep("컵을 물에 넣어요.", "auto_high"),
    newStep("컵을 수세미로 닦아요.", "choose"),
    newStep("컵을 건조대에 엎어요.", "none"),
  ], { title: "컵 씻기" });
}

function lint(sentence: string) {
  const out: { code: string; from: string | null; to: string | null }[] = [];
  if (sentence.replace(/\s/g, "").length > 20) out.push({ code: "too_long", from: null, to: null });
  if (sentence.includes("적재")) out.push({ code: "hard_word", from: "적재", to: "쌓기" });
  if (/(하세요|하십시오)[.!]?$/.test(sentence.trim())) out.push({ code: "command_tone", from: null, to: null });
  return out;
}

const snapshot = (t: MockEditorTask) => JSON.stringify(t.steps.map((s) => [s.sentence, s.url, s.safety, s.groupBreak]));

function stepOut(t: MockEditorTask, s: MockStep, i: number) {
  return {
    id: s.id, order: i + 1, sentence: s.sentence, action_type: "other", symbol_url: s.url,
    symbol_source: s.source === "photo" ? "photo" : s.url ? "LOCAL_AAC" : "fallback",
    needs_fallback: s.state === "choose" || s.state === "none", tts_audio_url: null, picture_state: s.state,
    safety_flag: s.safety,
    picture: s.url ? { card_id: s.id, url: s.url, label: `${s.sentence.slice(0, 6)} 그림`, source: s.source } : null,
    candidates: [],
    split: { source: s.span ? "model" : "", needs_review: false, original_span: s.span },
    lint: lint(s.sentence),
    safety: { flag: s.safety, source: s.safetySource, note: "" },
    group_break: s.groupBreak,
    task_updated_at: t.updatedAt,
  };
}

function taskOut(t: MockEditorTask) {
  return {
    id: t.id, title: t.title, status: t.versionNo ? "published" : "draft",
    steps: t.steps.map((s, i) => stepOut(t, s, i)),
    version: t.versionNo ? { current_no: t.versionNo, has_unsent_changes: t.sentSnapshot !== snapshot(t) } : null,
    in_progress_count: 0, recipients_count: t.recipients.length, updated_at: t.updatedAt,
  };
}

function summary(t: MockEditorTask) {
  return {
    id: t.id, title: t.title, state: t.archived ? "archived" : t.versionNo ? "published" : "draft",
    needs_check_count: t.steps.filter((s) => s.state !== "confirmed").length,
    has_unsent_changes: !!t.versionNo && t.sentSnapshot !== snapshot(t), step_count: t.steps.length,
    cover_url: t.steps[0]?.url ?? null, recipients: t.recipients.slice(0, 3).map((w) => ({ worker_id: w, initials: "김" })),
    recipients_more: Math.max(0, t.recipients.length - 3), updated_at: t.updatedAt, current_version_no: t.versionNo,
  };
}

function sendCheck(t: MockEditorTask) {
  const ids = (f: (s: MockStep) => boolean) => t.steps.filter(f).map((s) => s.id);
  const none = ids((s) => s.state === "none");
  const withPic = t.steps.filter((s) => s.state !== "none");
  const unconfirmed = ids((s) => s.state === "auto_high" || s.state === "choose");
  const blocking = [
    { code: "no_picture", done: t.steps.length - none.length, total: t.steps.length, step_ids: none },
    { code: "unconfirmed_auto", done: withPic.length - unconfirmed.length, total: withPic.length, step_ids: unconfirmed },
    { code: "unreviewed_split", done: 0, total: 0, step_ids: [] },
  ];
  const long = ids((s) => lint(s.sentence).some((l) => l.code === "too_long"));
  const tone = ids((s) => lint(s.sentence).some((l) => l.code === "command_tone"));
  const caution = ids((s) => s.safety && s.safetySource === "auto");
  return {
    ok: blocking.every((b) => b.done >= b.total),
    blocking,
    warnings: [
      { code: "too_long", count: long.length, step_ids: long },
      { code: "command_tone", count: tone.length, step_ids: tone },
      { code: "auto_caution", count: caution.length, step_ids: caution },
    ],
  };
}

export async function mockEditor(page: Page, opts: EditorMockOptions = {}): Promise<EditorMock> {
  const m: EditorMock = {
    tasks: opts.tasks ?? [],
    workers: opts.workers ?? [{ id: "w1", display_name: "김민지", access_code: "4821" }],
    calls: [],
    sends: [],
    imageDelayMs: 0,
    creates: [],
  };
  await page.route("https://cdn.jsdelivr.net/**", (route) => route.abort());
  await page.route(`${API}/**`, async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    const method = req.method();
    const path = url.pathname;
    if (method === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
    m.calls.push(`${method} ${path}${url.search}`);
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, headers: { ...CORS, "content-type": "application/json" }, body: JSON.stringify(body) });
    const body = () => (req.postData() ? (req.postDataJSON() as Record<string, unknown>) : {});

    if (path.startsWith("/api/aac/images/") || path.startsWith("/media/")) {
      if (m.imageDelayMs) await new Promise((r) => setTimeout(r, m.imageDelayMs));
      return route.fulfill({ status: 200, headers: { ...CORS, "content-type": "image/png" }, body: PNG_1X1 });
    }
    if (path === "/api/auth/demo") return json({ detail: "없음" }, 404);
    if (path === "/api/employer/help") return json([] as ReturnType<typeof makeHelp>[]);
    if (path === "/api/workers" && method === "GET") {
      return json(m.workers.map((w) => ({ ...w, access_code_hint: w.access_code.slice(-2), access_code_length: 4 })));
    }
    if (path === "/api/workplace") return json({ workplace_code: "AB12CD", org_name: "테스트 사업장" });
    if (path === "/api/tasks" && method === "GET") return json([]);
    if (path === "/api/employer/tasks" && method === "GET") {
      const live = m.tasks.filter((t) => !t.archived);
      const items = live.map(summary);
      return json({
        items,
        counts: {
          all: live.length, draft: items.filter((i) => i.state === "draft").length,
          needs_check: items.filter((i) => i.needs_check_count > 0).length,
          published: items.filter((i) => i.state === "published").length, archived: m.tasks.length - live.length,
        },
      });
    }
    if (path === "/api/aac/search" && method === "POST") {
      const q = String(body().query ?? "그림");
      return json({ query: q, matches: [1, 2, 3].map((k) => ({ asset_id: `Q${k}`, group_id: "g", job: "e2e", asset_type: "aac", label: `${q} ${k}`, image_url: pic(`Q${k}`), score: 0.9 })) });
    }
    if (path === "/api/tasks/split-preview" && method === "POST" && opts.preview) return json(opts.preview);
    if (path === "/api/tasks/split-preview" && method === "POST") {
      const raw = String(body().raw_input ?? "");
      const parts = raw.split(/(?<=[.!?])\s+/).map((s) => s.trim()).filter(Boolean);
      return json({
        task_title: "상자 정리", job: "",
        steps: parts.map((s, i) => ({
          order: i + 1, sentence: s, action_type: "other", symbol_query: [], split_group: null, split_check: false,
          source_text: null, safety_flag: isSafety(s),
        })),
      });
    }
    if (path === "/api/tasks" && method === "POST") {
      const b = body() as { raw_input: string; title?: string; steps: { sentence: string; safety_flag?: boolean; split?: { original_span?: string } }[] };
      m.creates.push(b);
      if (opts.createFails) return json({ detail: "초안을 만들지 못했어요. 잠시 뒤 다시 눌러 주세요." }, 502);
      const t = makeTask(
        b.steps.map((s) => newStep(s.sentence, "auto_high", { span: s.split?.original_span ?? "", safety: !!s.safety_flag || isSafety(s.sentence), safetySource: s.safety_flag || isSafety(s.sentence) ? "auto" : "" })),
        { title: b.title ?? "상자 정리", raw: b.raw_input },
      );
      m.tasks.unshift(t);
      return json(taskOut(t), 201);
    }

    const tm = path.match(/^\/api\/tasks\/([^/]+)(\/.*)?$/);
    if (!tm) return route.fulfill({ status: 599, headers: CORS, body: `unmocked ${method} ${path}` });
    const t = m.tasks.find((x) => x.id === decodeURIComponent(tm[1]));
    if (!t) return json({ detail: "직무를 찾을 수 없어요." }, 404);
    const rest = tm[2] ?? "";
    const touch = () => {
      t.updatedAt = now();
    };
    const find = (sid: string) => t.steps.find((s) => s.id === decodeURIComponent(sid));
    const outOf = (s: MockStep) => stepOut(t, s, t.steps.indexOf(s));

    if (rest === "" && method === "GET") return json(taskOut(t));
    if (rest === "" && method === "PATCH") {
      t.title = String(body().title ?? t.title);
      touch();
      return json(taskOut(t));
    }
    if (rest === "/candidates") {
      return json({ steps: t.steps.map((s) => ({ step_id: s.id, candidates: [1, 2, 3].map((k) => ({ card_id: `${s.id}c${k}`, url: pic(`${s.id}c${k}`), label: `후보 그림 ${k}` })) })) });
    }
    if (rest === "/send-check") return json(sendCheck(t));
    if (rest === "/recipients") {
      const status: Record<string, string> = {};
      for (const w of m.workers) status[w.id] = "none";
      return json({ last_batch_worker_ids: t.lastBatch, all_ever_worker_ids: t.recipients, workplace_last_batch_worker_ids: m.sends.at(-1)?.workerIds ?? [], today_status: status });
    }
    if (rest === "/send" && method === "POST") {
      const b = body() as { worker_ids: string[]; day: string };
      const check = sendCheck(t);
      if (!check.ok) return json({ detail: "자동으로 고른 그림을 아직 확인하지 않았어요. 확인한 뒤 다시 보내 주세요.", code: "send_blocked", step_ids: [] }, 422);
      const changed = t.sentSnapshot !== snapshot(t);
      if (changed) {
        t.versionNo = (t.versionNo ?? 0) + 1;
        t.sentSnapshot = snapshot(t);
      }
      t.lastBatch = b.worker_ids;
      t.recipients = [...new Set([...t.recipients, ...b.worker_ids])];
      m.sends.push({ taskId: t.id, workerIds: b.worker_ids, day: b.day });
      return json({
        version_no: t.versionNo, version_created: changed, day: "2026-11-10",
        results: b.worker_ids.map((id) => ({ worker_id: id, display_name: m.workers.find((w) => w.id === id)?.display_name ?? "", outcome: "created" })),
      });
    }
    if (rest === "/pictures/confirm" && method === "POST") {
      const ids = (body().step_ids as string[]) ?? [];
      const bad = ids.map(find).filter((s) => !s || s.state === "choose" || s.state === "none");
      if (bad.length) return json({ detail: "확인할 수 없는 단계가 있어요", code: "not_confirmable", step_ids: [] }, 422);
      const out = ids.map((id) => {
        const s = find(id)!;
        if (s.state === "auto_high") s.state = "confirmed";
        return s;
      });
      touch();
      return json(out.map(outOf));
    }
    if (rest === "/steps/reorder" && method === "PATCH") {
      const ids = body().step_ids as string[];
      t.steps = ids.map((id) => find(id)!).filter(Boolean);
      touch();
      return json(taskOut(t));
    }
    if (rest === "/steps" && method === "POST") {
      const s = newStep(String(body().sentence ?? ""));
      t.steps.push(s);
      touch();
      return json({ ...taskOut(t), split_step_ids: [], sentence: s.sentence }, 201);
    }
    if (rest === "/steps/merge" && method === "POST") return json(taskOut(t));
    const sm = rest.match(/^\/steps\/([^/]+)(\/.*)?$/);
    if (sm) {
      const s = find(sm[1]);
      if (!s) return json({ detail: "단계를 찾을 수 없습니다." }, 404);
      const sub = sm[2] ?? "";
      if (sub === "" && method === "PATCH") {
        const b = body() as { sentence?: string; safety_flag?: boolean; group_break?: boolean; expected_updated_at?: string };
        if (b.expected_updated_at && b.expected_updated_at !== t.updatedAt) {
          return json({ detail: "다른 창에서 먼저 고쳤어요. 새로 불러온 뒤 다시 고쳐 주세요.", code: "stale_edit", step_ids: [s.id] }, 409);
        }
        if (b.sentence !== undefined) s.sentence = b.sentence;
        if (b.safety_flag !== undefined) {
          s.safety = b.safety_flag;
          s.safetySource = "manual";
        }
        if (b.group_break !== undefined) s.groupBreak = b.group_break;
        touch();
        return json(outOf(s));
      }
      if (sub === "" && method === "DELETE") {
        t.steps = t.steps.filter((x) => x !== s);
        touch();
        return json(taskOut(t));
      }
      if (sub === "/rewrite" && method === "POST") {
        s.sentence = String(body().sentence ?? s.sentence);
        touch();
        return json({ task: taskOut(t), split_step_ids: [], sentence: s.sentence });
      }
      if (sub === "/picture/confirm" && method === "POST") {
        if (s.state === "auto_high") s.state = "confirmed";
        touch();
        return json(outOf(s));
      }
      if (sub === "/picture" && method === "POST") {
        const b = body() as { card_id: string; url: string };
        s.url = b.url;
        s.source = "manual";
        s.state = "confirmed";
        touch();
        return json(outOf(s));
      }
      if (sub === "/symbol-candidates") {
        return json({ step_id: s.id, reason: "low_margin", candidates: [1, 2, 3].map((k) => ({ asset_id: `${s.id}c${k}`, group_id: "g", job: "e2e", asset_type: "aac", label: `후보 그림 ${k}`, image_url: pic(`${s.id}c${k}`), score: 0.5 })) });
      }
      if (sub === "/tts" && method === "POST") return json({ tts_url: null });
    }
    return route.fulfill({ status: 599, headers: CORS, body: `unmocked ${method} ${path}` });
  });
  return m;
}
