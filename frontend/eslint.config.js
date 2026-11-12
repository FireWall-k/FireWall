import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tailwind from 'eslint-plugin-tailwindcss'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// 플러그인은 설정 파일 경로의 디렉터리를 기준으로 tailwindcss 패키지를 찾는데, 상대경로를 주면
// 실행 위치에 따라 "Could not resolve tailwindcss"로 죽는다(실측). 그래서 절대경로로 넘긴다.
const tailwindConfigPath = path.join(path.dirname(fileURLToPath(import.meta.url)), 'tailwind.config.js')

// className을 + 로 이어붙이지 못하게 하는 규칙. 아래 새 폴더 규칙에서도 다시 적는다 — flat config는 같은 규칙을
// 뒤 블록이 통째로 덮어쓰므로(옵션이 합쳐지지 않음) 빠뜨리면 새 폴더에서 이 검사가 사라진다.
const NO_CLASSNAME_PLUS = {
  selector: "JSXAttribute[name.name='className'] BinaryExpression[operator='+']",
  message: 'className은 + 로 이어붙이지 말고 cn(...)(src/cn.ts)을 쓰세요 — 이어붙인 클래스는 tailwind 린트가 검사하지 못합니다.',
}

// src/** 전체에서 막는 Tailwind 기본 팔레트(명세 6.1 R2: blue-700·green-700·emerald·sky·violet·slate·amber 등).
// 색은 tailwind.config.js의 토큰(ink·paper·moss·ok·warn·danger·info·auto·line·worker)만 쓴다.
// (2d 팔레트 잠금) tailwind.config.js가 theme.colors를 덮어써 기본 팔레트를 아예 만들지 않으므로, 기본 팔레트 클래스는
// no-custom-classname에도 걸린다. 이 규칙은 cn(...) 밖 문자열(META 표 등)까지 잡는 두 번째 그물이다.
const DEFAULT_PALETTE =
  'slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose'
const COLOR_UTIL =
  'bg|text|border|border-[xytrbl]|ring|ring-offset|outline|fill|stroke|from|via|to|divide|placeholder|decoration|accent|caret|shadow'
const PALETTE_RE = `(^|[\\s:!])(${COLOR_UTIL})-(${DEFAULT_PALETTE})-[0-9]`
// 10~11px 글자(명세 6.2 R3: 가장 작은 글씨 12px).
const SMALL_TEXT_RE = 'text-\\[1[01]px\\]'

const NEW_FOLDER_RULES = [
  NO_CLASSNAME_PLUS,
  {
    selector: `Literal[value=/${PALETTE_RE}/]`,
    message: 'Tailwind 기본 팔레트 색(slate·blue·green·amber…)은 새 사업주 화면에서 쓰지 않아요 — 사업주 토큰(ink·paper·moss·ok·warn·danger·info·auto)을 쓰세요(명세 6.1).',
  },
  {
    selector: `TemplateElement[value.raw=/${PALETTE_RE}/]`,
    message: 'Tailwind 기본 팔레트 색(slate·blue·green·amber…)은 새 사업주 화면에서 쓰지 않아요 — 사업주 토큰을 쓰세요(명세 6.1).',
  },
  {
    selector: `Literal[value=/${SMALL_TEXT_RE}/]`,
    message: '10~11px 글자는 쓰지 않아요 — 가장 작은 글씨는 text-ui-xs(12px)예요(명세 6.2).',
  },
  {
    selector: `TemplateElement[value.raw=/${SMALL_TEXT_RE}/]`,
    message: '10~11px 글자는 쓰지 않아요 — 가장 작은 글씨는 text-ui-xs(12px)예요(명세 6.2).',
  },
  {
    selector: "CallExpression[callee.name='confirm']",
    message: 'window.confirm 대신 components/ui의 Dialog를 쓰세요(명세 5.0 R11).',
  },
  {
    selector: "CallExpression[callee.object.name='window'][callee.property.name='confirm']",
    message: 'window.confirm 대신 components/ui의 Dialog를 쓰세요(명세 5.0 R11).',
  },
]

export default defineConfig([
  globalIgnores(['dist', 'playwright-report', 'test-results']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
  },
  {
    // tailwind.config.js에 없는 클래스는 Tailwind가 에러 없이 무시한다. 근로자 화면의
    // min-h-touch(80px 터치 영역)·text-worker(큰 글씨)가 정의 없이 쓰여 실제로는 적용되지
    // 않았던 사고(Phase 0.4)가 다시 나지 않도록, 정의되지 않은 클래스를 CI 린트에서 error로 막는다.
    // 다른 tailwindcss 규칙(클래스 순서 등)은 접근성과 무관하고 기존 코드 전체를 흔들므로 켜지 않는다.
    files: ['src/**/*.{ts,tsx}'],
    plugins: { tailwindcss: tailwind },
    settings: {
      tailwindcss: {
        config: tailwindConfigPath,
        // 조건부 클래스는 src/cn.ts의 cn(...)으로 만든다. 문자열 이어붙이기("a " + (c ? "b" : "c"))는
        // 플러그인이 검사하지 못해 미정의 클래스가 숨을 수 있다. cn 인자(문자열·삼항·&&·템플릿)는 모두 검사한다.
        callees: ['cn'],
      },
    },
    rules: {
      'tailwindcss/no-custom-classname': 'error',
      // className을 + 로 이어붙이면 위 규칙이 그 안을 못 본다(검사 구멍). cn(...)이나 템플릿 리터럴을 쓰게 한다.
      'no-restricted-syntax': ['error', NO_CLASSNAME_PLUS],
    },
  },
  {
    // (2d) 팔레트·10~11px·window.confirm 금지를 src/** 전체로 넓혔다(tasks §7 FOUNDATION). 옛 새 직무 화면 예외는 2b-1 병합 때 없앴다.
    files: ['src/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': ['error', ...NEW_FOLDER_RULES],
    },
  },
])
