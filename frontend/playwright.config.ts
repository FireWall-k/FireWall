import { defineConfig, devices } from "@playwright/test";

// 근로자 화면 접근성 e2e(Phase 0.4). jsdom은 레이아웃·CSS를 계산하지 않아 "버튼이 실제로 80px인가",
// "대비가 충분한가"를 못 본다 — 그래서 진짜 브라우저(Chromium)로 Vite 개발 서버를 띄워 확인한다.
// 백엔드는 띄우지 않는다: API는 각 테스트가 page.route로 목킹하므로 비밀값·DB 없이 CI에서 돈다.
// E2E_WEB_PORT(2a-1) 또는 E2E_PORT(2a-0)로 바꿀 수 있다(다른 작업 폴더의 개발 서버가 4321에 떠 있으면
// 그 화면을 재사용하는 일을 피하려고). 둘 다 받는다(기본 4321).
const PORT = Number(process.env.E2E_WEB_PORT || process.env.E2E_PORT || 4321);

// 존재하지 않는 API 주소를 박아 둔다. 로컬에 실제 백엔드(8000)가 떠 있어도 목킹이 빠진 요청이
// 그쪽으로 새어 나가 우연히 통과하는 일이 없도록 — 목킹 누락은 곧바로 실패로 드러나야 한다.
const E2E_API_BASE = "http://e2e-api.invalid";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    locale: "ko-KR",
  },
  projects: [
    // 근로자는 주로 휴대폰으로 쓴다 — 좁은 화면에서 버튼이 줄어들지 않는지가 핵심이라 모바일 뷰포트로 본다.
    // (기기 프리셋의 브라우저를 Chromium으로 고정해 CI에서 chromium 하나만 설치하면 되게 한다.)
    { name: "mobile-chromium", use: { ...devices["Pixel 7"], browserName: "chromium" } },
  ],
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: { VITE_API_BASE: E2E_API_BASE },
  },
});
