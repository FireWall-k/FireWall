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

/** 직무 … 메뉴(명세 5.3, contract §3.6). */
export const taskMenu = {
  edit: "고치기",
  resend: "다시 보내기",
  /** 확인할 것이 남은 직무의 [다시 보내기]: 누르면 그 직무 편집기의 첫 확인 단계로 간다. */
  resendBlocked: (n: number) => `확인할 것 ${n}개가 남았어요`,
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

/** 보내기 시트(contract §3.6·3.7). */
export const sendSheet = {
  title: "보내기 전에 확인해요",
  /** 성공 토스트는 글(sentMessage)과 [현황 보기] 단추로 나눠 그린다 — 합치면 sentToast(contract §3.7 글자 그대로). */
  sentToast: (n: number) => `${n}명에게 보냈어요 · 현황 보기`,
  sentMessage: (n: number) => `${n}명에게 보냈어요`,
  viewStatus: "현황 보기",
  inProgressNote: (name: string) => `${name} 님은 지금 하는 중이라 다음에 보낼 때부터 바뀌어요`,
  disabledTooltip: (n: number) => `확인할 것 ${n}개가 남았어요. 확인하면 보낼 수 있어요`,
  prefilled: "지난번 받은 사람을 골라 두었어요",
  /** 머리 아래 덧줄(has_unsent_changes): 다음에 만들어질 버전 번호. */
  versionLine: (no: number) => `고친 내용도 함께 보내요 · ${no}번째 버전`,
  loading: "점검표와 받는 사람을 불러오고 있어요",
  loadFailed: "점검표를 불러오지 못했어요 · 다시 시도해 주세요",
  checksHeading: "점검표",
  checksHint: "막힌 줄을 누르면 그 단계로 가요",
  /** 막힌 줄 없이 경고만 있을 때(보내기는 막지 않는다). */
  warnsHint: "줄을 누르면 그 단계로 가요. 보내기는 그대로 할 수 있어요",
  goToStep: (label: string) => `${label} · 그 단계로 가기`,
  recipientsHeading: "받는 사람",
  searchLabel: "이름으로 찾기",
  selectAll: "모두 선택",
  clearAll: "모두 해제",
  noWorkers: "아직 근로자가 없어요. 근로자 화면에서 먼저 더해 주세요.",
  noMatch: "찾는 이름이 없어요",
  status: {
    done: "오늘 이미 다 했어요 · 한 번 더 보내요",
    in_progress: "지금 하는 중이라 다음부터 바뀌어요",
    not_started: "아직 시작 전이에요",
    none: "",
  },
  whenHeading: "언제",
  today: "오늘",
  tomorrow: "내일",
  pickDate: "날짜 고르기",
  dateLabel: "보낼 날짜",
  submit: (n: number) => `${n}명에게 보내기`,
  needRecipient: "받는 사람을 한 명 이상 골라 주세요",
  needDate: "보낼 날짜를 골라 주세요",
  failed: "보내지 못했어요 · 다시 시도해 주세요",
  archived: "보관한 직무는 보낼 수 없어요. 보관함에서 꺼낸 뒤 보내 주세요.",
  noSteps: "단계가 하나도 없어요. 단계를 넣어 주세요.",
} as const;

/** 편집기 위 버전 안내(contract §3.7, 2b-1에서 씀). */
export const versionNotice = {
  // 하는 사람이 0명이면 '0명이 지금 하고 있어요' 대신 받은 사람 수만(2회차 검증, TODO(창업자 확인): 문구).
  working: (m: number, k: number) => (k > 0 ? `이 직무를 받은 ${m}명 중 ${k}명이 지금 하고 있어요` : `이 직무를 받은 사람이 ${m}명 있어요`),
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

/** 새 직무 화면(명세 5.4, tasks §4.3 NewTaskPage). */
export const newTask = {
  heading: "새 직무",
  label: "어떤 일을 시킬까요?",
  hint: "평소 말하듯 적어 주세요. 단계는 잡카드가 나눠요.",
  placeholder: "예: 출근하면 앞치마 입고 손 씻고, 컵 씻어서 건조대에 올려 놔.",
  charCount: (n: number, max: number) => `${n}/${max}자`,
  fillExample: "예시 넣기",
  exampleNote: "예시를 채워 두었어요. 고쳐도 되고, 그대로 [단계로 나누기]를 눌러 봐도 돼요.",
  restored: "적던 내용을 다시 불러왔어요",
  more: "더 알려 주기(선택)",
  businessType: "업종",
  businessTypeHint: "예: 카페, 물류",
  workEnvironment: "일하는 곳",
  workEnvironmentHint: "예: 창고, 미끄러운 바닥",
  workerNote: "근로자 특성",
  workerNoteHint: "예: 그림을 보면 더 잘 알아요",
  noteWorker: "맞춤 대상 근로자",
  noteWorkerNone: "고르지 않음",
  noteWorkerHint: "근로자 특성은 그 근로자의 메모 사용 설정을 켜고 처리 동의를 기록한 경우에만 자동 나누기에 쓰여요.",
  privacy: "근로자 이름은 A로 바꿔서 처리해요.",
  split: "단계로 나누기",
  splitting: "문장을 나누고 있어요",
  splitEmpty: "나눌 문장을 찾지 못했어요. 할 일을 조금 더 자세히 적어 주세요.",
  splitFailed: "문장을 나누지 못했어요 · 잠시 뒤 다시 눌러 주세요",
  createFailed: "초안을 만들지 못했어요 · 잠시 뒤 다시 눌러 주세요",
  resplitTitle: "새로 나눌까요?",
  resplitBody: "고친 줄이 있어요. 새로 나누면 고친 내용은 사라져요.",
  resplitConfirm: "새로 나누기",
  leaveTitle: "적던 내용이 사라져요",
  leaveBody: "이 화면을 떠나면 적던 지시문과 나눈 단계가 지워져요.",
  leaveConfirm: "나가기",
  leaveCancel: "계속 적기",
} as const;

/** 입력 화면에서 나눈 단계 목록(명세 5.4·3.4-A 2번: 나누기는 이 순간에 끝낸다). */
export const splitList = {
  title: "이렇게 나눴어요",
  count: (n: number) => `(${n}단계)`,
  rule: "한 줄에 동작 하나, 그림 한 장",
  checkNotice: (n: number) =>
    `노란 줄 ${n}개는 나눈 곳이 애매해요. 맞으면 그대로 두고, 아니면 [합치기]나 [더 나누기]를 눌러 주세요.`,
  stale:
    "직무 내용을 고쳤어요. 아래 목록은 고치기 전 글로 나눈 것이에요. [이대로 그림 고르기]를 누르면 아래 목록대로 만들어요. 고친 글로 새로 나누려면 [단계로 나누기]를 다시 눌러 주세요.",
  rowLabel: (n: number) => `${n}단계 문장`,
  rowPlaceholder: "이 단계에서 할 일을 적어 주세요",
  merge: "합치기",
  mergeLabel: (a: number, b: number) => `${a}단계와 ${b}단계 합치기`,
  splitMore: "더 나누기",
  splitMoreLabel: (n: number) => `${n}단계 더 나누기`,
  splitMoreHint: "커서를 둔 곳에서 두 줄로 나눠요. 커서가 없으면 아래에 빈 줄을 만들어요.",
  deleteLabel: (n: number) => `${n}단계 지우기`,
  lastRow: "마지막 한 줄은 지울 수 없어요",
  full: (max: number) => `단계는 ${max}줄까지예요`,
  addRow: "한 줄 추가",
  noGroupHint: "동작이 여러 개일 수 있어요. 나눌 곳에 커서를 두고 [더 나누기]를 눌러 주세요.",
  groupHint: (source: string) => (source ? `나눈 곳 확인 · 원래 문장: “${source}”` : "나눈 곳 확인"),
  emptyRows: (list: string) => `${list}가 비어 있어요. 문장을 적거나 그 줄을 지워 주세요.`,
  confirm: "이대로 그림 고르기",
  confirmHint: "누르면 초안으로 저장하고 단계마다 그림을 붙여요.",
} as const;

/** 편집기 스켈레톤(명세 3.4-A 3번): 진행 단계만, 퍼센트 숫자는 꾸며내지 않는다. */
export const editorProgress = {
  pictures: "그림을 고르고 있어요",
  voice: "목소리를 만들고 있어요",
  loading: "직무를 불러오고 있어요",
  label: "초안을 만드는 중",
} as const;

/** 그림 4상태(명세 5.5 표, contract §3.3 picture_state). ✦와 보라는 확인하지 않은 자동 결과에만. */
export const pictureStatus = {
  confirmed: "확인함",
  auto_high: "✦ 자동 · 확인 필요",
  choose: "골라 주세요",
  none: "그림 없음",
} as const;

/** 직무 편집기(명세 5.5, tasks §4.3). */
export const editor = {
  loadFailed: "직무를 불러오지 못했어요 · 다시 시도해 주세요",
  titleLabel: "직무 제목",
  titleEdit: (title: string) => `제목 고치기 · ${title}`,
  stepsHeading: "단계",
  stepsCount: (n: number) => `${n}단계`,
  /** 단계 행 번호 뒤에 화면 읽기 프로그램만 읽는 말(보이는 번호 + "단계"). */
  stepWord: "단계",
  caution: "조심",
  moveUp: (n: number) => `${n}단계 위로`,
  moveDown: (n: number) => `${n}단계 아래로`,
  grab: (n: number) => `${n}단계 순서 바꾸기`,
  grabHint: "스페이스 키로 들고 위아래 화살표 키로 옮긴 뒤 스페이스 키로 놓아요. 그만두려면 이스케이프 키를 눌러요.",
  grabbed: (n: number) => `${n}단계를 들었어요. 위아래 화살표 키로 옮기고 스페이스 키로 놓아요.`,
  movedTo: (at: number) => `${at}번째 자리예요`,
  droppedAt: (at: number) => `${at}번째 자리에 놓았어요`,
  reorderCancelled: "순서를 그대로 뒀어요",
  reorderFailed: "순서를 바꾸지 못했어요 · 다시 시도해 주세요",
  addStep: "단계 추가",
  addStepLabel: "새 단계 문장",
  addStepPlaceholder: "예: 컵을 건조대에 엎어 놓아요",
  addStepSubmit: "더하기",
  addStepFailed: "단계를 더하지 못했어요 · 다시 시도해 주세요",
  groupBreakLabel: (n: number) => `${n}단계 앞에서 묶음 나누기`,
  groupDivider: "묶음 경계",
  groupHint: "9단계가 넘으면 묶음을 나눠 두면 좋아요.",
  backToList: "단계 목록으로",
  detailHeading: (n: number) => `${n}단계 고치기`,
  pictureHeading: "그림",
  source: { auto: "✦ 자동으로 고른 그림", manual: "직접 고른 그림", photo: "현장 사진" },
  /** 확인한 자동 그림(✦는 확인하지 않은 자동 결과에만, 명세 5.10). */
  sourceConfirmedAuto: "확인한 그림",
  confirmPicture: "이 그림이 맞아요",
  confirmFailed: "그림을 확인하지 못했어요 · 잠시 뒤 다시 눌러 주세요",
  otherCandidates: "다른 후보 보기",
  chooseHeading: "맞는 그림을 골라 주세요",
  candidateNo: (n: number) => `후보 ${n}`,
  candidatesLoading: "후보를 찾고 있어요",
  candidatesFailed: "후보를 불러오지 못했어요. [다른 그림 찾기]나 [현장 사진 올리기]를 써 주세요.",
  noCandidates: "맞는 후보가 없어요. [다른 그림 찾기]나 [현장 사진 올리기]를 써 주세요.",
  useCurrent: "지금 그림 쓰기",
  findPicture: "다른 그림 찾기",
  uploadPhoto: "현장 사진 올리기",
  removePhoto: "사진 빼기",
  pictureApplied: "그림을 바꿨어요",
  pictureFailed: "그림을 바꾸지 못했어요 · 다시 시도해 주세요",
  photoRemoved: "사진을 빼고 자동 그림으로 돌렸어요",
  sentenceLabel: "문장",
  sentenceHint: "고치면 잠시 뒤 저절로 저장돼요. 칸을 벗어나면 목소리를 다시 만들어요.",
  emptySentence: "문장이 비어 있어요. 할 일을 적어 주세요.",
  originalQuote: "원래 지시문에서 온 부분",
  lintHeading: "문장 점검",
  lint: {
    too_long: "20자가 넘어요",
    hard_word: (from: string, to: string) => `어려운 말: ${from} → ${to}`,
    command_tone: "~해요 체로 바꾸기",
  },
  splitNotice: "두 단계로 나눴어요",
  undo: "되돌리기",
  undoFailed: "되돌리지 못했어요 · 다시 시도해 주세요",
  rewriting: "저장하는 중이에요",
  voice: "목소리 듣기",
  voiceStop: "멈추기",
  voiceFallback: "목소리를 만들지 못해 이 기기 음성으로 읽어요",
  cautionLabel: "조심 표시",
  cautionHint: "켜면 근로자 화면 그림 위에 '조심해요' 띠가 떠요.",
  cautionAuto: "✦ 자동 제안",
  cautionAutoHint: "칼·뜨거운·기계 같은 낱말을 보고 켰어요. 맞으면 그대로 두면 돼요.",
  cautionFailed: "조심 표시를 바꾸지 못했어요 · 다시 시도해 주세요",
  dangerZone: "위험 구역",
  deleteStep: "이 단계 지우기",
  deleteTitle: (n: number) => `${n}단계를 지울까요?`,
  deleteBody: "지운 단계는 되돌릴 수 없어요. 이미 보낸 근로자 화면은 받은 그대로예요.",
  deleteConfirm: "지우기",
  deleteFailed: "단계를 지우지 못했어요 · 다시 시도해 주세요",
  lastStep: "마지막 단계는 지울 수 없어요",
  blockedPicture: "이 단계 때문에 보내지 못했어요. 그림을 고르거나 사진을 올려 주세요.",
  blockedConfirm: "이 단계 때문에 보내지 못했어요. 그림이 맞는지 확인해 주세요.",
  overview: "그림 한눈에",
  send: "보내기",
  reload: "새로 불러오기",
} as const;

/** 확인 대기열 막대(ReviewQueueBar, 명세 5.5 머리). */
export const reviewQueue = {
  remaining: (n: number) => `확인할 것 ${n}개 남음`,
  next: "다음 ▶",
  nextLabel: "다음 확인할 단계로",
  allDone: "모두 확인했어요",
} as const;

/** 저장 표시(SaveIndicator, 명세 5.5). */
export const saveState = {
  saved: (when: string) => `저장됨 · ${when}`,
  saving: "저장하는 중…",
  failed: "저장하지 못했어요",
  retry: "다시 시도",
} as const;

/** 그림 한눈에 보기(명세 5.5 '그림 한눈에 보기'). */
export const overview = {
  title: "그림 한눈에 보기",
  hint: "틀린 그림을 누르면 그 단계로 가요. ✦ 자동 그림만 한꺼번에 확인할 수 있어요.",
  back: "편집기로 돌아가기",
  confirmAll: "보이는 자동 그림 모두 맞아요",
  waiting: "그림을 다 불러오면 누를 수 있어요",
  check: (n: number) => `${n}단계 그림이 맞아요`,
  open: (n: number) => `${n}단계 보기`,
  /** 칸 번호 뒤에 화면 읽기 프로그램만 읽는 말(보이는 번호 + "단계 보기"). */
  openWord: "단계 보기",
  broken: "그림을 못 불러왔어요",
  reloadPicture: (n: number) => `${n}단계 그림 다시 불러오기`,
  reloadShort: "다시 불러오기",
  brokenExcluded: (n: number) => `불러오지 못한 그림 ${n}장은 빼고 확인해요`,
  confirmed: (n: number) => `그림 ${n}장을 확인했어요`,
  allDone: "모두 확인했어요",
  left: (n: number) => `단계를 열어 고칠 것 ${n}개`,
} as const;

/** 그림 찾기·사진 올리기(PicturePicker, 명세 6.5 현장 사진 가이드). */
export const picker = {
  searchTitle: (n: number) => `${n}단계 그림 찾기`,
  searchLabel: "찾을 낱말",
  searchHint: "예: 컵 닦기, 상자 옮기기",
  searchSubmit: "찾기",
  searching: "그림을 찾고 있어요",
  results: (n: number) => `그림 ${n}장을 찾았어요`,
  noResults: "맞는 그림을 찾지 못했어요. 다른 낱말로 찾아 보거나 현장 사진을 올려 주세요.",
  searchFailed: "그림을 찾지 못했어요 · 다시 시도해 주세요",
  apply: (label: string) => `${label} 고르기`,
  photoTitle: (n: number) => `${n}단계 현장 사진 올리기`,
  photoTips: ["손과 물건이 크게 보이게 찍어요", "동작 하나만 찍어요", "뒤를 치워요"],
  photoFace: "얼굴이 찍히지 않게 해요. 근로자 얼굴은 올리지 않아요.",
  examplesLabel: "사진 예시",
  examples: ["좋은 예 · 손과 물건이 크게", "좋은 예 · 뒤가 깨끗해요"],
  photoPick: "사진 고르기",
  uploading: "사진을 올리고 있어요",
  uploadFailed: "사진을 올리지 못했어요 · 다시 시도해 주세요",
  uploaded: "사진을 올렸어요",
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
