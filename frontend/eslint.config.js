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
      },
    },
    rules: {
      'tailwindcss/no-custom-classname': 'error',
    },
  },
])
