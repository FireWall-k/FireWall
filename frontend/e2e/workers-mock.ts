import type { Page, Route } from "@playwright/test";
import { API } from "./employer-mock";

// (2d) 근로자·설정 화면 가짜 백엔드(contract §6.2 모양). mockEmployer 뒤에 부르면 이 경로들을 먼저 받는다
// (Playwright는 나중에 단 route가 먼저 받는다). 나머지는 mockEmployer로 넘긴다(fallback).
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET,POST,PATCH,DELETE,OPTIONS",
};

const PREFS = {
  font_size: "normal", autoplay_sound: true, tts_rate: 0.9, sfx: true, vibration: false, praise: "normal", hand: "right", contrast: "normal",
};

export function makeWorker(over: Record<string, unknown> = {}) {
  return {
    id: "w1", display_name: "김민지", access_code_hint: "34", access_code_length: 4, code_length: 4, note: "", ai_note_allowed: false,
    ai_consent: false, personal_info_consent: true, name_ambiguous: false, a11y_prefs: { ...PREFS }, today_badge: "help",
    done_7d: [0, 1, 0, 2, 1, 0, 1], help_7d: 2, consent_state: "ai_missing", ...over,
  };
}

export interface WorkersMock {
  workers: ReturnType<typeof makeWorker>[];
  workplace: Record<string, unknown>;
  calls: string[];
  codes: Record<string, string>;
}

export async function mockWorkers(page: Page, opts: { empty?: boolean } = {}): Promise<WorkersMock> {
  const m: WorkersMock = {
    workers: opts.empty
      ? []
      : [
          makeWorker(),
          makeWorker({ id: "w2", display_name: "이준호", today_badge: "help_coming", consent_state: "complete", ai_consent: true }),
          makeWorker({ id: "w3", display_name: "박서연", today_badge: "done", help_7d: 0 }),
          makeWorker({ id: "w4", display_name: "최하늘", today_badge: "not_started", consent_state: "missing", personal_info_consent: false }),
        ],
    workplace: {
      workplace_code: "AB12CD", org_name: "햇살카페", device_link: "http://localhost:5173/worker?site=AB12CD",
      teacher_title: "선생님", worker_defaults: { ...PREFS },
    },
    calls: [],
    codes: { w1: "4821", w2: "1357", w3: "2468", w4: "9090" },
  };
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(Date.now() - (6 - i) * 86_400_000);
    return d.toISOString().slice(0, 10);
  });
  const handler = async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    const method = req.method();
    const path = url.pathname;
    if (method === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, headers: { ...CORS, "content-type": "application/json" }, body: JSON.stringify(body) });
    const body = () => (req.postData() ? (req.postDataJSON() as Record<string, unknown>) : {});
    m.calls.push(`${method} ${path}${url.search}`);

    if (path === "/api/workers" && method === "GET") return json(m.workers);
    if (path === "/api/workers" && method === "POST") {
      const b = body();
      const w = makeWorker({ id: `w${m.workers.length + 10}`, display_name: b.display_name, today_badge: "none", done_7d: [0, 0, 0, 0, 0, 0, 0], help_7d: 0 });
      m.workers.push(w);
      m.codes[w.id as string] = "0712";
      return json({ ...w, access_code: "0712" }, 201);
    }
    if (path === "/api/workplace" && method === "GET") return json(m.workplace);
    if (path === "/api/workplace" && method === "PATCH") {
      const b = body();
      if (b.teacher_title !== undefined && !/^[가-힣]{1,6}$/.test(String(b.teacher_title))) {
        return json({ detail: "호칭은 한글 1~6자로 적어 주세요." }, 422);
      }
      m.workplace = {
        ...m.workplace,
        ...(b.org_name !== undefined ? { org_name: b.org_name } : {}),
        ...(b.teacher_title !== undefined ? { teacher_title: b.teacher_title } : {}),
        worker_defaults: { ...(m.workplace.worker_defaults as object), ...((b.worker_defaults as object) ?? {}) },
      };
      return json(m.workplace);
    }
    let mm = path.match(/^\/api\/workers\/([^/]+)\/access-code\/reveal$/);
    if (mm && method === "POST") return json({ code: m.codes[mm[1]] ?? "0000" });
    mm = path.match(/^\/api\/workers\/([^/]+)\/access-code$/);
    if (mm && method === "POST") {
      m.codes[mm[1]] = "5590";
      return json({ ...m.workers.find((w) => w.id === mm![1]), access_code: "5590" });
    }
    mm = path.match(/^\/api\/workers\/([^/]+)\/delete$/);
    if (mm && method === "POST") {
      const w = m.workers.find((x) => x.id === mm![1]);
      if (!w) return json({ detail: "근로자를 찾을 수 없습니다." }, 404);
      if (String(body().confirm_name).trim() !== w.display_name) {
        return json({ detail: "이름이 맞지 않아요. 지울 근로자 이름을 그대로 적어 주세요." }, 422);
      }
      m.workers = m.workers.filter((x) => x !== w);
      return json({ ok: true, wal_checkpointed: true, name_mentions: [] });
    }
    mm = path.match(/^\/api\/workers\/([^/]+)$/);
    if (mm && method === "PATCH") {
      const w = m.workers.find((x) => x.id === mm![1]);
      if (!w) return json({ detail: "근로자를 찾을 수 없습니다." }, 404);
      const b = body();
      if (b.a11y_prefs) w.a11y_prefs = { ...w.a11y_prefs, ...(b.a11y_prefs as object) };
      if (b.note !== undefined) w.note = String(b.note);
      if (b.ai_note_allowed !== undefined) w.ai_note_allowed = !!b.ai_note_allowed;
      return json(w);
    }
    mm = path.match(/^\/api\/workers\/([^/]+)\/consents$/);
    if (mm && method === "POST") return json({ id: "c1", consent_type: body().consent_type, subject: body().subject, policy_version: "v1", granted_at: "2026-11-10T00:00:00", revoked_at: null, recorded_by: "e" });
    if (mm && method === "GET") return json([]);
    mm = path.match(/^\/api\/employer\/workers\/([^/]+)\/stats$/);
    if (mm) {
      return json({
        worker_id: mm[1], days: 7,
        daily: days.map((day, i) => ({ day, assigned: 1, done: i % 3 === 0 ? 1 : 0, steps_done: 4, help: i === 6 ? 1 : 0, work_sec: 300 })),
        steps: [
          { task_id: "t3", task_title: "택배 상자 포장하기", order: 1, sentence: "상자를 펴요", samples: 4, avg_duration_sec: 148, replay_count: 3, help_count: 1 },
          { task_id: "t3", task_title: "택배 상자 포장하기", order: 2, sentence: "물건을 넣어요", samples: 4, avg_duration_sec: 62, replay_count: 0, help_count: 0 },
        ],
        avg_step_sec: 105,
      });
    }
    return route.fallback();
  };
  await page.route(`${API}/api/workers**`, handler);
  await page.route(`${API}/api/workplace`, handler);
  await page.route(`${API}/api/employer/workers/**`, handler);
  return m;
}

/** 화면에 보이는 글자 중 가장 작은 크기(px). 명세 6.2: 12px 이상. */
export async function minFontPx(page: Page): Promise<{ px: number; text: string }> {
  return page.evaluate(() => {
    let best = { px: 999, text: "" };
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const t = (n.textContent ?? "").trim();
      const el = n.parentElement;
      if (!t || !el) continue;
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      if (cs.visibility === "hidden" || cs.display === "none" || r.width === 0 || r.height === 0) continue;
      // 화면 읽기 전용(sr-only, 1px 클립)은 보이는 글이 아니다.
      if (r.width <= 1 && r.height <= 1) continue;
      const px = parseFloat(cs.fontSize);
      if (px < best.px) best = { px, text: t.slice(0, 30) };
    }
    return best;
  });
}
