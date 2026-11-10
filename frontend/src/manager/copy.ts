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

/** 아직 열지 않은 화면(contract §2.2). */
export const placeholder = {
  settingsHeading: "설정",
  settingsTitle: "설정은 준비 중이에요",
  settingsBody: "사업장·기기 연결·화면 기본값 설정은 다음 업데이트에서 열려요.",
  editorTitle: "단계 편집 화면은 준비 중이에요",
  editorBody: "다음 업데이트에서 이 주소로 그 단계를 바로 열어요.",
  editorBack: "직무 목록으로",
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

/** 옛 대시보드의 [보관하기](contract §2.1: 삭제 버튼을 보관으로 바꿈, 화면째 지우는 것은 2d). */
export const dashboardArchive = {
  button: "보관하기",
  buttonLabel: "선택한 직무 보관하기",
  confirm: (title: string) =>
    `'${title}'${eulReul(title)} 보관함으로 옮길까요?\n보관해도 수행 기록은 남아요. 직무 목록의 '보관'에서 꺼낼 수 있어요.`,
  failed: "보관하지 못했어요 · 다시 시도해 주세요",
  /** 이미 보관한 직무를 고르면 [보관하기] 대신 보이는 표시. 기록은 계속 볼 수 있다. */
  already: "보관함에 있는 직무예요",
  optionSuffix: "(보관함)",
} as const;

// --- (2c) 오늘 현황과 도움(명세 5.2, contract §5.2) ---

/** 걸린 시간: '45초', '2분 30초', '3분'. */
export function durationText(sec: number): string {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  if (s < 60) return `${s}초`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r ? `${m}분 ${r}초` : `${m}분`;
}

/** 소수 한 자리까지(끝의 .0은 뺌): 3 → '3', 2.5 → '2.5'. */
function oneDecimal(n: number): string {
  return String(Math.round((Number(n) || 0) * 10) / 10);
}

/** LiveProvider가 제목 줄에 보이는 갱신 상태(실패해도 토스트를 띄우지 않음). */
export const live = {
  lastUpdated: (time: string) => `마지막 갱신 ${time}`,
  disconnected: "연결이 잠시 끊겼어요",
  loading: "현황을 불러오고 있어요",
  loadFailed: "현황을 불러오지 못했어요",
  loadFailedBody: "인터넷 연결을 확인해 주세요. 5초마다 다시 불러와요.",
} as const;

/** 근로자 상태 배지(서버 판정 값 → 글). '도움 가는 중'은 확인했지만 아직 해결 전. */
export const liveBadge = {
  help: "도움 요청",
  help_acked: "도움 가는 중",
  offline: "연결 끊김",
  stuck_suspect: "막힘 의심",
  in_progress: "하는 중",
  new: "시작 전",
  done: "다 함",
  idle: "오늘 일 없음",
} as const;

export const home = {
  heading: "오늘 현황",
  newTask: "새 직무",
  /** '11월 8일 일요일'. */
  date: (m: number, d: number, weekday: string) => `${m}월 ${d}일 ${weekday}`,
  weekdays: ["일요일", "월요일", "화요일", "수요일", "목요일", "금요일", "토요일"],
} as const;

/** 요약 카드 4칸(누르면 아래 표나 직무 목록을 그 조건으로 걸러 봄). 완료율 %는 보이지 않는다. */
export const summaryCards = {
  label: "오늘 요약",
  working: "지금 일하는 사람",
  workingValue: (n: number, total: number) => `${n}/${total}명`,
  openHelp: "도움 요청",
  openHelpValue: (n: number) => `${n}건`,
  stuck: "막힘 의심",
  stuckValue: (n: number) => `${n}단계`,
  needsCheck: "확인이 필요한 직무",
  needsCheckValue: (n: number) => `${n}개`,
  needsCheckHint: "직무 목록에서 보기",
  filtering: (label: string) => `'${label}'${euroRo(label)} 걸러 보는 중이에요`,
  clearFilter: "걸러보기 지우기",
} as const;

/** 근로자 실시간 표(행 56). */
export const liveTable = {
  heading: "근로자",
  caption: "근로자 실시간 현황",
  colWorker: "근로자",
  colTask: "지금 하는 일",
  colProgress: "진행",
  colStep: "지금 단계",
  colStatus: "상태",
  colActivity: "마지막 활동",
  colMenu: "메뉴",
  progress: (done: number, total: number) => `${done}/${total}`,
  progressLabel: (done: number, total: number) => `${total}단계 중 ${done}단계 함`,
  stepLine: (order: number, sentence: string) => `${order}단계 · ${sentence}`,
  noTask: "오늘 할 일 없음",
  allDone: "오늘 일을 다 했어요",
  notYet: "아직 없음",
  offlineSince: (min: number) => `마지막 신호 ${min}분 전`,
  rowMenu: (name: string) => `${name} 님 메뉴`,
  openTimeline: "오늘 기록 보기",
  workerInfo: "근로자 정보 보기",
  emptyFiltered: "이 조건에 맞는 근로자가 없어요",
  noWorkers: "아직 등록한 근로자가 없어요",
} as const;

/** 도움 요청 띠(모든 /m 화면 맨 위, 최대 3건 + '그 외 N건'). */
export const helpBand = {
  region: "도움 요청",
  requested: "님이 도움을 요청했어요",
  stepOf: (order: number) => `${order}단계`,
  seeMore: "보러 가기",
  fixStep: "이 단계 고치기",
  resolve: "도와줬어요",
  ack: "확인했어요",
  acked: "도움 가는 중",
  more: (n: number) => `그 외 ${n}건`,
  actionsMenu: (name: string) => `${name} 님 도움 요청 메뉴 더 보기`,
  actionFailed: "처리하지 못했어요. 다시 눌러 주세요.",
} as const;

/** 오늘 기록 서랍(오른쪽 480). 차트에는 '표로 보기'를 함께 둔다. */
export const timeline = {
  title: (name: string) => `${name} 님 오늘 기록`,
  description: "단계별 걸린 시간, 다시 듣기, 이전 누름, 도움을 보여 줘요.",
  viewLabel: "보는 방법",
  chartView: "막대로 보기",
  tableView: "표로 보기",
  tableCaption: (title: string) => `${title} 단계별 기록`,
  colStep: "단계",
  colDuration: "걸린 시간",
  colReplay: "다시 듣기",
  colPrev: "이전 누름",
  colHelp: "도움",
  times: (n: number) => `${n}번`,
  notDone: "아직 안 함",
  noRecord: "오늘 받은 일이 없어요",
  eventsHeading: "시간 순 기록",
  event: {
    step_done: (order: number) => `${order}단계를 했어요`,
    help_open: "도움을 요청했어요",
    help_ack: "선생님이 확인했어요",
    help_resolved: "도움을 받았어요",
    help_cancelled: "도움 요청을 그만뒀어요",
  },
  loadFailed: "기록을 불러오지 못했어요",
  retry: "다시 불러오기",
} as const;

/** 고치면 좋은 단계(규칙만으로 만든 제안, 유료 모델 없이 동작). */
export const coaching = {
  heading: "고치면 좋은 단계",
  description: "지난 7일 기록에서 근로자가 오래 머물거나 다시 들은 단계예요.",
  empty: "지금은 고칠 단계가 없어요",
  emptyBody: "근로자가 일을 하면 기록을 보고 제안을 보여 드려요.",
  suggestion: {
    photo: "사진으로 바꾸기",
    split: "두 단계로 나누기",
    easy_words: "쉬운 말로 바꾸기",
  },
  suggestionLabel: "제안",
  replay: (n: number) => `다시 듣기 평균 ${oneDecimal(n)}번`,
  avg: (sec: number) => `평균 ${durationText(sec)}`,
  help: (n: number) => `도움 ${n}번`,
  runs: (n: number) => `${n}번 함`,
  fix: "이 단계 고치기",
  fixLabel: (title: string, sentence: string) => `이 단계 고치기 · ${title} '${sentence}'`,
  after: (v: number) => `${v}번째 보낸 뒤`,
  afterAvg: (sec: number) => `평균 ${durationText(sec)}`,
  removed: "편집 화면에서 지운 단계예요",
  loadFailed: "제안을 불러오지 못했어요",
} as const;

/** 새 사업장 빈 상태: 시작 점검표 3단계 + [바로 하기]. */
export const homeEmpty = {
  title: "시작해 볼까요?",
  description: "세 가지만 하면 근로자가 그림 카드로 일을 시작해요.",
  steps: [
    { title: "근로자 추가", body: "근로자 이름을 적으면 4자리 번호가 생겨요." },
    { title: "기기 연결", body: "근로자 휴대폰에서 사업장 코드와 번호를 넣어요." },
    { title: "첫 직무 보내기", body: "하는 일을 말로 적고 근로자에게 보내요." },
  ],
  go: "바로 하기",
  goLabel: (title: string) => `${title} 바로 하기`,
  done: "했어요",
} as const;

/** 상단 바 사용자 메뉴의 웹 푸시 스위치. */
export const pushToggle = {
  label: "도움 알림 받기",
  on: "켜짐",
  off: "꺼짐",
  turnedOn: "도움 알림을 켰어요. 이 화면을 안 보고 있어도 알려 드려요.",
  turnedOff: "도움 알림을 껐어요",
  denied: "브라우저가 알림을 막고 있어요. 브라우저 설정에서 알림을 허용해 주세요.",
  failed: "알림을 켜지 못했어요. 잠시 뒤 다시 눌러 주세요.",
} as const;
