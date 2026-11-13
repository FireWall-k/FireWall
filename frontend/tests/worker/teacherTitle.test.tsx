import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { COPY, FORBIDDEN_PATTERNS, teacherCopy, withJosa } from "../../src/worker/copy";
import {
  applySiteCode,
  getSavedTeacherTitle,
  getSavedWorkplaceCode,
  getSavedWorkplaceName,
  saveTeacherTitle,
  saveWorkplaceCode,
  saveWorkplaceName,
} from "../../src/workerCodes";

// (2d, contract §6.2) 호칭은 사업장 설정. 근로자 문구는 받침에 맞춰 조사를 붙이고, 로그인 전에는 저장값 또는 '선생님'.
// /worker?site=CODE는 기기에 사업장 코드를 저장하고(다르면 예전 가게 이름 지움) 주소에서 site를 뺀다.

function flat(v: unknown, p = ""): [string, string][] {
  if (typeof v === "string") return [[p, v]];
  if (v && typeof v === "object") return Object.entries(v).flatMap(([k, x]) => flat(x, p ? `${p}.${k}` : k));
  return [];
}

beforeEach(() => localStorage.clear());

describe("withJosa", () => {
  it("받침 있음 / 없음 / '께'는 그대로", () => {
    expect(withJosa("선생님", "이/가")).toBe("선생님이");
    expect(withJosa("코치", "이/가")).toBe("코치가");
    expect(withJosa("선생님", "을/를")).toBe("선생님을");
    expect(withJosa("코치", "을/를")).toBe("코치를");
    expect(withJosa("선생님", "은/는")).toBe("선생님은");
    expect(withJosa("코치", "은/는")).toBe("코치는");
    expect(withJosa("선생님", "께")).toBe("선생님께");
    expect(withJosa("코치", "께")).toBe("코치께");
  });
});

describe("teacherCopy: 받침 없는 '코치'와 받침 있는 '선생님'으로 모든 키", () => {
  const expected: Record<string, [string, string]> = {
    "btn.teacherSetup": ["선생님용: 기기 연결하기", "코치용: 기기 연결하기"],
    "btn.teacherLongCode": ["선생님용: 긴 번호로 들어가기", "코치용: 긴 번호로 들어가기"],
    "login.askTeacher": ["선생님께 번호를 물어봐요.", "코치께 번호를 물어봐요."],
    "login.tooMany": ["잠깐 쉬었다가 다시 눌러 봐요. 선생님께 말해 주세요.", "잠깐 쉬었다가 다시 눌러 봐요. 코치께 말해 주세요."],
    "help.sending": ["선생님을 부르는 중이에요", "코치를 부르는 중이에요"],
    "help.sent": ["선생님을 불렀어요. 여기서 기다려요.", "코치를 불렀어요. 여기서 기다려요."],
    "help.failed": ["아직 못 불렀어요. 손을 들어 선생님을 불러요.", "아직 못 불렀어요. 손을 들어 코치를 불러요."],
    "help.acked": ["선생님이 확인했어요", "코치가 확인했어요"],
    "status.emptyBody": ["선생님이 일을 보내면 여기에 나와요.", "코치가 일을 보내면 여기에 나와요."],
    "status.unpairedBody": ["선생님께 말해 주세요.", "코치께 말해 주세요."],
    "allDone.body": ["선생님께 알려 주세요.", "코치께 알려 주세요."],
    "setup.body": ["선생님이 하는 곳이에요. 가게 코드를 넣어 주세요.", "코치가 하는 곳이에요. 가게 코드를 넣어 주세요."],
  };

  it("키 목록이 계약과 같고, 두 호칭 모두 글자 그대로 맞다", () => {
    const a = Object.fromEntries(flat(teacherCopy("선생님")));
    const b = Object.fromEntries(flat(teacherCopy("코치")));
    expect(Object.keys(a).sort()).toEqual(Object.keys(expected).sort());
    for (const [k, [sun, coach]] of Object.entries(expected)) {
      expect(a[k], k).toBe(sun);
      expect(b[k], k).toBe(coach);
    }
  });

  it("호칭 문구도 근로자 금지어가 없다", () => {
    for (const t of ["선생님", "코치"]) {
      for (const [k, s] of flat(teacherCopy(t))) {
        for (const re of FORBIDDEN_PATTERNS) expect(re.test(s), `${t} ${k}: ${s}`).toBe(false);
      }
    }
  });
});

describe("COPY는 기기에 저장된 호칭으로 읽는다(로그인 전에는 저장값 또는 '선생님')", () => {
  it("저장값이 없으면 '선생님'", () => {
    expect(getSavedTeacherTitle()).toBe("선생님");
    expect(COPY.login.askTeacher).toBe("선생님께 번호를 물어봐요.");
    expect(COPY.help.acked).toBe("선생님이 확인했어요");
    expect(COPY.btn.teacherSetup).toBe("선생님용: 기기 연결하기");
  });

  it("저장하면 같은 자리가 바로 바뀐다", () => {
    saveTeacherTitle("코치");
    expect(COPY.login.askTeacher).toBe("코치께 번호를 물어봐요.");
    expect(COPY.help.sent).toBe("코치를 불렀어요. 여기서 기다려요.");
    expect(COPY.status.empty.body).toBe("코치가 일을 보내면 여기에 나와요.");
    expect(COPY.status.unpaired.body).toBe("코치께 말해 주세요.");
    expect(COPY.allDone.body).toBe("코치께 알려 주세요.");
    expect(COPY.setup.body).toBe("코치가 하는 곳이에요. 가게 코드를 넣어 주세요.");
  });

  it("규칙(한글 1~6자) 밖의 값은 저장하지 않고, 저장된 값이 이상하면 '선생님'", () => {
    saveTeacherTitle("Coach");
    expect(getSavedTeacherTitle()).toBe("선생님");
    localStorage.setItem("jobcard_teacher_title", "아주아주긴호칭이에요");
    expect(getSavedTeacherTitle()).toBe("선생님");
  });
});

describe("/worker?site=CODE", () => {
  it("저장된 코드가 없으면 저장한다(정규화)", () => {
    expect(applySiteCode(" demo-01 ")).toBe(true);
    expect(getSavedWorkplaceCode()).toBe("DEMO01");
  });

  it("같은 코드면 아무것도 지우지 않는다", () => {
    saveWorkplaceCode("DEMO01");
    saveWorkplaceName("햇살카페");
    saveTeacherTitle("코치");
    expect(applySiteCode("DEMO01")).toBe(false);
    expect(getSavedWorkplaceName()).toBe("햇살카페");
    expect(getSavedTeacherTitle()).toBe("코치");
  });

  it("다른 코드면 예전 가게 이름·호칭을 지우고 새 코드를 저장한다", () => {
    saveWorkplaceCode("DEMO01");
    saveWorkplaceName("햇살카페");
    saveTeacherTitle("코치");
    expect(applySiteCode("NEW777")).toBe(true);
    expect(getSavedWorkplaceCode()).toBe("NEW777");
    expect(getSavedWorkplaceName()).toBeNull();
    expect(getSavedTeacherTitle()).toBe("선생님");
  });

  it("빈 값은 무시한다", () => {
    saveWorkplaceCode("DEMO01");
    expect(applySiteCode("  ")).toBe(false);
    expect(getSavedWorkplaceCode()).toBe("DEMO01");
  });
});

vi.mock("../../src/worker/EntryScreen", () => ({
  default: function Entry() {
    const loc = useLocation();
    return <p data-testid="entry">{`${loc.pathname}${loc.search}|${getSavedWorkplaceCode()}`}</p>;
  },
}));

import WorkerApp from "../../src/worker/WorkerApp";

describe("WorkerApp이 ?site=를 읽는다", () => {
  it("첫 화면부터 저장된 코드를 쓰고, 주소에서 site를 뺀다(다른 칸은 남김)", async () => {
    saveWorkplaceCode("OLD111");
    saveWorkplaceName("옛 가게");
    render(
      <MemoryRouter initialEntries={["/worker?site=new222&x=1"]}>
        <Routes>
          <Route path="/worker/*" element={<WorkerApp auth={null} onLogin={() => undefined} onLogout={() => undefined} />} />
        </Routes>
      </MemoryRouter>,
    );
    const entry = await screen.findByTestId("entry");
    expect(entry.textContent).toBe("/worker?x=1|NEW222");
    expect(getSavedWorkplaceName()).toBeNull();
  });
});

describe("근로자 화면 파일에 '선생님' 직접 사용 0건", () => {
  it("src/worker/**/*.tsx", () => {
    const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/worker");
    const bad: string[] = [];
    const walk = (dir: string) => {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, e.name);
        if (e.isDirectory()) walk(full);
        else if (e.name.endsWith(".tsx") && fs.readFileSync(full, "utf8").includes("선생님")) bad.push(full);
      }
    };
    walk(root);
    expect(bad).toEqual([]);
  });
});
