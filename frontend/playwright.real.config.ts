import { defineConfig, devices } from "@playwright/test";

// 실제 백엔드에 붙이는 통합 e2e(목킹 없음). 기본 e2e(playwright.config.ts)와 달리 page.route로 API를 꾸미지 않고
// 로컬에 띄운 백엔드·AI 하네스(규칙 모드, 키 없음)를 그대로 쓴다. CI에서는 돌지 않는다 — 직접 띄워서 돌린다:
//   1) AI 하네스: ai_service에서 OPENAI_API_KEY= AAC_LLM_RERANK=off uvicorn main:app --port 8101
//   2) 백엔드: backend에서 AI_BASE_URL=http://127.0.0.1:8101 PUBLIC_BACKEND_URL=http://127.0.0.1:8100
//      CORS_ORIGINS=http://127.0.0.1:5180 DEMO_SEED=0 DATABASE_URL=sqlite:///<빈 파일> uvicorn main:app --port 8100
//   3) 사업주 계정: python manage.py create-employer --login realboss --password-stdin (REAL_EMPLOYER_* 로 바꿀 수 있음)
//   4) npx playwright test -c playwright.real.config.ts
const PORT = Number(process.env.REAL_WEB_PORT ?? 5180);
const REAL_API = process.env.REAL_API_BASE ?? "http://127.0.0.1:8100";

export default defineConfig({
  testDir: "./e2e-real",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    locale: "ko-KR",
  },
  projects: [
    { name: "phone", use: { ...devices["Pixel 7"], browserName: "chromium", viewport: { width: 390, height: 844 } } },
    {
      name: "tablet",
      use: { ...devices["Galaxy Tab S4"], browserName: "chromium", viewport: { width: 768, height: 1024 } },
    },
  ],
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: true,
    timeout: 120_000,
    env: { VITE_API_BASE: REAL_API },
  },
});
