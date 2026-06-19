/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // 접근성 토큰: 근로자 UI는 큰 터치 영역과 큰 글자가 기본값.
      fontSize: {
        worker: ["1.5rem", { lineHeight: "2rem" }],
        "worker-lg": ["2rem", { lineHeight: "2.5rem" }],
      },
      minHeight: { touch: "80px" },
      minWidth: { touch: "80px" },
    },
  },
  plugins: [],
};
