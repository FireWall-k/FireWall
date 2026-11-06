/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          900: "#1C2321",
          700: "#3A4540",
          500: "#647168",
        },
        paper: {
          50: "#FAF8F3",
          100: "#F2EEE3",
          200: "#E6E0D2",
        },
        moss: {
          400: "#7A9471",
          500: "#5C7A52",
          600: "#48613F",
        },
        clay: {
          400: "#D98B5F",
          500: "#C4703E",
          600: "#A35A2E",
        },
        signal: {
          amber: "#E0A030",
          red: "#C24B3F",
        },
        worker: {
          bg: "#FFF8EC",
          card: "#FFFFFF",
          ink: "#1A1A1A",
          accent: "#2C6E49",
          accentDark: "#1E4D33",
        },
      },
      fontFamily: {
        display: ["'Gmarket Sans'", "'Pretendard'", "sans-serif"],
        body: ["'Pretendard'", "sans-serif"],
        worker: ["'Pretendard'", "sans-serif"],
      },
      // 근로자(발달장애인) 화면 전용 크기. WorkerPage가 min-h-touch·text-worker·text-worker-lg를
      // 처음부터 썼지만 여기 정의가 없어 Tailwind가 CSS를 하나도 만들지 않았다 — 버튼은 내용 높이로
      // 쪼그라들고 글씨는 기본 16px로 나왔다(Phase 0.4). 지금은 eslint no-custom-classname과
      // tests/tailwindClasses.test.ts가 같은 사고를 막는다.
      minHeight: {
        // 손 떨림·정밀 동작이 어려운 사용자도 한 번에 누를 수 있는 터치 영역.
        // WCAG 2.5.5(44px)보다 넉넉한 80px — 장갑을 낀 현장 작업 중에도 누르기 쉽게.
        touch: "80px",
      },
      minWidth: {
        // 아이콘만 있는 정사각형 버튼도 같은 터치 영역을 갖도록 짝을 맞춰 둔다.
        touch: "80px",
      },
      fontSize: {
        // 근로자 화면 기본 큰 글씨(버튼·안내 문장). 24px + 넉넉한 줄간격으로 한 글자씩 읽기 쉽게.
        worker: ["1.5rem", { lineHeight: "1.5" }],
        // 지금 할 단계 문장·완료 메시지처럼 가장 먼저 눈에 들어와야 하는 글씨(32px).
        "worker-lg": ["2rem", { lineHeight: "1.35" }],
        "worker-sentence": ["2.75rem", { lineHeight: "1.3", fontWeight: "700" }],
        "worker-button": ["1.5rem", { lineHeight: "1.4", fontWeight: "700" }],
      },
    },
  },
  plugins: [],
}

