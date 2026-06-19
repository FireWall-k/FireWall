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
        display: ["'Fraunces'", "serif"],
        body: ["'Inter'", "sans-serif"],
        worker: ["'Pretendard'", "'Inter'", "sans-serif"],
      },
      fontSize: {
        "worker-sentence": ["2.75rem", { lineHeight: "1.3", fontWeight: "700" }],
        "worker-button": ["1.5rem", { lineHeight: "1.4", fontWeight: "700" }],
      },
    },
  },
  plugins: [],
}

