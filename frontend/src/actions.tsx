/* eslint-disable react-refresh/only-export-components */
import type { ReactNode } from "react";

// 동작(action_type)을 색·아이콘·라벨로 시각화한다(기능 4).
// 같은 객체 그림(예: 상자)이라도 동작이 다르면 칩으로 구분돼 인지부하를 낮춘다.
// 결정론적(네트워크 의존 없음)이라 폴백 상징에도 항상 적용된다.
//
// 주의(Tailwind): 색 클래스는 반드시 '리터럴 문자열'로 둔다. `bg-${x}-100`처럼
// 동적으로 만들면 Tailwind가 스캔하지 못해 빌드에서 누락된다.

type ActionMeta = { label: string; chip: string; icon: ReactNode };

function svg(children: ReactNode): ReactNode {
  return (
    <svg
      viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round"
      className="h-[1.15em] w-[1.15em] shrink-0" aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const ACTION_META: Record<string, ActionMeta> = {
  observe: {
    label: "확인하기",
    chip: "bg-blue-100 text-blue-800",
    icon: svg(<><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" /></>),
  },
  move: {
    label: "옮기기",
    chip: "bg-green-100 text-green-800",
    icon: svg(<><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>),
  },
  stack: {
    label: "쌓기",
    chip: "bg-purple-100 text-purple-800",
    icon: svg(<><path d="m12 2 9 5-9 5-9-5 9-5Z" /><path d="m3 12 9 5 9-5" /><path d="m3 17 9 5 9-5" /></>),
  },
  sort: {
    label: "분류하기",
    chip: "bg-orange-100 text-orange-800",
    icon: svg(<><path d="M11 5h10" /><path d="M11 9h7" /><path d="M11 13h4" /><path d="m3 8 3-3 3 3" /><path d="M6 5v14" /></>),
  },
  // pack은 담다·포장하다·밀봉하다·접다를 묶은 계열이다(ai_service/taxonomy.py). 예전 라벨 "담기"는 그중
  // 한 동사라, 상자를 접는 단계에도 "담기"가 붙었다. 계열 이름은 묶음 전체를 가리키는 말로 둔다.
  pack: {
    label: "포장하기",
    chip: "bg-teal-100 text-teal-800",
    icon: svg(<><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z" /><path d="m3.3 7 8.7 5 8.7-5" /><path d="M12 22V12" /></>),
  },
  clean: {
    label: "청소하기",
    chip: "bg-cyan-100 text-cyan-800",
    icon: svg(<><path d="M9 4v4" /><path d="M7 6h4" /><path d="M15 10l1.6 3.4L20 15l-3.4 1.6L15 20l-1.6-3.4L10 15l3.4-1.6Z" /></>),
  },
  // 아래 셋은 분류 체계(taxonomy.py)에 있는데 여기 없어서 '작업하기'로 뭉개져 보였다.
  wear: {
    label: "착용하기",
    chip: "bg-indigo-100 text-indigo-800",
    icon: svg(<><path d="M20.4 18.6 12 14l-8.4 4.6" /><path d="M12 14V3" /><path d="m8 6 4-3 4 3" /></>),
  },
  operate: {
    label: "조작하기",
    chip: "bg-amber-100 text-amber-900",
    icon: svg(<><circle cx="12" cy="12" r="3" /><path d="M12 2v3" /><path d="M12 19v3" /><path d="M2 12h3" /><path d="M19 12h3" /></>),
  },
  assemble: {
    label: "조립하기",
    chip: "bg-rose-100 text-rose-800",
    icon: svg(<><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9l-3.8 3.8Z" /></>),
  },
  other: {
    label: "작업하기",
    chip: "bg-slate-100 text-slate-700",
    icon: svg(<><circle cx="12" cy="12" r="9" /><path d="M12 8v4l2 2" /></>),
  },
};

export function metaFor(action: string): ActionMeta {
  return ACTION_META[action] ?? ACTION_META.other;
}

export function ActionChip({ action, className = "" }: { action: string; className?: string }) {
  const m = metaFor(action);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 font-semibold ${m.chip} ${className}`}
      data-action={action}
    >
      {m.icon}
      {m.label}
    </span>
  );
}

// ---------- 근로자 화면의 동작 꼬리표 ----------
// 근로자 화면에서는 계열 이름(action_type)을 그대로 보여 주지 않는다. 계열은 여러 동사를 묶은 것이라
// ("포장" 계열 = 담다·접다·밀봉하다…) 그 이름이 문장의 동사와 다른 말이 되기 쉽다 — 상자를 접는 그림과
// "덮개를 접으세요" 문장 밑에 "담기"가 붙었다. 게다가 저장된 action_type은 틀릴 수 있다(규칙 분해가
// "-세요"의 '세'를 세다로 읽어 거의 모든 단계를 확인하기로 분류했고, 문장을 고쳐도 옛 값이 남았다).
//
// 그래서 꼬리표는 근로자가 읽는 그 문장의 서술어에서 만든다: 아래 닫힌 사전에 있는 동사로 문장이 끝날 때만
// 그 동사 그대로("접으세요" → "접기")를 아이콘·색과 함께 보여 준다. 사전에 없으면 꼬리표를 숨긴다 —
// 틀린 동작 낱말을 보여 주느니 안 보여 주는 편이 낫다.

type VerbEntry = {
  label: string;      // 꼬리표 글자(명사형) — 문장의 동사 그대로
  action: string;     // 아이콘·색을 고를 계열
  stem: string | null; // '-세요/-십시오' 앞 모양(접으-·옮기-·확인하-). 모호하면 null
  a: string[];         // '-아/-어' 모양(접어·옮겨·확인해) — "-요", 보조 용언("주세요")이 붙는다
};

const v = (label: string, action: string, stem: string | null, ...a: string[]): VerbEntry =>
  ({ label, action, stem, a });

// 현장 지시문에 흔한 동사만 둔다. 뜻이 여럿인 표면형('쓰세요' = 쓰다/쓸다)은 넣지 않는다.
const VERBS: VerbEntry[] = [
  v("접기", "pack", "접으", "접어"), v("담기", "pack", "담으", "담아"), v("넣기", "pack", "넣으", "넣어"),
  v("덮기", "pack", "덮으", "덮어"), v("포장하기", "pack", "포장하", "포장해"), v("밀봉하기", "pack", "밀봉하", "밀봉해"),
  v("놓기", "move", "놓으", "놓아", "놔"), v("두기", "move", "두", "둬", "두어"), v("옮기기", "move", "옮기", "옮겨"),
  v("꺼내기", "move", "꺼내", "꺼내"), v("가져오기", "move", "가져오", "가져와"), v("가져가기", "move", "가져가", "가져가"),
  // 내려놓기는 내리기보다 앞에 둔다 — "내려놓으세요"를 '내려'+'놓으세요'(내리기)로 읽지 않게.
  v("올리기", "move", "올리", "올려"), v("내려놓기", "move", "내려놓으", "내려놓아", "내려놔"), v("내리기", "move", "내리", "내려"), v("붓기", "move", "부으", "부어"),
  v("싣기", "move", "실으", "실어"), v("채우기", "move", "채우", "채워"), v("건네기", "move", "건네", "건네"),
  v("전달하기", "move", "전달하", "전달해"),
  v("쌓기", "stack", "쌓으", "쌓아"),
  v("분류하기", "sort", "분류하", "분류해"), v("나누기", "sort", "나누", "나눠", "나누어"),
  v("정리하기", "sort", "정리하", "정리해"), v("구분하기", "sort", "구분하", "구분해"),
  v("닦기", "clean", "닦으", "닦아"), v("씻기", "clean", "씻으", "씻어"), v("쓸기", "clean", null, "쓸어"),
  v("치우기", "clean", "치우", "치워"), v("버리기", "clean", "버리", "버려"), v("청소하기", "clean", "청소하", "청소해"),
  v("헹구기", "clean", "헹구", "헹궈"), v("소독하기", "clean", "소독하", "소독해"),
  v("확인하기", "observe", "확인하", "확인해"), v("살펴보기", "observe", "살펴보", "살펴봐"), v("보기", "observe", "보", "봐"),
  v("세기", "observe", "세", "세어"), v("읽기", "observe", "읽으", "읽어"), v("점검하기", "observe", "점검하", "점검해"),
  v("검사하기", "observe", "검사하", "검사해"),
  v("입기", "wear", "입으", "입어"), v("신기", "wear", "신으", "신어"), v("벗기", "wear", "벗으", "벗어"),
  v("끼기", "wear", "끼", "껴", "끼어"), v("착용하기", "wear", "착용하", "착용해"),
  v("누르기", "operate", "누르", "눌러"), v("켜기", "operate", "켜", "켜"), v("끄기", "operate", "끄", "꺼"),
  v("열기", "operate", "여", "열어"), v("닫기", "operate", "닫으", "닫아"), v("입력하기", "operate", "입력하", "입력해"),
  v("끼우기", "assemble", "끼우", "끼워"), v("붙이기", "assemble", "붙이", "붙여"), v("조이기", "assemble", "조이", "조여"),
  v("조립하기", "assemble", "조립하", "조립해"), v("연결하기", "assemble", "연결하", "연결해"), v("고정하기", "assemble", "고정하", "고정해"),
];

// '-어' 모양 뒤에 붙는 보조 용언("닦아 주세요"·"넣어 두세요"·"확인해 보세요"). 본동사는 앞 낱말이다.
// 가다·오다는 넣지 않는다: "내려가세요"·"들어가세요"·"내려 가세요"는 '내리다'가 아니라 따로 된 이동 동사다.
const AUX_WORDS = new Set([
  "주세요", "주십시오", "줘요", "줘", "드리세요", "드려요", "두세요", "둬요", "놓으세요", "놔요", "놓아요",
  "보세요", "봐요",
]);
const HON_ENDINGS = ["세요", "십시오", "시오", "셔요"];

// 보조 용언으로도, 본동사로도 쓰이는 말(두세요·놓으세요·보세요) 앞에 이 조사로 끝나는 낱말이 오면
// 본동사다("바닥에 두세요" → 두기, "선반을 보세요" → 보기). '이·가·와·과'는 넣지 않는다 — "들어가"처럼
// '-아/-어' 모양과 겹친다.
const PARTICLES = ["을", "를", "에", "에서", "에게", "께", "한테", "로", "으로", "은", "는", "도", "만"];
const endsWithParticle = (w: string) => w.length >= 2 && PARTICLES.some((p) => w.endsWith(p) && w.length > p.length);

function matchWord(word: string, allowFusedAux: boolean): VerbEntry | null {
  for (const e of VERBS) {
    if (e.stem && HON_ENDINGS.some((end) => word === e.stem + end)) return e;
    for (const a of e.a) {
      if (word === a || word === `${a}요`) return e;
      // "옮겨주세요"처럼 보조 용언을 붙여 쓴 경우
      if (allowFusedAux && word.startsWith(a) && AUX_WORDS.has(word.slice(a.length))) return e;
    }
    if (word === e.label) return e; // 체크리스트식 "컵에 우유 붓기"
  }
  return null;
}

// 한 문장(마침표로 끝나는 한 덩어리)의 서술어 동사. 확실하지 않으면 null.
function predicateVerb(words: string[]): VerbEntry | null {
  const last = words[words.length - 1];
  if (AUX_WORDS.has(last) && words.length >= 2) {
    const prev = words[words.length - 2];
    // "내려 놓으세요"처럼 띄어 쓴 합성 동사(내려놓다)가 사전에 따로 있으면 그것으로 읽는다.
    const joined = matchWord(prev + last, false);
    if (joined) return joined;
    const main = VERBS.find((e) => e.a.includes(prev));
    if (main) return main;
    // 앞말이 사전에 없는 '-아/-어' 모양이면("모아 두세요"·"꽂아 두세요"·"밀어 보세요") 진짜 동작은 그 앞말인데
    // 무엇인지 모른다 — 보조 용언(두기·보기)을 꼬리표로 보여 주면 틀린 말이 된다. 앞말이 조사로 끝날 때만
    // 보조 용언이 아니라 본동사로 읽는다.
    if (!endsWithParticle(prev)) return null;
    return matchWord(last, false);
  }
  return matchWord(last, true);
}

// 한글 음절 끝에 받침 ㄴ을 붙인다("접으" → "접은", "옮기" → "옮긴"). 받침이 이미 있으면 null.
function withNieun(stem: string): string | null {
  const code = stem.charCodeAt(stem.length - 1) - 0xac00;
  if (code < 0 || code > 11171 || code % 28 !== 0) return null;
  return stem.slice(0, -1) + String.fromCharCode(0xac00 + code + 4);
}

// 서술어 앞에서 다른 동작을 시키는 연결형("씻고"·"접어서"·"닦으며"·"접은 뒤")의 동사.
function connectiveVerb(word: string, next: string | undefined): VerbEntry | null {
  for (const e of VERBS) {
    const root = e.label.slice(0, -1); // 접기 → 접, 옮기기 → 옮기
    if (word === `${root}고`) return e;
    if (e.a.some((a) => word === `${a}서`)) return e;
    if (e.stem && (word === `${e.stem}며` || word === `${e.stem}면서`)) return e;
    if (e.stem && (next === "뒤" || next === "후" || next === "다음") && word === withNieun(e.stem)) return e;
  }
  return null;
}

/** 문장 서술어의 동사로 만든 꼬리표. 사전에 없는 동사로 끝나면 null(꼬리표를 보여 주지 않는다).
 *
 * 한 단계가 서로 다른 동작 둘을 시키면("손을 씻고 장갑을 끼세요"·"그릇을 씻으세요. 그 다음 헹구세요")
 * 마지막 동사 하나만 보여 주는 꼬리표는 나머지 동작을 빠뜨린 틀린 꼬리표다 — 이때도 null이다
 * (ai_service decompose._guess_action도 같은 규칙으로 other를 돌려준다). */
export function stepActionChip(sentence: string): { label: string; action: string } | null {
  const sentences = sentence.split(/[.!?。\n]+/).map((s) => s.match(/[가-힣]+/g) ?? []).filter((w) => w.length);
  if (!sentences.length) return null;
  let chosen: VerbEntry | null = null;
  for (const words of sentences) {
    const verb = predicateVerb(words);
    // 문장마다 서술어가 같은 동사여야 한다("…놓으세요. 큰 상자는 아래쪽에 … 놓으세요"는 놓기 하나).
    if (!verb || (chosen && verb.label !== chosen.label)) return null;
    chosen = verb;
    for (let i = 0; i < words.length - 1; i++) {
      const other = connectiveVerb(words[i], words[i + 1]);
      if (other && other.label !== verb.label) return null;
    }
  }
  return chosen ? { label: chosen.label, action: chosen.action } : null;
}

/** 근로자 단계 화면의 동작 꼬리표. 문장에서 동사를 확실히 못 읽으면 아무것도 그리지 않는다. */
export function WorkerActionChip({ sentence, className = "" }: { sentence: string; className?: string }) {
  const chip = stepActionChip(sentence);
  if (!chip) return null;
  const m = metaFor(chip.action);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 font-semibold ${m.chip} ${className}`}
      data-action={chip.action}
      data-testid="action-chip"
    >
      {m.icon}
      {chip.label}
    </span>
  );
}
