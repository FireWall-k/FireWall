import { describe, expect, it } from "vitest";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { render, screen } from "@testing-library/react";
import { Bell } from "lucide-react";
import { IconButton } from "../../src/components/ui";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

/** src 안의 가상 파일 하나를 실제 tsconfig.app.json 설정으로 타입 검사해 오류 문장들을 돌려준다. */
function typeErrors(code: string): string[] {
  const configPath = path.join(root, "tsconfig.app.json");
  const cfg = ts.readConfigFile(configPath, ts.sys.readFile);
  const parsed = ts.parseJsonConfigFileContent(cfg.config, ts.sys, root);
  const probe = path.join(root, "src", "__iconbutton_probe__.tsx").split(path.sep).join("/");
  const options = { ...parsed.options, noEmit: true, incremental: false, tsBuildInfoFile: undefined };
  const host = ts.createCompilerHost(options);
  const orig = host.getSourceFile.bind(host);
  host.getSourceFile = (name, lang, ...rest) =>
    name.split(path.sep).join("/") === probe ? ts.createSourceFile(name, code, lang) : orig(name, lang, ...rest);
  const origExists = host.fileExists.bind(host);
  host.fileExists = (name) => name.split(path.sep).join("/") === probe || origExists(name);
  const program = ts.createProgram([probe], options, host);
  const sf = program.getSourceFile(probe)!;
  return ts
    .getPreEmitDiagnostics(program, sf)
    .map((d) => ts.flattenDiagnosticMessageText(d.messageText, "\n"));
}

describe("IconButton(아이콘만 있는 버튼)", () => {
  it("aria-label이 버튼 이름이 된다, 배지는 숫자를 그린다", () => {
    render(<IconButton aria-label="도움 요청 2건" icon={<Bell aria-hidden="true" />} badge={2} />);
    const b = screen.getByRole("button", { name: "도움 요청 2건" });
    // 숫자는 CSS 내용으로 그린다(이름에 이미 수가 있어 글자로 두 번 읽히지 않게).
    expect(b.querySelector("[data-badge]")).toHaveAttribute("data-badge", "2");
    expect(b).toHaveTextContent("");
  });

  it("aria-label을 빠뜨리면 타입 오류가 난다(tsc가 막음)", () => {
    const header = 'import IconButton from "./components/ui/IconButton";\n';
    const ok = typeErrors(header + 'export const A = () => <IconButton aria-label="닫기" icon={null} />;\n');
    expect(ok).toEqual([]);
    const bad = typeErrors(header + "export const A = () => <IconButton icon={null} />;\n");
    expect(bad.join("\n")).toMatch(/aria-label/);
  });
}, 60_000);
