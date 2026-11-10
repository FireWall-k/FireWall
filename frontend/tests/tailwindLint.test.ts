import { beforeAll, describe, expect, it } from "vitest";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { ESLint } from "eslint";

// 미정의 Tailwind 클래스가 린트에 실제로 걸리는지 확인한다(Phase 0.4 보완).
// 예전 WorkerPage는 조건부 클래스를 "a " + (c ? "b" : "c")로 이어붙였는데, eslint-plugin-tailwindcss는
// 그 안을 검사하지 않아 미정의 클래스가 섞여도 린트가 통과했다. 지금은 cn(...)(src/cn.ts) + callees 설정으로
// 인자까지 검사하고, className 안의 + 이어붙이기 자체를 no-restricted-syntax로 막는다.
// 설정이 바뀌어 이 보장이 조용히 사라지지 않도록 실제 eslint.config.js로 코드 조각을 린트해 본다.
// (전역 setup.ts가 window를 건드리므로 환경은 기본 jsdom 그대로 둔다. ESLint는 순수 Node 코드라 무관.)
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const probePath = path.join(root, "src", "__lint_probe__.tsx");

let eslint: ESLint;

async function ruleIds(code: string, filePath = probePath): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath });
  return result.messages.map((m) => m.ruleId ?? `fatal:${m.message}`);
}

const header = 'import { cn } from "./cn";\n';

describe("tailwind 미정의 클래스 린트", () => {
  beforeAll(() => {
    eslint = new ESLint({ cwd: root });
  });

  it("대조군: 정의된 클래스만 쓴 cn(...)은 통과한다", async () => {
    const code = header +
      'export const A = ({ on }: { on: boolean }) => <b className={cn("min-h-touch text-worker", on ? "bg-moss-600" : "bg-paper-100", on && "font-bold")} />;\n';
    expect(await ruleIds(code)).toEqual([]);
  });

  it("cn(...)의 삼항 안에 숨은 미정의 클래스도 잡는다", async () => {
    const code = header +
      'export const A = ({ on }: { on: boolean }) => <b className={cn("min-h-touch", on ? "bg-moss-600" : "min-h-tuch")} />;\n';
    expect(await ruleIds(code)).toContain("tailwindcss/no-custom-classname");
  });

  it("cn(...)의 && 뒤에 숨은 미정의 클래스도 잡는다", async () => {
    const code = header +
      'export const A = ({ on }: { on: boolean }) => <b className={cn("min-h-touch", on && "text-worker-xl")} />;\n';
    expect(await ruleIds(code)).toContain("tailwindcss/no-custom-classname");
  });

  it("템플릿 리터럴의 고정 부분도 잡는다", async () => {
    const code = 'export const A = ({ x }: { x: string }) => <b className={`min-h-touchh ${x}`} />;\n';
    expect(await ruleIds(code)).toContain("tailwindcss/no-custom-classname");
  });

  it("className을 + 로 이어붙이면 실패한다(검사 구멍을 막는다)", async () => {
    const code = 'export const A = ({ on }: { on: boolean }) => <b className={"min-h-touch " + (on ? "a" : "b")} />;\n';
    expect(await ruleIds(code)).toContain("no-restricted-syntax");
  });
}, 60_000);

// 기본 팔레트·10~11px 글자·window.confirm 금지. 2a-1은 새 폴더에만 걸었고, 2d부터 src/** 전체에 건다.
// 예외는 2b-1이 지우는 옛 새 직무 화면 두 파일(eslint.config.js LEGACY_UNTIL_2B1)뿐이다.
const uiProbe = path.join(root, "src", "components", "ui", "__lint_probe__.tsx");
const managerProbe = path.join(root, "src", "manager", "__lint_probe__.tsx");
const loginProbe = path.join(root, "src", "pages", "LoginPage.tsx");
const oldProbe = path.join(root, "src", "pages", "__old_probe__.tsx");
const uiHeader = 'import { cn } from "../../cn";\n';
const mHeader = 'import { cn } from "../cn";\n';

describe("새 사업주 폴더 lint(팔레트·작은 글자·confirm)", () => {
  beforeAll(() => {
    eslint = new ESLint({ cwd: root });
  });

  it("대조군: 사업주 토큰만 쓴 부품은 통과한다", async () => {
    const code =
      uiHeader +
      'export const A = ({ on }: { on: boolean }) => <b className={cn("bg-moss-600 text-ui-xs text-white", on && "bg-danger-50 text-danger-700")} />;\n';
    expect(await ruleIds(code, uiProbe)).toEqual([]);
  });

  it.each([
    ["bg-blue-700", uiProbe, uiHeader],
    ["text-slate-500", managerProbe, mHeader],
    ["hover:bg-green-700", managerProbe, mHeader],
    ["border-amber-300", uiProbe, uiHeader],
    ["ring-emerald-600", uiProbe, uiHeader],
    ["text-sky-700", loginProbe, mHeader],
    ["bg-violet-100", managerProbe, mHeader],
  ])("기본 팔레트 %s는 실패한다", async (cls, file, header) => {
    const code = header + `export const A = ({ on }: { on: boolean }) => <b className={cn("p-2", on && "${cls}")} />;\n`;
    expect(await ruleIds(code, file)).toContain("no-restricted-syntax");
  });

  it("템플릿 리터럴 안의 기본 팔레트도 잡는다", async () => {
    const code = "export const A = ({ x }: { x: string }) => <b className={`p-2 bg-slate-100 ${x}`} />;\n";
    expect(await ruleIds(code, managerProbe)).toContain("no-restricted-syntax");
  });

  it("text-[10px]·text-[11px]은 실패한다", async () => {
    for (const cls of ["text-[10px]", "text-[11px]"]) {
      const code = mHeader + `export const A = () => <b className={cn("${cls}")} />;\n`;
      expect(await ruleIds(code, managerProbe), cls).toContain("no-restricted-syntax");
    }
  });

  it("confirm(·window.confirm(은 실패한다", async () => {
    for (const call of ["confirm('지울까요?')", "window.confirm('지울까요?')"]) {
      const code = `export function f() { return ${call}; }\n`;
      expect(await ruleIds(code, managerProbe), call).toContain("no-restricted-syntax");
    }
  });

  it("className + 이어붙이기 금지는 새 폴더에서도 그대로다", async () => {
    const code = 'export const A = ({ on }: { on: boolean }) => <b className={"p-2 " + (on ? "a" : "b")} />;\n';
    expect(await ruleIds(code, managerProbe)).toContain("no-restricted-syntax");
  });

  it("(2d) src/** 전체에 건다: 옛 화면 폴더·근로자 폴더도 팔레트·confirm이 실패한다", async () => {
    const code =
      mHeader + 'export const A = () => <b className={cn("bg-blue-700 text-slate-500")} onClick={() => window.confirm("x")} />;\n';
    const ids = await ruleIds(code, oldProbe);
    expect(ids).toContain("no-restricted-syntax");
    const workerProbe = path.join(root, "src", "worker", "__lint_probe__.tsx");
    expect(await ruleIds(code, workerProbe)).toContain("no-restricted-syntax");
  });

  it("(2d 팔레트 잠금) 기본 팔레트 클래스는 만들어지지 않아 no-custom-classname에도 걸린다", async () => {
    const code = mHeader + 'export const A = () => <b className={cn("p-2 bg-blue-700")} />;\n';
    expect(await ruleIds(code, managerProbe)).toContain("tailwindcss/no-custom-classname");
  });

  it("(2d) 남겨 두는 색 white·black·transparent·current·inherit는 통과한다", async () => {
    const code =
      mHeader +
      'export const A = () => <b className={cn("bg-white text-black border-transparent fill-current text-inherit hc:text-black hc:bg-white")} />;\n';
    expect(await ruleIds(code, path.join(root, "src", "worker", "__lint_probe__.tsx"))).toEqual([]);
  });

}, 60_000);

// (2d 완료 기준 4) 실제 src/** 파일 전체에서 기본 팔레트·10~11px·window.confirm 0건(옛 새 직무 화면 2파일은 2b-1이 지움).
describe("src/** 전체 검사(완료 기준 4)", () => {
  it("기본 팔레트·text-[10px|11px]·confirm( 이 0건", async () => {
    const fs = await import("node:fs");
    const LEGACY = new Set(["src/pages/ManagerPage.tsx", "src/components/SplitPreviewList.tsx"]);
    const PALETTE =
      /(^|[\s:!"'`])(bg|text|border|border-[xytrbl]|ring|ring-offset|outline|fill|stroke|from|via|to|divide|placeholder|decoration|accent|caret|shadow)-(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-[0-9]/;
    const bad: string[] = [];
    const walk = (dir: string) => {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, e.name);
        if (e.isDirectory()) walk(full);
        else if (/\.(ts|tsx)$/.test(e.name)) {
          const rel = path.relative(root, full).split(path.sep).join("/");
          if (LEGACY.has(rel)) continue;
          const text = fs.readFileSync(full, "utf8");
          text.split("\n").forEach((line, i) => {
            if (PALETTE.test(line) || /text-\[1[01]px\]/.test(line) || /(^|[^.\w])confirm\(|window\.confirm\(/.test(line)) {
              bad.push(`${rel}:${i + 1}: ${line.trim()}`);
            }
          });
        }
      }
    };
    walk(path.join(root, "src"));
    expect(bad).toEqual([]);
  });
});
