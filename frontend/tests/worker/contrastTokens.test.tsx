import { beforeAll, describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import postcss from "postcss";
import tailwindcss from "tailwindcss";
import { render } from "@testing-library/react";
import tailwindConfig from "../../tailwind.config.js";
import { ProgressDots } from "../../src/worker/ProgressDots";

// 3b-1 고대비·근로자 디자인 토큰 대비(명세 6.1·8.1). axe는 고대비 모드의 테두리 두께·초점 고리·그림 둘레·진행 점 모양처럼
// '글자가 아닌 것'을 보지 못한다 — 실제 토큰 값(tailwind.config.js)·index.css·Tailwind 산출 CSS·화면 코드로 직접 잰다.
// 값을 바꾸다 목표를 놓치면 여기서 실패한다.

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const read = (p: string) => fs.readFileSync(path.join(root, p), "utf8");
const worker = (tailwindConfig.theme!.colors as Record<string, Record<string, string> | string>).worker as Record<string, string>;
const colors = tailwindConfig.theme!.colors as Record<string, string>;
const BLACK = colors.black;
const WHITE = colors.white;

function luminance(h: string): number {
  const n = h.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}
function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}
const round2 = (v: number) => Math.round(v * 100) / 100;

let css = "";
beforeAll(async () => {
  const config = {
    ...tailwindConfig,
    content: (tailwindConfig.content as string[]).map((p) => path.join(root, p).split(path.sep).join("/")),
  };
  const out = await postcss([tailwindcss(config)]).process("@tailwind utilities;", { from: undefined });
  css = out.css.replace(/\s+/g, "");
}, 30_000);

describe("고대비 글자·바탕", () => {
  it("검정 글자 / 흰 바탕 21:1", () => {
    expect(BLACK).toBe("#000000");
    expect(WHITE).toBe("#FFFFFF");
    expect(round2(contrast(BLACK, WHITE))).toBe(21);
  });

  it("근로자 화면 뿌리는 고대비에서 흰 바탕·검정 글자로 바뀐다", () => {
    for (const f of ["src/worker/WorkerScreen.tsx", "src/worker/StepPlayer.tsx", "src/worker/ui/StatusScreen.tsx", "src/worker/ui/ConfirmScreen.tsx"]) {
      expect(read(f), f).toContain("hc:bg-white hc:text-black");
    }
    expect(css).toContain('[data-contrast="high"].hc\\:bg-white{');
    expect(css).toContain('[data-contrast="high"].hc\\:text-black{');
  });
});

describe("주 버튼", () => {
  it("고대비 주 버튼은 primary-pressed #1E4D33, 흰 글씨 9.70:1(기본 primary 7.20:1)", () => {
    expect(worker["primary-pressed"]).toBe("#1E4D33");
    expect(round2(contrast(WHITE, worker["primary-pressed"]))).toBeGreaterThanOrEqual(9.7);
    expect(contrast(WHITE, worker.primary)).toBeGreaterThanOrEqual(7);
    const btn = read("src/worker/ui/WorkerButton.tsx");
    expect(btn).toMatch(/PrimaryAction[\s\S]*text-white[\s\S]*hc:bg-worker-primary-pressed/);
  });

  it("고대비 버튼 테두리 3px 검정: 공통 버튼·[듣기]·직무 카드, [도와주세요]는 3px 이상", () => {
    expect(css).toContain('[data-contrast="high"].hc\\:border-\\[3px\\]{border-width:3px');
    expect(css).toMatch(/\[data-contrast="high"\]\.hc\\:border-black\{[^}]*border-color:rgb\(000\//);
    expect(read("src/worker/ui/WorkerButton.tsx")).toContain('"hc:border-[3px] hc:border-black"');
    expect(read("src/worker/StepPlayer.tsx")).toContain('"hc:border-[3px] hc:border-black hc:bg-white hc:text-black"');
    expect(read("src/worker/JobCard.tsx")).toContain('!highlight && "hc:border-[3px]"');
    const help = read("src/worker/Help.tsx");
    expect(help).toMatch(/pressed \? "border-4 border-worker-help-ink" : "border-\[3px\] border-worker-help-line"/);
    expect(help).toContain('"hc:border-black hc:bg-white hc:text-black"');
    // 테두리가 바탕과 구분된다(흰 바탕 위 검정 21:1). 짙은 초록 버튼 칠과는 2.16:1뿐이라 테두리는 바탕과의 경계 몫이다.
    expect(round2(contrast(BLACK, WHITE))).toBe(21);
  });
});

describe("초점 고리", () => {
  const indexCss = read("src/index.css").replace(/\/\*[\s\S]*?\*\//g, "");
  it("기본 3px #C4703E + 바깥 간격 3px, 바탕(#FFF8EC)·흰색 위 3:1 이상", () => {
    expect(indexCss).toMatch(/:focus-visible\s*\{\s*outline:\s*3px solid #C4703E;\s*outline-offset:\s*3px;/);
    expect(contrast("#C4703E", worker.bg)).toBeGreaterThanOrEqual(3);
    expect(contrast("#C4703E", worker.card)).toBeGreaterThanOrEqual(3);
  });

  it("고대비는 4px 검정, 간격(outline-offset 3px)은 그대로라 짙은 초록 버튼 옆에서도 흰 틈 + 검정 고리로 보인다", () => {
    const hc = indexCss.match(/\[data-contrast="high"\]\s*:focus-visible\s*\{([^}]*)\}/);
    expect(hc).not.toBeNull();
    expect(hc![1]).toMatch(/outline:\s*4px solid #000000/);
    // 고대비 규칙이 간격을 0으로 덮지 않는다(outline 줄임말은 outline-offset을 바꾸지 않는다).
    expect(hc![1]).not.toMatch(/outline-offset/);
    // 검정 고리는 짙은 초록 버튼(#1E4D33)과 붙으면 2.16:1이라 안 보인다 — 그래서 사이에 흰 바탕 틈이 있어야 한다.
    expect(contrast(BLACK, worker["primary-pressed"])).toBeLessThan(3);
    expect(contrast(BLACK, WHITE)).toBeGreaterThanOrEqual(3);
  });
});

describe("그림 둘레", () => {
  it("그림 상자 둘레 2px, 고대비에서 검정", () => {
    const src = read("src/worker/StepPlayer.tsx");
    expect(src).toContain("rounded-worker-pic border-2 border-worker-line-soft bg-white hc:border-black");
    expect(css).toMatch(/\.border-2\{border-width:2px/);
  });
});

describe("조심 띠·도움 띠·기록 보냄 띠(글자 7:1, 테두리 3:1)", () => {
  it("조심 띠: caution-ink / caution 7:1 이상, 고대비는 흰 바탕 검정 글자 + 아래 2px 검정", () => {
    expect(contrast(worker["caution-ink"], worker.caution)).toBeGreaterThanOrEqual(7);
    expect(read("src/worker/StepPlayer.tsx")).toContain("text-worker-caution-ink hc:border-b-2 hc:border-black hc:bg-white hc:text-black");
  });

  it("도움 띠: help-ink / help 7:1 이상, 보조 글씨 ink-soft / help 7:1 이상, 테두리 help-line은 띠·바탕 위 3:1 이상", () => {
    expect(contrast(worker["help-ink"], worker.help)).toBeGreaterThanOrEqual(7);
    expect(contrast(worker["ink-soft"], worker.help)).toBeGreaterThanOrEqual(7);
    expect(contrast(worker["help-line"], worker.help)).toBeGreaterThanOrEqual(3);
    expect(contrast(worker["help-line"], worker.bg)).toBeGreaterThanOrEqual(3);
  });

  it("끊김 띠 caution-ink / caution, 기록 보냄 띠 primary-pressed / primary-tint 7:1 이상", () => {
    expect(contrast(worker["caution-ink"], worker.caution)).toBeGreaterThanOrEqual(7);
    expect(contrast(worker["primary-pressed"], worker["primary-tint"])).toBeGreaterThanOrEqual(7);
    // 3b-1에서 고친 것: 예전 글자색 primary는 tint 위 6.26:1로 7:1에 못 미쳤다.
    expect(contrast(worker.primary, worker["primary-tint"])).toBeLessThan(7);
    expect(read("src/worker/WorkerScreen.tsx")).toContain('"border-worker-primary bg-worker-primary-tint text-worker-primary-pressed"');
  });

  it("모든 띠는 고대비에서 흰 바탕·검정 글자·검정 테두리", () => {
    expect(read("src/worker/WorkerScreen.tsx")).toMatch(/tone === "synced"[^\n]*\n\s*"hc:border-black hc:bg-white hc:text-black"/);
  });
});

describe("진행 점: 끝냄·지금·남음은 색 말고 모양으로도 다르다", () => {
  it("점: 끝냄 = 체크 그림, 지금 = 큰 점 + 안쪽 흰 점 + 고리, 남음 = 빈 원(테두리만)", () => {
    const { container } = render(<ProgressDots total={3} current={1} done={(i) => i === 0} />);
    const [done, now, todo] = Array.from(container.querySelectorAll("[data-state]"));
    expect(done.getAttribute("data-state")).toBe("done");
    expect(done.querySelector("svg")).not.toBeNull();
    expect(now.getAttribute("data-state")).toBe("current");
    expect(now.className).toContain("size-7");
    expect(now.className).toContain("ring-2");
    expect(now.querySelector("svg")).toBeNull();
    expect(now.querySelector("span.rounded-full")).not.toBeNull();
    expect(todo.getAttribute("data-state")).toBe("todo");
    expect(todo.children).toHaveLength(0);
    expect(todo.className).toContain("border-2");
    expect(todo.className).toContain("size-5");
    // 셋의 모양 표시(안의 것·크기)가 모두 다르다.
    const sig = (el: Element) => `${el.querySelector("svg") ? "check" : el.children.length ? "dot" : "empty"}|${/size-(\d)/.exec(el.className)?.[1]}`;
    expect(new Set([done, now, todo].map(sig)).size).toBe(3);
    // 남은 점 테두리(line)는 바탕·흰색 위 3:1 이상(명세 8.1).
    expect(contrast(worker.line, worker.bg)).toBeGreaterThanOrEqual(3);
    expect(contrast(worker.line, worker.card)).toBeGreaterThanOrEqual(3);
  });

  it("칸 막대(12개 넘음·위 띠 안): 지금 칸은 높이와 3px 테두리, 끝냄은 칠, 남음은 2px 테두리만", () => {
    const { container } = render(<ProgressDots total={3} current={1} done={(i) => i === 0} fit />);
    const [done, now, todo] = Array.from(container.querySelectorAll("[data-state]"));
    expect(done.className).toMatch(/\bh-3\b/);
    expect(done.className).toContain("bg-worker-primary");
    expect(done.className).not.toContain("border");
    expect(now.className).toMatch(/\bh-5\b/);
    expect(now.className).toContain("border-[3px]");
    expect(todo.className).toMatch(/\bh-3\b/);
    expect(todo.className).toContain("border-2");
    expect(todo.className).toContain("bg-worker-card");
  });
});

describe("근로자 버튼 80px 이상(명세 4.0)", () => {
  it("공통 버튼은 min-h-touch(80) / 주 버튼 min-h-touch-lg(88), [도와주세요]도 80", () => {
    expect(css).toMatch(/\.min-h-touch\{min-height:80px/);
    expect(css).toMatch(/\.min-h-touch-lg\{min-height:88px/);
    const btn = read("src/worker/ui/WorkerButton.tsx");
    expect(btn).toContain('"min-h-touch-lg bg-worker-primary');
    expect(btn).toContain('"min-h-touch border-2 border-worker-line');
    expect(read("src/worker/Help.tsx")).toContain("inline-flex min-h-touch");
  });
});
