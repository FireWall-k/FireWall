import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { DEFAULT_A11Y_PREFS, type A11yPrefs } from "../../src/api";
import { COPY } from "../../src/worker/copy";
import { jobProgress } from "../../src/worker/resume";
import { SessionContext, type WorkerSessionValue } from "../../src/worker/session";
import * as speech from "../../src/worker/speech";
import TodayScreen from "../../src/worker/TodayScreen";
import { normalizeJob, type TodayJob } from "../../src/worker/workerApi";

// 2차 검증: '새 일이 왔어요'만 근로자의 소리 자동 재생 설정을 보지 않았다(결정 4).
const job = (aid: string): TodayJob =>
  normalizeJob({ assignment_id: aid, task_id: "t", task_title: `일 ${aid}`, steps: [] });

function value(jobs: TodayJob[], prefs: Partial<A11yPrefs>): WorkerSessionValue {
  const p = { ...DEFAULT_A11Y_PREFS, ...prefs };
  return {
    me: { id: "w1", display_name: "민수", workplace_name: "행복카페", teacher_title: "선생님", a11y_prefs: p },
    prefs: p, jobs, online: true, synced: false, pendingCount: 0, unsentNote: null,
    refresh: async () => {}, progressOf: (j) => jobProgress(j.steps, new Set()), localDoneIds: () => [],
    completeStep: () => {}, onMediaError: () => {}, logout: () => {}, reportError: () => {},
  };
}

function renderWith(jobs: TodayJob[], prefs: Partial<A11yPrefs>) {
  const ui = (v: WorkerSessionValue) => (
    <MemoryRouter><SessionContext.Provider value={v}><TodayScreen /></SessionContext.Provider></MemoryRouter>
  );
  const r = render(ui(value(jobs, prefs)));
  return { rerender: (next: TodayJob[]) => r.rerender(ui(value(next, prefs))) };
}

describe("오늘 할 일: 새 일 알림 소리", () => {
  it("소리 자동 재생을 켠 근로자에게만 읽는다", () => {
    const spy = vi.spyOn(speech, "speakText").mockImplementation(() => {});
    const on = renderWith([job("a1")], { autoplay_sound: true });
    on.rerender([job("a1"), job("a2")]);
    expect(spy).toHaveBeenCalledWith(COPY.band.newJob, expect.anything());
    spy.mockClear();
    const off = renderWith([job("b1")], { autoplay_sound: false });
    off.rerender([job("b1"), job("b2")]);
    expect(spy).not.toHaveBeenCalledWith(COPY.band.newJob, expect.anything());
    spy.mockRestore();
  });
});
