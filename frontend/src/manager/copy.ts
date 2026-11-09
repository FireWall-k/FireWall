// 사업주 화면 문구 사전(명세 6.7, contract §0·§3.7). 새 사업주 화면의 글은 모두 여기서 가져간다.
// 규칙: '~해요' 체, 버튼은 동사로 끝냄, 결과는 숫자 + 할 일, 오류는 무엇이 안 됐는지 + 다음 할 일,
// 영어 enum·'AI'·공급자 이름은 보이지 않음, 자동 결과는 '✦ 자동', 근로자는 '김민지 님'.
// tests/managerCopy.test.ts가 이 파일 전체를 훑어 금지어를 막고, §3.7 문구는 글자 그대로 비교한다.

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
  confirmNameLabel: (name: string) => `지우려면 '${name}'을(를) 똑같이 적어 주세요`,
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
  settingsTitle: "설정은 준비 중이에요",
  settingsBody: "사업장·기기 연결·화면 기본값 설정은 다음 업데이트에서 열려요.",
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
  searchEmpty: (q: string) => `'${q}'(으)로 찾은 직무가 없어요`,
  archivedEmptyBody: "보관한 직무는 여기에 모여요. 보관해도 수행 기록은 남아요.",
  clearSearch: "검색 지우기",
} as const;

/** 직무 목록에서 한 일의 결과(토스트). 제목은 따옴표로 감싼다. */
export const taskToast = {
  archived: (title: string) => `'${title}'을(를) 보관함으로 옮겼어요`,
  unarchived: (title: string) => `'${title}'을(를) 보관함에서 꺼냈어요`,
  duplicated: (title: string) => `'${title}'을(를) 새 초안으로 만들었어요`,
  deleted: (title: string) => `'${title}'을(를) 완전히 지웠어요`,
} as const;

/** 완전히 지우기 위험 창(명세 5.0: 지워지는 것을 목록으로, contract §1.7). */
export const taskDelete = {
  title: (title: string) => `'${title}'을(를) 완전히 지울까요?`,
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
    `'${title}'을(를) 보관함으로 옮길까요?\n보관해도 수행 기록은 남아요. 직무 목록의 '보관'에서 꺼낼 수 있어요.`,
  failed: "보관하지 못했어요 · 다시 시도해 주세요",
} as const;
