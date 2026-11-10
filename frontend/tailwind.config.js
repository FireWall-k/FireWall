/** @type {import('tailwindcss').Config} */
const FALLBACK_FONTS = ["'Apple SD Gothic Neo'", "'Noto Sans KR'", "'Malgun Gothic'", "sans-serif"];

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    // (2d 팔레트 잠금, contract §6.3) theme.colors를 통째로 덮어써 Tailwind 기본 팔레트(slate·blue·green·amber…)를
    // 만들지 않는다. 그래서 기본 팔레트 클래스는 eslint no-custom-classname에도 걸린다. white·black·transparent·current·
    // inherit는 남긴다(근로자 hc:text-black·hc:bg-white, 사업주 text-white 등).
    colors: {
      white: "#FFFFFF",
      black: "#000000",
      transparent: "transparent",
      current: "currentColor",
      inherit: "inherit",
      ink: {
        900: "#1C2321",
        700: "#3A4540",
        // #647168 → #5B675F: paper-100 위에서 4.5:1을 못 넘던 값(명세 6.1). paper-50 위 5.57:1.
        500: "#5B675F",
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
        // 눌림·호버(흰 글씨 8.70:1).
        700: "#3B5134",
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
      // 입력칸 테두리(흰색 위 4.1:1).
      line: {
        strong: "#8C7B63",
      },
      // 사업주 상태색(명세 6.1). 50은 바탕, 700은 글씨.
      ok: { 50: "#EAF4EC", 700: "#2F6B3A" },
      warn: { 50: "#FFF4DB", 700: "#8A5300", line: "#B45309" },
      // 800: 위험 버튼 눌림·호버(흰 글씨 8.6:1).
      danger: { 50: "#FDECEA", 700: "#B3261E", 800: "#8F1E18" },
      // '✦ 자동'(아직 확인하지 않은 자동 결과)에만 쓴다(창업자 결정 2).
      auto: { 50: "#F3F0FF", 700: "#5B4BB7" },
      info: { 700: "#1E5FA8" },
      // 근로자 화면 토큰(명세 6.1). 목표: 글자 7:1 이상, 테두리·아이콘 3:1 이상.
      // 뜻을 가진 색은 셋뿐: 초록(primary)=하기, 주황(help·caution)=도움·조심, 파랑(sound)=듣기. 빨강은 쓰지 않는다.
      worker: {
        bg: "#FFF8EC",
        card: "#FFFFFF",
        ink: "#1A1A1A",
        "ink-soft": "#4A4036",
        line: "#8C7B63",
        "line-soft": "#E9DFCF",
        primary: "#1F6340",
        "primary-pressed": "#1E4D33",
        "primary-tint": "#E6F2EA",
        help: "#FFE3B8",
        "help-ink": "#6B3300",
        "help-line": "#B45309",
        sound: "#E3EEFB",
        "sound-ink": "#0B3D91",
        caution: "#FFE9DC",
        "caution-ink": "#7A2E0E",
        night: "#33302B",
        focus: "#C4703E",
        // 임시 별칭: 옛 WorkerPage가 쓰는 동안만 둔다(통합 때 삭제). 예전 #2C6E49는 흰 글씨 6.12:1로
        // 7:1에 못 미쳐 값부터 primary로 바꿨다.
        accent: "#1F6340",
        accentDark: "#1E4D33",
      },
    },
    extend: {
      // 기본 팔레트를 뺐으므로 테두리 기본색(preflight·divide)은 예전 값(gray-200)을 직접 적는다. 빼면 currentColor로
      // 바뀌어 색을 적지 않은 테두리가 진하게 나온다(근로자 기준 이미지가 달라짐).
      borderColor: { DEFAULT: "#e5e7eb" },
      fontFamily: {
        display: ["'Gmarket Sans'", "'Pretendard'", ...FALLBACK_FONTS],
        body: ["'Pretendard'", ...FALLBACK_FONTS],
        worker: ["'Pretendard'", ...FALLBACK_FONTS],
      },
      // 근로자(발달장애인) 화면 전용 크기. WorkerPage가 min-h-touch·text-worker·text-worker-lg를
      // 처음부터 썼지만 여기 정의가 없어 Tailwind가 CSS를 하나도 만들지 않았다 — 버튼은 내용 높이로
      // 쪼그라들고 글씨는 기본 16px로 나왔다(Phase 0.4). 지금은 eslint no-custom-classname과
      // tests/tailwindClasses.test.ts가 같은 사고를 막는다.
      minHeight: {
        // 손 떨림·정밀 동작이 어려운 사용자도 한 번에 누를 수 있는 터치 영역.
        // WCAG 2.5.5(44px)보다 넉넉한 80px — 장갑을 낀 현장 작업 중에도 누르기 쉽게.
        touch: "80px",
        // 주 행동([다 했어요]·[시작하기]) 88px.
        "touch-lg": "88px",
        // 작은 기기 위 띠(버튼 없는 띠만 이 높이까지 줄어든다).
        "worker-top-sm": "72px",
        // 사업주 화면 높이(명세 6.3, R4). 컨트롤 36(pointer:coarse에서 44), 표 행 56, 목록 행 88, 상단 바 56.
        control: "36px",
        "control-coarse": "44px",
        "table-row": "56px",
        "list-row": "88px",
        topbar: "56px",
      },
      minWidth: {
        // 아이콘만 있는 정사각형 버튼도 같은 터치 영역을 갖도록 짝을 맞춰 둔다.
        touch: "80px",
        control: "36px",
        "control-coarse": "44px",
      },
      // 사업주 틀 폭(명세 3.3·5.0·5.6): 사이드바 240/72, 서랍(Sheet) 480, 목록·홈 본문 최대 1200, 로그인 폼 400.
      width: {
        sidebar: "240px",
        rail: "72px",
        sheet: "480px",
      },
      maxWidth: {
        sheet: "480px",
        page: "1200px",
        form: "400px",
      },
      spacing: {
        sidebar: "240px",
        rail: "72px",
        control: "36px",
        "control-coarse": "44px",
        topbar: "56px",
        tabbar: "64px",
      },
      height: {
        // 근로자 화면 위 띠(휴대폰 80 / 작은 기기 72 / 태블릿 96)와 아래 막대(112 / 작은 기기 104, 안전영역은 따로).
        "worker-top": "80px",
        "worker-top-sm": "72px",
        "worker-top-tab": "96px",
        "worker-bottom": "112px",
        "worker-bottom-sm": "104px",
        "table-row": "56px",
        // 사업주 상단 바·컨트롤·아래 탭바·로그인 390 위 띠(명세 5.1).
        topbar: "56px",
        control: "36px",
        "control-coarse": "44px",
        tabbar: "64px",
        "login-band": "120px",
      },
      fontSize: {
        // 근로자 화면 가장 작은 글씨(상태 글, 보조 버튼 글자) 20px.
        "worker-caption": ["1.25rem", { lineHeight: "1.5", fontWeight: "500" }],
        // 근로자 화면 기본 큰 글씨(버튼·안내 문장). 24px + 넉넉한 줄간격으로 한 글자씩 읽기 쉽게.
        worker: ["1.5rem", { lineHeight: "1.5" }],
        // 직무 카드 이름, [다 했어요] 28px 굵게.
        "worker-title": ["1.75rem", { lineHeight: "1.35", fontWeight: "700" }],
        // 지금 할 단계 문장·완료 메시지처럼 가장 먼저 눈에 들어와야 하는 글씨(32px).
        "worker-lg": ["2rem", { lineHeight: "1.35" }],
        "worker-sentence": ["2.75rem", { lineHeight: "1.3", fontWeight: "700" }],
        "worker-button": ["1.5rem", { lineHeight: "1.4", fontWeight: "700" }],
        // 사업주 글자(명세 6.2, R3). 기본 text-xs·sm·lg 같은 이름을 덮으면 옛 화면과 근로자 화면 글자 크기가
        // 함께 바뀌므로 ui- 이름을 따로 둔다. 새 폴더(components/ui·manager·LoginPage)는 이 이름만 쓴다.
        // 10~11px는 만들지 않는다(가장 작은 글씨 12px).
        "ui-xs": ["0.75rem", { lineHeight: "1.5" }],
        "ui-sm": ["0.8125rem", { lineHeight: "1.5" }],
        "ui-base": ["0.875rem", { lineHeight: "1.55" }],
        "ui-md": ["1rem", { lineHeight: "1.5" }],
        "ui-lg": ["1.25rem", { lineHeight: "1.4" }],
        "ui-xl": ["1.5rem", { lineHeight: "1.3", letterSpacing: "-0.01em", fontWeight: "700" }],
        "ui-kpi": ["2rem", { lineHeight: "1.2" }],
        // 로그인 왼쪽 패널 로고(Gmarket Sans 28, 명세 5.1).
        "ui-logo": ["1.75rem", { lineHeight: "1.2" }],
      },
      borderRadius: {
        "worker-btn": "16px",
        "worker-card": "20px",
        "worker-pic": "24px",
        // 사업주(명세 6.3): 입력·버튼 6, 카드 10, Dialog·Sheet 14. 배지는 rounded-full.
        control: "6px",
        card: "10px",
        overlay: "14px",
      },
      boxShadow: {
        // 근로자 화면에서 그림자는 카드에만(명세 6.3).
        "worker-card": "0 2px 0 rgba(26,26,26,.06)",
        // 사업주 그림자 3단계(명세 6.3).
        "ui-sm": "0 1px 2px rgba(28,35,33,.06)",
        "ui-md": "0 4px 12px rgba(28,35,33,.08)",
        overlay: "0 12px 32px rgba(28,35,33,.16)",
      },
      // 사업주 움직임(명세 6.6, R6): 호버·토스트 150ms, Sheet 200ms. 움직임 줄이기는 index.css가 0ms로 덮는다.
      transitionDuration: {
        hover: "150ms",
        toast: "150ms",
        sheet: "200ms",
      },
      keyframes: {
        // 단계 넘김: 오른쪽 24px에서 들어오며 나타난다(명세 6.6).
        "step-in": {
          from: { transform: "translateX(24px)", opacity: "0" },
          to: { transform: "translateX(0)", opacity: "1" },
        },
        // '잘했어요' 체크 표시.
        check: {
          "0%": { transform: "scale(0.6)", opacity: "0" },
          "60%": { transform: "scale(1.08)", opacity: "1" },
          "100%": { transform: "scale(1)", opacity: "1" },
        },
        // 사업주: Sheet는 오른쪽에서 200ms, 토스트·Dialog·메뉴는 150ms로 나타난다(명세 6.6).
        "sheet-in": {
          from: { transform: "translateX(24px)", opacity: "0" },
          to: { transform: "translateX(0)", opacity: "1" },
        },
        "pop-in": {
          from: { transform: "translateY(4px)", opacity: "0" },
          to: { transform: "translateY(0)", opacity: "1" },
        },
      },
      animation: {
        "sheet-in": "sheet-in 200ms ease-out",
        "pop-in": "pop-in 150ms ease-out",
        "step-in": "step-in 200ms ease-out",
        check: "check 400ms ease-out",
      },
    },
  },
  plugins: [
    // wide: 가로로 넓은 화면(가로 태블릿·노트북). 근로자 단계 화면은 여기서 그림·문장을 왼쪽, 버튼을 오른쪽에
    // 둬 그림이 화면 높이를 다 쓰게 한다(세로로 쌓으면 1024×768에서 그림이 가로의 26%뿐이었다).
    // theme.screens에 raw 값으로 넣으면 Tailwind가 max-sm: 같은 max-* 변형을 만들지 않아(근로자 머리글이 쓴다)
    // 변형으로 따로 더한다.
    ({ addVariant }) => {
      // 3차 검증: 예전에는 폭 768 이상만 wide라 640×360·667×375·740×360 가로 휴대폰이 세로처럼 쌓여 문장이 화면 밖으로
      // 밀렸다. 가로이면서 폭 560 이상이면 두 칸으로 둔다(StepPlayer의 WIDE_QUERY와 같은 값).
      addVariant("wide", "@media (orientation: landscape) and (min-width: 560px)");
      // small: 작은 휴대폰(360 폭 이하) 또는 낮은 화면(620 높이 이하). 위 띠·아래 막대를 줄인다.
      addVariant("small", "@media (max-width: 360px), (max-height: 620px)");
      // tablet: 폭 768 이상이고 높이도 넉넉한 화면(태블릿 세로·가로). 휴대폰 가로(844×390)는 폭만 넓어 md:로는
      // 태블릿과 구분되지 않는다 — 높이 조건을 붙인다. small과는 겹치지 않는다(높이 700 이상).
      addVariant("tablet", "@media (min-width: 768px) and (min-height: 700px)");
      // land: 가로로 눕힌 휴대폰(844×390 등). 높이가 낮아 세로로 쌓으면 넘친다 — 번호 넣기는 제목·칸을 왼쪽,
      // 키패드를 오른쪽에 둔다.
      addVariant("land", "@media (orientation: landscape) and (max-height: 620px)");
      // topnarrow: 위 띠(TopBar, container-name topbar)가 22rem보다 좁을 때. 컨테이너 쿼리의 rem은 html 글자 크기를
      // 따른다(미디어 쿼리는 따르지 않는다) — 그래서 글자를 키운 좁은 휴대폰(360·390 폭, 130%)에서만 걸리고 100%
      // 글자 휴대폰에서는 걸리지 않는다. 4차 검증: 360폭 130%에서 [나가기]와 [도와주세요]가 16~46px 겹쳤다.
      addVariant("topnarrow", "@container topbar (max-width: 22rem)");
      // bandnarrow: 띠(Band, container-name band)가 22rem보다 좁을 때(topnarrow와 같은 기준). 4차 검증 2회: 360폭 130%에서
      // [취소]·[다시 부르기]가 띠 폭의 절반을 먹어 띠 글이 150px 칸에 4~5줄로 꺾였고 띠가 약 290px이 되어 문장이 밀렸다.
      addVariant("bandnarrow", "@container band (max-width: 22rem)");
      // 근로자 화면 설정(a11y_prefs). WorkerApp이 루트에 data 속성을 붙인다.
      addVariant("hc", '[data-contrast="high"] &');
      addVariant("lefty", '[data-hand="left"] &');
      addVariant("large-text", '[data-font="large"] &');
      // coarse: 손가락으로 누르는 기기(휴대폰·태블릿). 사업주 컨트롤을 36 → 44로 키운다(명세 6.3, R4).
      addVariant("coarse", "@media (pointer: coarse)");
    },
  ],
}
