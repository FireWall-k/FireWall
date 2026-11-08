// 근로자 화면 문구 사전(명세 4.14 + 4.5·4.9 표). 근로자 화면의 글자는 모두 여기서 꺼내 쓴다.
// 규칙(명세 6.7): '~해요' 체, 한 문장에 동작 하나, 쉬운 말. 사업주는 근로자에게 '선생님'이다(창업자 결정 1).
// 금지: 영어, '사업주'·'사업장 코드'·'접속 코드'·'로그아웃', '오류'·'실패'·'에러', '1 / 4' 같은 분수,
// '~합니다'·'~하세요'. tests/copy.test.ts가 아래 FORBIDDEN_PATTERNS로 모든 문구를 검사하고,
// e2e도 같은 목록으로 실제 화면 글자를 검사한다.
// api.ts가 아니라 apiErrors.ts에서 가져온다: 화면 테스트가 "../src/api"를 통째로 목으로 바꿔도 오류 판정은 살아 있게.
import { ApiError, AuthError, NetworkError } from "../apiErrors";

type JosaPair = "을/를" | "이/가" | "은/는" | "과/와" | "으로/로";

// 숫자로 끝나는 낱말의 받침(0 영, 1 일, 3 삼, 6 육, 7 칠, 8 팔 → 받침 있음).
const DIGIT_HAS_FINAL: Record<string, boolean> = {
  "0": true, "1": true, "2": false, "3": true, "4": false,
  "5": false, "6": true, "7": true, "8": true, "9": false,
};

/** 마지막 글자의 받침 종류. null = 받침 없음, "ㄹ" = ㄹ 받침, "other" = 그 밖의 받침. */
function finalConsonant(word: string): null | "ㄹ" | "other" {
  const trimmed = word.trim().replace(/[\s)\]}"'’”.!?…]+$/u, "");
  const last = trimmed.slice(-1);
  if (!last) return null;
  const code = last.charCodeAt(0);
  if (code >= 0xac00 && code <= 0xd7a3) {
    const jong = (code - 0xac00) % 28;
    if (jong === 0) return null;
    return jong === 8 ? "ㄹ" : "other";
  }
  if (last in DIGIT_HAS_FINAL) {
    if (!DIGIT_HAS_FINAL[last]) return null;
    // 1(일)·7(칠)·8(팔)은 ㄹ 받침.
    return last === "1" || last === "7" || last === "8" ? "ㄹ" : "other";
  }
  return null;
}

/** 받침에 맞는 조사를 붙인다. josa("컵 씻기", "을/를") → "컵 씻기를". */
export function josa(word: string, pair: JosaPair): string {
  const fc = finalConsonant(word);
  const [withFinal, withoutFinal] = pair.split("/");
  if (pair === "으로/로") return word + (fc === null || fc === "ㄹ" ? "로" : "으로");
  return word + (fc === null ? withoutFinal : withFinal);
}

const WEEKDAYS = ["일요일", "월요일", "화요일", "수요일", "목요일", "금요일", "토요일"];

export const COPY = {
  btn: {
    enter: "들어가기",
    start: "시작하기",
    resume: "이어서 하기",
    done: "다 했어요",
    nextJob: "다음 일 하기",
    continue: "계속하기",
    retry: "다시 해 보기",
    refresh: "새로 보기",
    reenter: "번호 다시 넣기",
    prev: "이전",
    next: "다음",
    exit: "나가기",
    listen: "듣기",
    stop: "멈춤",
    help: "도와주세요",
    cancel: "취소",
    recall: "다시 부르기",
    end: "끝내기",
    history: "했던 일 보기",
    home: "홈으로",
    restart: "처음부터 하기",
    replayJob: "방금 일 다시 보기",
    retryPicture: "다시 보기",
    teacherSetup: "선생님용: 기기 연결하기",
    teacherLongCode: "선생님용: 긴 번호로 들어가기",
  },
  key: {
    backspace: "지우기",
    clear: "비우기",
  },
  login: {
    title: "내 번호를 눌러요",
    wrong: "번호가 맞지 않아요. 다시 눌러 봐요.",
    askTeacher: "선생님께 번호를 물어봐요.",
    entering: "들어가는 중이에요",
    // 사전(4.14) 밖에서 더한 문구: 시도가 너무 많아 서버가 잠시 막았을 때(429).
    tooMany: "잠깐 쉬었다가 다시 눌러 봐요. 선생님께 말해 주세요.",
  },
  help: {
    sending: "선생님을 부르는 중이에요",
    btnSending: "부르는 중",
    sent: "선생님을 불렀어요. 여기서 기다려요.",
    btnSent: "불렀어요",
    failed: "아직 못 불렀어요. 손을 들어 선생님을 불러요.",
    acked: "선생님이 확인했어요",
  },
  status: {
    loading: { title: "일을 가져오고 있어요", slow: "조금 오래 걸려요. 기다려 주세요." },
    empty: { title: "아직 받은 일이 없어요", body: "선생님이 일을 보내면 여기에 나와요." },
    offline: { title: "인터넷이 안 돼요", body: "와이파이를 확인해 주세요.", cached: "받아 둔 일은 할 수 있어요." },
    error: { title: "잠깐 문제가 생겼어요", body: "조금 뒤에 다시 해 봐요." },
    expired: { title: "다시 들어와 주세요" },
    unpaired: { title: "이 기기를 아직 연결하지 않았어요", body: "선생님께 말해 주세요." },
  },
  band: {
    offline: "인터넷이 끊겼어요. 일은 계속해도 돼요.",
    offlineShort: "인터넷 끊김",
    // 좁은 휴대폰의 위 띠 가운데(도움 띠가 떠 있을 때). 아이콘 아래 두 글자.
    offlineTiny: "끊김",
    synced: "기록을 다 보냈어요",
    newJob: "새 일이 왔어요",
  },
  home: {
    greeting: (name: string) => `${name} 님, 안녕하세요`,
    todayCount: (n: number) => `오늘 할 일 ${n}개`,
  },
  card: {
    new: "새 일",
    done: "다 했어요",
    resume: (n: number) => `${n}단계부터 이어서 해요`,
    stopped: "하다가 멈췄어요",
  },
  start: {
    title: (t: string) => `${josa(t, "을/를")} 시작해요`,
    stepCount: (n: number) => `${n}단계예요`,
  },
  step: {
    praise: "잘했어요",
    tapToListen: "눌러서 들어요",
    caution: "조심해요",
    /** 화면 읽기 프로그램 전용(화면에는 숫자를 보이지 않는다). */
    srProgress: (i: number, n: number) => `${n}단계 중 ${i}단계`,
  },
  picture: {
    failed: "그림을 못 불러왔어요",
  },
  done: {
    title: (t: string) => `${josa(t, "을/를")} 다 했어요`,
    praise: "정말 잘했어요",
    nextPreview: (t: string) => `다음 일: ${t}`,
  },
  allDone: {
    title: "오늘 일을 다 했어요",
    body: "선생님께 알려 주세요.",
  },
  confirm: {
    exit: { title: "일을 멈출까요?", body: "나중에 이어서 할 수 있어요.", stay: "계속할래요", leave: "멈출래요" },
    end: { title: "오늘 일을 끝낼까요?", stay: "아니요, 계속할래요", leave: "네, 끝낼래요" },
    // 끝내기 전에 못 보낸 기록이 남아 있고 인터넷이 끊겼을 때(2차 검증).
    unsent: "아직 못 보낸 기록이 있어요. 인터넷이 되면 다시 들어와요.",
  },
  history: {
    today: "오늘",
    yesterday: "어제",
    empty: "아직 했던 일이 없어요",
    /** "11월 6일 목요일". */
    date: (d: Date) => `${d.getMonth() + 1}월 ${d.getDate()}일 ${WEEKDAYS[d.getDay()]}`,
  },
} as const;

/**
 * 근로자 화면에 나오면 안 되는 글자(명세 4.14). copy.test.ts와 e2e가 함께 쓴다.
 * 근로자 이름·직무 이름처럼 사업주가 넣은 글자는 이 검사 대상이 아니다(문구 사전만 검사).
 */
export const FORBIDDEN_PATTERNS: RegExp[] = [
  /[A-Za-z]/,
  /JOB CARD/i,
  /사업주/,
  /사업장 코드/,
  /접속 코드/,
  /로그아웃/,
  /오류/,
  /실패/,
  /에러/,
  /\d+\s*\/\s*\d+/,
  /합니다/,
  // "안녕하세요"(인사)는 허용한다. 지시하는 "~하세요" 체만 막는다.
  /(?<!안녕)하세요/,
];

/** 근로자 화면 오류 종류. 화면(StatusScreen·띠·키패드 문구)은 이 값으로만 고른다 — 서버 detail은 보이지 않는다. */
export type WorkerErrorKind = "offline" | "error" | "expired" | "wrong_code" | "too_many" | "gone";

/**
 * 오류를 근로자 화면 종류로 바꾼다(명세 4.9). 영어 원문("Failed to fetch")이나 서버 문장
 * ('접속 코드' 같은 금지어가 섞임)을 그대로 돌려주지 않는다.
 * - 네트워크 끊김(NetworkError, fetch의 TypeError) → offline
 * - 로그인 외 401(AuthError) → expired, 로그인 요청의 401(ApiError 401) → wrong_code
 * - 429 → too_many, 404·400 → gone(지워졌거나 맞지 않는 배정), 그 밖(5xx·모름) → error
 */
export function toWorkerMessage(err: unknown): WorkerErrorKind {
  if (err instanceof NetworkError || err instanceof TypeError) return "offline";
  if (err instanceof AuthError) return "expired";
  if (err instanceof ApiError) {
    if (err.status === 401) return "wrong_code";
    if (err.status === 429) return "too_many";
    if (err.status === 404 || err.status === 400) return "gone";
    return "error";
  }
  return "error";
}
