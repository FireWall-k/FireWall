// 사업주 화면 문구 사전(명세 6.7, contract §0·§3.7). 새 사업주 화면의 글은 모두 여기서 가져간다.
// 규칙: '~해요' 체, 버튼은 동사로 끝냄, 결과는 숫자 + 할 일, 오류는 무엇이 안 됐는지 + 다음 할 일,
// 영어 enum·'AI'·공급자 이름은 보이지 않음, 자동 결과는 '✦ 자동', 근로자는 '김민지 님'.
// tests/managerCopy.test.ts가 이 파일 전체를 훑어 금지어를 막고, §3.7 문구는 글자 그대로 비교한다.

import { eulReul, euroRo } from "./josa";

/** 사람을 부를 때: '김민지 님'. */
export const person = (name: string) => `${name} 님`;

/** 직무 상태(서버 TaskSummaryOut.state). 화면에는 영어 값을 보이지 않는다. */
export const taskState = {
  draft: "초안",
  published: "보냄",
  archived: "보관",
} as const;

/** 직무 목록 걸러보기(contract §2.1, 서로 겹침). */
export const taskFilter = {
  all: "전체",
  draft: "초안",
  needs_check: "확인 필요",
  published: "보냄",
  archived: "보관",
} as const;

/** 사이드바·아래 탭바·이동 경로. '그림'은 파일럿 전까지 숨긴다(명세 3.3). */
export const nav = {
  home: "홈",
  tasks: "직무",
  workers: "근로자",
  pictures: "그림",
  settings: "설정",
  more: "더보기",
  newTask: "새 직무",
  editTask: "직무 고치기",
  workerDetail: "근로자 상세",
  mainNav: "주 메뉴",
  mobileNav: "아래 메뉴",
  breadcrumb: "이동 경로",
} as const;

/** 틀(AppShell·TopBar). */
export const shell = {
  brand: "잡카드",
  skipToContent: "본문으로 건너뛰기",
  userMenu: "계정 메뉴",
  userMenuSuffix: " 계정 메뉴",
  logout: "로그아웃",
  employerFallbackName: "사업주",
  helpBell: (n: number) => (n > 0 ? `도움 요청 ${n}건 · 띠로 가기` : "도움 요청 없음"),
} as const;

/** 공통 부품 글(Dialog·Toast·Table·EmptyState). */
export const ui = {
  close: "닫기",
  cancel: "취소",
  confirm: "확인",
  delete: "지우기",
  undo: "실행 취소",
  retry: "다시 시도",
  loading: "불러오는 중이에요",
  empty: "아직 아무것도 없어요",
  loadFailed: "불러오지 못했어요",
  deletedItemsTitle: "함께 지워지는 것",
  confirmNameLabel: (name: string) => `지우려면 '${name}'${eulReul(name)} 똑같이 적어 주세요`,
} as const;

/** 오류 문장: 무엇이 안 됐는지 · 다음 할 일. */
export const errors = {
  network: "서버에 닿지 못했어요 · 인터넷 연결을 확인하고 다시 시도해 주세요",
  save: "저장하지 못했어요 · 다시 시도해 주세요",
  load: "불러오지 못했어요 · 잠시 뒤 다시 시도해 주세요",
  session: "로그인이 끝났어요 · 다시 로그인해 주세요",
  generic: "처리하지 못했어요 · 다시 시도해 주세요",
} as const;

/** 직무 목록 행(contract §2.1 행 배지, 명세 5.3). */
export const taskRow = {
  needsCheck: (n: number) => `확인 필요 ${n}`,
  unsentChanges: "고친 내용 안 보냄",
  stepCount: (n: number) => `${n}단계`,
  recipientsMore: (n: number) => `+${n}`,
  recipientsLabel: (n: number) => `받은 사람 ${n}명`,
  noRecipients: "아직 안 보냄",
  rowMenu: (title: string) => `${title} 메뉴`,
} as const;

/** 직무 … 메뉴(명세 5.3). 편집은 2b-1 새 편집기에서 열린다. */
export const taskMenu = {
  edit: "고치기",
  editLater: "새 편집기에서 열려요",
  duplicate: "복제해서 고치기",
  archive: "보관하기",
  unarchive: "보관함에서 꺼내기",
  delete: "완전히 지우기",
} as const;

/** 보내기 점검표 code(contract §0: 서버는 code와 숫자만 보낸다). */
export type SendCheckCode =
  | "no_picture"
  | "unconfirmed_auto"
  | "unreviewed_split"
  | "too_long"
  | "hard_word"
  | "command_tone"
  | "auto_caution";

/** 점검표 줄 문구(contract §3.7, 글자 그대로). done/total은 '다 된 수/전체', count는 걸린 수. */
export const sendCheck = {
  no_picture: (done: number, total: number) => `모든 단계에 그림이 있어요 ${done}/${total}`,
  unconfirmed_auto: (done: number, total: number) => `자동으로 고른 그림을 확인했어요 ${done}/${total}`,
  unreviewed_split: (done: number, total: number) => `자동으로 나눈 문장을 확인했어요 ${done}/${total}`,
  too_long: (count: number) => `긴 문장이 ${count}개 있어요`,
  hard_word: (count: number) => `어려운 낱말이 ${count}개 있어요`,
  command_tone: (count: number) => `~하세요 체 문장이 ${count}개 있어요`,
  auto_caution: (count: number) => `✦ 자동으로 켠 조심 표시가 ${count}개 있어요`,
} as const;

/** 서버가 보낸 점검 한 줄을 문장으로. 모르는 code는 영어를 보이지 않고 일반 문장을 쓴다. */
export function sendCheckLabel(code: string, n: { done?: number; total?: number; count?: number }): string {
  const done = n.done ?? 0;
  const total = n.total ?? 0;
  const count = n.count ?? 0;
  switch (code as SendCheckCode) {
    case "no_picture":
    case "unconfirmed_auto":
    case "unreviewed_split":
      return sendCheck[code as "no_picture"](done, total);
    case "too_long":
    case "hard_word":
    case "command_tone":
    case "auto_caution":
      return sendCheck[code as "too_long"](count);
    default:
      return `확인할 것이 ${count || 1}개 있어요`;
  }
}

/** 보내기 시트(contract §3.7, 2b-1에서 씀). */
export const sendSheet = {
  title: "보내기 전에 확인해요",
  sentToast: (n: number) => `${n}명에게 보냈어요 · 현황 보기`,
  inProgressNote: (name: string) => `${name} 님은 지금 하는 중이라 다음에 보낼 때부터 바뀌어요`,
  disabledTooltip: (n: number) => `확인할 것 ${n}개가 남았어요. 확인하면 보낼 수 있어요`,
  prefilled: "지난번 받은 사람을 골라 두었어요",
} as const;

/** 편집기 위 버전 안내(contract §3.7, 2b-1에서 씀). */
export const versionNotice = {
  working: (m: number, k: number) => `이 직무를 받은 ${m}명 중 ${k}명이 지금 하고 있어요`,
  nextTime: "다음에 보낼 때부터 바뀌어요",
} as const;

/** 로그인(명세 5.1, R12). */
export const login = {
  title: "로그인",
  intro: "말로 적으면, 그림 카드 일 안내가 됩니다",
  tabsLabel: "누가 들어오나요",
  employerTab: "사업주",
  workerTab: "근로자",
  loginId: "아이디",
  password: "비밀번호",
  workplaceCode: "사업장 코드",
  workplaceHint: "사업주에게 받은 사업장 코드를 넣어 주세요. 한 번 로그인하면 이 기기에 저장돼요.",
  keepWorkplace: (code: string) => `취소 (사업장 ${code} 그대로 쓰기)`,
  workplaceSaved: "사업장",
  changeWorkplace: "이 기기 사업장 변경",
  accessCode: "접속 코드",
  demoFilled: "시연용 데모 계정이 미리 채워져 있어요. 로그인을 눌러 주세요.",
  submit: "로그인",
  submitting: "확인하고 있어요",
  failed: "로그인하지 못했어요 · 다시 시도해 주세요",
  workerQuestion: "근로자이신가요?",
  workerLink: "근로자 화면으로 ›",
  examplesLabel: "단계 카드 예시",
  examples: ["손을 깨끗이 씻어요", "앞치마를 입어요", "컵을 물에 넣어요"],
} as const;

/** 아직 열지 않은 화면(contract §2.2). 홈 '오늘 현황'은 2c에서 열린다. */
export const placeholder = {
  homeHeading: "홈",
  homeTitle: "오늘 현황은 준비 중이에요",
  homeBody: "근로자별 수행 기록은 근로자 화면의 '현황'에서 볼 수 있어요.",
  homeWorkers: "근로자 보기",
} as const;

/** 직무 목록 화면(명세 5.3, tasks §3.3). */
export const taskList = {
  title: "직무",
  newTask: "새 직무",
  filterLabel: "직무 걸러보기",
  searchLabel: "제목으로 찾기",
  searchPlaceholder: "예: 컵 씻기",
  caption: "직무 목록",
  colTitle: "직무",
  colSteps: "단계",
  colStatus: "상태",
  colRecipients: "받은 사람",
  colUpdated: "고친 날",
  colMenu: "메뉴",
  noCover: "그림 없음",
  emptyTitle: "아직 만든 직무가 없어요",
  emptyBody: "하는 일을 말로 적으면 그림 카드 단계로 나눠 드려요.",
  emptyCreate: "새 직무 만들기",
  emptyExample: "예시로 만들어 보기",
  filteredEmpty: (label: string) => `'${label}'에 해당하는 직무가 없어요`,
  searchEmpty: (q: string) => `'${q}'${euroRo(q)} 찾은 직무가 없어요`,
  archivedEmptyBody: "보관한 직무는 여기에 모여요. 보관해도 수행 기록은 남아요.",
  clearSearch: "검색 지우기",
  /** 걸러보기·검색을 바꾼 뒤 화면 읽기 프로그램에 알리는 결과 수. */
  resultCount: (n: number) => (n > 0 ? `직무가 ${n}개 있어요` : "맞는 직무가 없어요"),
} as const;

/** 직무 목록에서 한 일의 결과(토스트). 제목은 따옴표로 감싼다. */
export const taskToast = {
  archived: (title: string) => `'${title}'${eulReul(title)} 보관함으로 옮겼어요`,
  unarchived: (title: string) => `'${title}'${eulReul(title)} 보관함에서 꺼냈어요`,
  duplicated: (title: string) => `'${title}'${eulReul(title)} 새 초안으로 만들었어요`,
  deleted: (title: string) => `'${title}'${eulReul(title)} 완전히 지웠어요`,
} as const;

/** 완전히 지우기 위험 창(명세 5.0: 지워지는 것을 목록으로, contract §1.7). */
export const taskDelete = {
  title: (title: string) => `'${title}'${eulReul(title)} 완전히 지울까요?`,
  description: "지우면 되돌릴 수 없어요. 기록을 남기려면 보관한 채로 두면 돼요.",
  items: ["직무의 모든 단계와 보낸 버전", "근로자에게 보낸 배정", "수행 기록과 도움 요청 기록", "단계에 붙인 사진·음성 연결"],
  confirm: "완전히 지우기",
} as const;

/** 고친 날(상대 시간). 일주일이 넘으면 날짜로 쓴다. */
export const relative = {
  justNow: "방금",
  minutes: (n: number) => `${n}분 전`,
  hours: (n: number) => `${n}시간 전`,
  yesterday: "어제",
  days: (n: number) => `${n}일 전`,
  date: (m: number, d: number) => `${m}월 ${d}일`,
  dateWithYear: (y: number, m: number, d: number) => `${y}년 ${m}월 ${d}일`,
} as const;

/** 오늘 상태 배지(contract §6.2 today_badge). 색 + 아이콘 + 글로 보인다(명세 8.2). */
export const todayBadge = {
  help: "도움 요청",
  help_coming: "도움 가는 중",
  done: "다 했어요",
  in_progress: "하는 중",
  not_started: "시작 전",
  none: "오늘 일 없음",
} as const;

/** 동의 상태(명세 5.7). 'AI' 대신 '자동 처리'. */
export const consentState = {
  complete: "동의 완료",
  ai_missing: "자동 처리 미동의",
  missing: "개인정보 동의 없음",
} as const;

/** 접속 코드 가리기·보기(명세 5.7: ●●●● + 눈 5초). */
export const accessCode = {
  show: (name: string) => `${name} 님 번호 5초 보기`,
  hide: (name: string) => `${name} 님 번호 가리기`,
  copy: "복사하기",
  copied: "번호를 복사했어요",
  copyFailed: "복사하지 못했어요 · 번호를 직접 적어 주세요",
  print: "인쇄용 카드 만들기",
  reissue: "새 번호 만들기",
  reissueTitle: (name: string) => `${name} 님 번호를 새로 만들까요?`,
  reissueBody: "예전 번호로는 더 들어갈 수 없어요. 새 번호를 근로자에게 알려 주세요.",
  reissued: (name: string) => `${name} 님 새 번호를 만들었어요`,
  freshTitle: (name: string) => `${name} 님 새 번호예요`,
  freshBody: "이 번호를 근로자에게 알려 주세요. 창을 닫으면 번호는 다시 가려져요.",
  freshClose: "다 봤어요",
  current: "지금 번호",
  shortCode: "예전에 만든 긴 번호예요. 새 번호를 만들면 4자리가 돼요.",
} as const;

/** 근로자 목록(/m/workers, 명세 5.7). */
export const workerList = {
  title: "근로자",
  add: "근로자 추가하기",
  caption: "근로자 목록",
  colName: "이름",
  colToday: "오늘",
  colDone7: "최근 7일 완료",
  colHelp: "도움 요청",
  colConsent: "동의",
  colCode: "번호",
  colMenu: "메뉴",
  rowMenu: (name: string) => `${name} 님 메뉴`,
  open: "자세히 보기",
  delete: "지우기",
  done7Label: (n: number) => `최근 7일 동안 ${n}번 다 했어요`,
  times: (n: number) => `${n}번`,
  emptyTitle: "아직 근로자가 없어요",
  emptyBody: "근로자를 추가하면 4자리 번호가 생겨요. 그 번호로 근로자 화면에 들어가요.",
} as const;

/** 근로자 추가 창(명세 5.7). */
export const workerAdd = {
  title: "근로자 추가하기",
  name: "이름",
  namePlaceholder: "예: 김민지",
  nameRequired: "이름을 적어 주세요",
  note: "특성 메모 (선택)",
  noteHint: "예: 그림을 보면 더 잘 알아요. 메모는 사업주만 봐요.",
  submit: "추가하기",
  doneTitle: (name: string) => `${name} 님을 추가했어요`,
  doneBody: "이 번호를 근로자에게 알려 주세요. 근로자 화면에서 이 4자리만 누르면 들어가요.",
  codeLabel: "근로자 번호",
  close: "다 했어요",
} as const;

/** 인쇄용 카드(이름·QR·번호). */
export const printCard = {
  title: "인쇄용 카드",
  workerHeading: (name: string) => `${name} 님`,
  codeLabel: "내 번호",
  siteLabel: "사업장 코드",
  qrLabel: "기기 연결 QR 코드",
  howTo: "휴대폰 카메라로 QR 코드를 비추면 이 사업장 근로자 화면이 열려요.",
  print: "인쇄하기",
  deviceHeading: "기기 연결 카드",
} as const;

/** 근로자 지우기(이름 다시 적기, contract §6.2). */
export const workerDelete = {
  title: (name: string) => `${name} 님을 지울까요?`,
  description: "지우면 되돌릴 수 없어요. 필요하면 '동의·개인정보'에서 기록을 먼저 내려받아 주세요.",
  items: ["근로자 정보와 메모", "받은 배정과 수행 기록", "도움 요청 기록", "동의 기록"],
  done: (name: string) => `${name} 님을 지웠어요`,
  mentions: (n: number) => `직무 ${n}개에 이름이 남아 있어요 · 직무 문장을 고쳐 주세요`,
} as const;

/** 근로자 상세(/m/workers/:id) 탭. */
export const workerDetail = {
  tabsLabel: "근로자 상세",
  tabStats: "현황",
  tabPrefs: "화면 설정",
  tabCode: "접속 코드",
  tabConsent: "동의·개인정보",
  notFound: "근로자를 찾을 수 없어요",
  back: "근로자 목록으로",
  ambiguousName: "이름이 흔한 낱말과 같아요. 직무 문장에는 이름 대신 '근로자'라고 써 주세요.",
} as const;

/** 근로자 상세 '현황'(명세 5.7: 단위는 '2분 28초', 차트에 숫자와 표로 보기). */
export const workerStats = {
  heading: "최근 7일",
  doneChart: "날마다 다 한 일",
  doneBarLabel: (day: string, n: number) => `${day} ${n}번 다 했어요`,
  stepChart: "단계별 평균 시간",
  avgStep: "단계 평균 시간",
  totalDone: "다 한 일",
  totalHelp: "도움 요청",
  showTable: "표로 보기",
  showChart: "차트로 보기",
  tableCaption: "단계별 기록",
  colTask: "직무",
  colStep: "단계",
  colAvg: "평균 시간",
  colReplay: "다시 듣기",
  colHelp: "도움 요청",
  dayCaption: "날마다 기록",
  colDay: "날짜",
  colAssigned: "받은 일",
  colDone: "다 한 일",
  emptyTitle: "아직 기록이 없어요",
  emptyBody: "근로자가 일을 하면 여기에 단계별 시간이 쌓여요.",
  stepName: (order: number, sentence: string) => `${order}. ${sentence}`,
  times: (n: number) => `${n}번`,
  dayLabel: (m: number, d: number) => `${m}/${d}`,
} as const;

/** 초 → '2분 28초'(명세 5.7). 1분 미만·딱 떨어지는 분도 자연스럽게. */
export function duration(sec: number): string {
  const total = Number.isFinite(sec) ? Math.max(0, Math.round(sec)) : 0;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return m > 0 ? `${h}시간 ${m}분` : `${h}시간`;
  if (m > 0) return s > 0 ? `${m}분 ${s}초` : `${m}분`;
  return `${s}초`;
}

/** 근로자 화면 설정(명세 4.12 표 그대로). 근로자 상세와 설정의 기본값이 같이 쓴다. */
export const prefs = {
  heading: "근로자 화면 설정",
  hint: "근로자 서버 정보에 저장돼서 기기를 바꿔도 같아요. 다음에 근로자가 화면을 열 때부터 바뀌어요.",
  defaultsHeading: "근로자 화면 기본값",
  defaultsHint: "새로 추가하는 근로자에게 이 값이 들어가요. 이미 있는 근로자는 바뀌지 않아요.",
  saved: "저장했어요",
  font_size: { label: "글자 크기", normal: "기본", large: "크게" },
  autoplay_sound: { label: "소리 자동 재생", hint: "단계에 들어가면 문장을 한 번 읽어 줘요." },
  tts_rate: { label: "말 속도", slow: "느리게", normal: "보통", fast: "조금 빠르게" },
  sound: { label: "효과음·진동" },
  sfx: { label: "효과음" },
  vibration: { label: "진동" },
  praise: { label: "칭찬", normal: "보통", quiet: "조용히" },
  hand: { label: "손 방향", right: "오른손", left: "왼손", hint: "왼손이면 [다 했어요]가 왼쪽에 와요." },
  contrast: { label: "화면 대비", normal: "기본", high: "고대비" },
} as const;

/** 동의·개인정보 탭(옛 WorkersPage 로직을 옮김). 법정 동의 이름도 'AI' 대신 '자동 처리'(창업자 결정). */
export const consent = {
  heading: "동의·개인정보",
  personal: "개인정보 수집·이용 동의",
  automated: "자동 처리·국외 이전 동의",
  automatedBadge: "자동 처리 동의",
  received: "받음",
  notReceived: "아직 없음",
  self: "당사자",
  guardian: "보호자",
  recordFrom: (who: string) => `${who}에게 받았어요`,
  revoke: "철회 기록하기",
  grantTitle: (label: string) => `${label}를 받았나요?`,
  grantBody: (who: string, name: string) =>
    `${who}에게서 ${name} 님 동의를 받았다고 기록해요. 동의서 원본은 사업장에서 보관해 주세요.`,
  automatedBody: "동의하면 자동 코칭에 이 근로자의 수행 기록이 쓰여요. 기록은 국외 서버에서 처리될 수 있어요.",
  revokeTitle: (label: string) => `${label} 철회를 기록할까요?`,
  personalRevokeBody: "철회한 뒤에는 이 근로자의 개인정보를 더 쓰지 말고, 필요하면 내려받은 뒤 지워 주세요.",
  automatedRevokeBody: "철회하면 자동 코칭은 기본 규칙 제안만 나와요.",
  recorded: (label: string) => `${label}를 기록했어요`,
  revoked: (label: string) => `${label} 철회를 기록했어요`,
  note: "특성 메모",
  noteHint: "사업주만 봐요. 기본으로는 자동 코칭에 보내지 않아요.",
  noteSave: "메모 저장하기",
  noteSaved: "메모를 저장했어요",
  noteForCoaching: "자동 코칭에 메모 쓰기",
  noteNeedsConsent: "자동 처리 동의를 기록하기 전에는 메모를 보내지 않아요.",
  export: "기록 내려받기",
  exportHint: "열람 요구에 답할 때 써요. 파일에 개인정보가 있으니 안전하게 보관해 주세요.",
  exported: "기록을 내려받았어요",
  deleteHeading: "근로자 지우기",
  deleteButton: "이 근로자 지우기",
} as const;

/** 설정(/m/settings, 명세 5.8). PIN(선생님 모드)은 3차라 숨긴다. */
export const settings = {
  title: "설정",
  workplaceHeading: "사업장",
  orgName: "사업장 이름",
  orgNameSave: "이름 저장하기",
  orgNameSaved: "사업장 이름을 저장했어요",
  workplaceCode: "사업장 코드",
  copyCode: "코드 복사하기",
  codeCopied: "사업장 코드를 복사했어요",
  deviceHeading: "기기 연결",
  deviceBody:
    "근로자 휴대폰·태블릿으로 QR 코드를 비추거나 주소를 열면 이 사업장 근로자 화면이 바로 열려요. 그다음엔 근로자 번호 4자리만 누르면 돼요.",
  deviceLink: "기기 연결 주소",
  copyLink: "주소 복사하기",
  linkCopied: "주소를 복사했어요",
  copyFailed: "복사하지 못했어요 · 직접 적어 주세요",
  printCard: "인쇄용 카드 만들기",
  titleHeading: "근로자 화면에서 부르는 호칭",
  titleLabel: "호칭",
  titleHint: "한글 1~6자. 예: 선생님, 코치, 팀장",
  titleInvalid: "호칭은 한글 1~6자로 적어 주세요.",
  titlePreview: "근로자 화면 미리보기",
  titleSave: "호칭 저장하기",
  titleSaved: "호칭을 저장했어요",
  notifyHeading: "알림",
  notifyLabel: "도움 알림 받기",
  notifyHint: "근로자가 도움을 요청하면 이 기기에 알림이 와요. 잠금 화면에는 이름이 보이지 않아요.",
  notifyLater: "알림은 다음 업데이트에서 켤 수 있어요.",
  accountHeading: "계정",
  accountName: "로그인한 이름",
  logout: "로그아웃",
} as const;
