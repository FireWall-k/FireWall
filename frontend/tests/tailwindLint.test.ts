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

async function ruleIds(code: string): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath: probePath });
  return result.messages.map((m) => m.ruleId ?? `fatal:${m.message}`);
}

const header = 'import { cn } from "./cn";\n';

describe("tailwind 미정의 클래스 린트", () => {
  beforeAll(() => {
    eslint = new ESLint({ cwd: root });
  });

  it("대조군: 정의된 클래스만 쓴 cn(...)은 통과한다", async () => {
    const code = header +
      'export const A = ({ on }: { on: boolean }) => <b className={cn("min-h-touch text-worker", on ? "bg-green-700" : "bg-slate-100", on && "font-bold")} />;\n';
    expect(await ruleIds(code)).toEqual([]);
  });

  it("cn(...)의 삼항 안에 숨은 미정의 클래스도 잡는다", async () => {
    const code = header +
      'export const A = ({ on }: { on: boolean }) => <b className={cn("min-h-touch", on ? "bg-green-700" : "min-h-tuch")} />;\n';
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
