import { beforeAll, describe, it, expect } from "vitest";
import path from "node:path";
import { fileURLToPath } from "node:url";
import postcss from "postcss";
import tailwindcss from "tailwindcss";
import tailwindConfig from "../tailwind.config.js";

// 근로자 화면의 80px 터치 영역·큰 글씨 클래스(min-h-touch, text-worker 등)는 예전에 tailwind.config.js에
// 정의가 없어서 Tailwind가 조용히 무시했다 — 화면에는 클래스 이름이 붙어 있는데 CSS 규칙이 하나도
// 생성되지 않아 버튼이 손가락보다 작게, 글씨가 기본 크기로 나왔다(Phase 0.4). jsdom 렌더 테스트는
// 클래스 이름만 보므로 이 결함을 못 잡는다. 그래서 실제 빌드와 같은 설정으로 Tailwind를 postcss로
// 돌려 산출 CSS에 규칙이 "실제로" 생기는지 단언한다.
// (전역 setup.ts가 window를 건드리므로 환경은 기본 jsdom 그대로 둔다. postcss·tailwind는 순수 Node 코드라 무관.)
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

async function buildCss(): Promise<string> {
  const config = {
    ...tailwindConfig,
    // content 경로는 cwd 기준 상대경로라 테스트 실행 위치와 무관하게 frontend/ 기준으로 고정한다.
    content: (tailwindConfig.content as string[]).map((p) => path.join(root, p).split(path.sep).join("/")),
  };
  const result = await postcss([tailwindcss(config)]).process(
    "@tailwind base;\n@tailwind components;\n@tailwind utilities;",
    { from: undefined },
  );
  // 공백·줄바꿈을 걷어내 "선택자{속성:값}" 형태로 단언하기 쉽게 만든다.
  return result.css.replace(/\s+/g, "");
}

describe("근로자 화면 접근성 Tailwind 클래스가 실제 CSS로 생성된다", () => {
  let css = "";
  beforeAll(async () => {
    css = await buildCss();
  }, 30_000);

  it("대조군: 정의된 커스텀 색상 클래스는 생성된다(content 스캔이 실제로 동작하는지 확인)", () => {
    // 이게 실패하면 아래 단언의 실패 원인이 설정 누락이 아니라 content 경로 문제다.
    expect(css).toContain(".bg-worker-bg{");
  });

  it("min-h-touch → min-height: 80px (터치 타깃)", () => {
    expect(css).toMatch(/\.min-h-touch\{min-height:80px;?\}/);
  });

  it("text-worker → 큰 글씨 + 줄간격", () => {
    expect(css).toMatch(/\.text-worker\{font-size:[^;}]+;line-height:[^}]+\}/);
  });

  it("text-worker-lg → 더 큰 글씨 + 줄간격", () => {
    expect(css).toMatch(/\.text-worker-lg\{font-size:[^;}]+;line-height:[^}]+\}/);
  });

  // 근로자 단계 화면 배치(2026-11 UI 진단). 아래 규칙이 빠지면 화면은 그대로 그려지지만 배치가 조용히 무너진다.
  it("wide 변형(가로로 넓은 화면) → 그림 왼쪽·버튼 오른쪽 격자", () => {
    expect(css).toContain("@media(orientation:landscape)and(min-width:768px){");
    expect(css).toContain(".wide\\:grid{display:grid");
  });

  it("wide 변형을 더해도 max-sm: 변형이 그대로 생성된다(머리글 눈썹 글씨 숨김)", () => {
    // theme.screens에 raw 값을 넣으면 Tailwind가 max-* 변형을 만들지 않는다 — 그래서 wide는 플러그인 변형이다.
    expect(css).toContain(".max-sm\\:hidden{display:none");
  });

  // 1차 근로자 토큰(명세 6.1~6.3). 부품(worker/ui, ui/icons)이 쓰는 이름이 실제 CSS로 생기는지.
  it("근로자 색 토큰: primary #1F6340, ink-soft, line(명세 6.1)", () => {
    expect(css).toMatch(/\.bg-worker-primary\{[^}]*background-color:rgb\(319964\/var/);
    expect(css).toMatch(/\.text-worker-ink-soft\{[^}]*color:rgb\(746454\/var/);
    expect(css).toMatch(/\.border-worker-line\{[^}]*border-color:rgb\(14012399\/var/);
  });

  it("사업주 ink-500은 #5B675F(대비 4.5:1 이상)", () => {
    expect(css).toMatch(/\.text-ink-500\{[^}]*color:rgb\(9110395\//);
  });

  it("근로자 크기 토큰: min-h-touch-lg 88px, text-worker-title 28px 굵게, text-worker-caption 20px, rounded-worker-btn 16px", () => {
    expect(css).toMatch(/\.min-h-touch-lg\{min-height:88px;?\}/);
    expect(css).toMatch(/\.text-worker-title\{font-size:1\.75rem;line-height:1\.35;font-weight:700;?\}/);
    expect(css).toMatch(/\.text-worker-caption\{font-size:1\.25rem;line-height:1\.5;font-weight:500;?\}/);
    expect(css).toMatch(/\.rounded-worker-btn\{border-radius:16px;?\}/);
  });

  it("small·hc 변형과 움직임 줄이기 변형이 생성된다", () => {
    expect(css).toContain("@media(max-width:360px),(max-height:620px){");
    expect(css).toContain('[data-contrast="high"].hc\\:border-black');
    expect(css).toContain("@media(prefers-reduced-motion:reduce){.motion-reduce\\:animate-none{animation:none");
  });

  it("그림 바닥 min(10rem, 20dvh)·맞추기 3단계 바닥 min(8rem, 15dvh)와 아주 좁은 칸에서만 버튼을 쌓는 컨테이너 쿼리", () => {
    expect(css).toContain("min-height:min(10rem,20dvh)");
    expect(css).toContain("min-height:min(8rem,15dvh)");
    expect(css).toContain("@container(min-width:16rem){");
  });
});
