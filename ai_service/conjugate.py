"""표 기반 동사 활용기 — 원형 하나에서 '-고', '-아/-어(서)', '-(으)ㄴ', '-(으)세요'를 만든다.

규칙 분해기(step_split)가 "상자를 접어서 분리수거함에 넣으세요"를 두 단계로 나눌 때 앞 절의 "접어서"를
"접으세요"로 바꿔야 한다. 이 바꾸기가 틀리면 근로자가 읽는 문장이 틀린다(지난 시도: '걸어서' → '거세요',
'엎어' → '엎어를'). 그래서 원칙을 하나 둔다 — **활용이 확실하지 않으면 None을 돌려주고, 부르는 쪽은
나누지 않는다.**

확실하다는 것은:
  1) 원형이 한 어절 '…다'이고, '-ㄴ다/-는다' 평서형(쓴다·노크한다)이 아니다.
  2) 받침 ㄷ·ㅂ·ㅅ, 끝 음절 '르', 받침 ㅎ처럼 같은 겉모양에 규칙·불규칙이 섞이는 어간은 아래 표에
     어느 쪽인지 적혀 있어야 한다. 표에 없거나 뜻에 따라 활용이 갈리는 어간(걷다: 걸어/걷어,
     묻다: 물어/묻어, 이르다, 푸다)은 None.
  3) 받침 없는 어간은 모음별 축약 규칙(가→가, 보→봐, 주→줘, 내리→내려, 쓰→써, 되→돼 …)이 표에 있는
     모음만 받는다. 표에 없는 모음(ㅑ·ㅛ·ㅠ·ㅘ·ㅝ …)은 None.
  4) ㄹ 어간의 지시형이 ㄹ 탈락으로 다른 흔한 동사의 지시형과 같아지면(갈다→가세요, 쓸다→쓰세요, 들다→드세요)
     Forms.polite만 None으로 둔다 — 문법은 맞아도 읽는 사람은 다른 동작으로 읽는다.
  5) 두 동사가 나눠 쓰는 '-아/-어' 겉모양(걸어: 걷다/걸다, 들어: 듣다/들다 …)은 HOMOGRAPH_A_FORMS에 적어 두고,
     부르는 쪽이 is_homograph_a_form으로 걸러 나누지 않는다.

거꾸로(활용형 → 원형)는 이 모듈이 하지 않는다. 부르는 쪽이 사전 분석기(korean_verbs.Analyzer)로
후보 원형을 얻고, 이 모듈로 다시 만들어 겉모양이 똑같은지 확인한다(round trip). 후보가 둘 이상이면
(들어서: 듣다/들다) 확실하지 않은 것이다.
"""
from __future__ import annotations

from dataclasses import dataclass

from korean_verbs import _join, _split, is_conjugated_form, is_plain_lemma

# 종성 번호
_F_NONE, _F_N, _F_D, _F_L, _F_B, _F_S, _F_H = 0, 4, 7, 8, 17, 19, 27
# 중성 번호
_A, _AE, _YA, _EO, _E, _YEO, _O, _WA, _WAE, _OE, _U, _WEO, _WI, _EU, _UI, _I = (
    0, 1, 2, 4, 5, 6, 8, 9, 10, 11, 13, 14, 16, 18, 19, 20)

# ---- 받침 ㄷ·ㅂ·ㅅ: 끝 음절별로 규칙/불규칙을 적는다 ----------------------------------------
_D_IRREGULAR = frozenset({"싣", "듣"})                               # 실어 / 실은 / 실으세요
_D_REGULAR = frozenset({"닫", "받", "뜯", "쏟", "얻", "믿", "돋"})   # 닫아 / 닫은 / 닫으세요
_B_IRREGULAR = {"줍": "주워", "굽": "구워", "눕": "누워", "돕": "도와"}  # 주워 / 주운 / 주우세요
_B_REGULAR = frozenset({"잡", "접", "집", "입", "뽑", "씹", "업", "꼽"})  # 잡아 / 잡은 / 잡으세요
_S_IRREGULAR = frozenset({"붓", "젓", "긋", "잇"})                   # 부어 / 부은 / 부으세요
_S_REGULAR = frozenset({"씻", "벗", "빗", "솟"})                     # 씻어 / 씻은 / 씻으세요
# 뜻에 따라 활용이 갈리는 어간. 굽다는 위에서 불규칙(구워)으로 적었다 — 일터 지시문의 '굽다'는 굽기다.
# '굽어서'처럼 규칙형으로 나오면 부르는 쪽의 겉모양 대조(round trip)에서 걸러진다.
_AMBIGUOUS_STEMS = frozenset({"걷", "묻", "이르", "푸"})

# ---- 끝 음절 '르' ------------------------------------------------------------------------
# 르 불규칙: 누르→눌러, 자르→잘라 (앞 음절에 ㄹ 받침이 붙는다)
_REU_IRREGULAR = frozenset({
    "누르", "고르", "자르", "바르", "부르", "기르", "오르", "흐르", "마르", "나르", "모르", "가르",
    "두르", "지르", "문지르", "거르", "찌르", "휘두르", "서두르", "구르", "추스르",
})
# 으 탈락: 따르→따라, 치르→치러, 들르→들러
_REU_EU_DROP = frozenset({"따르", "치르", "들르"})

# ---- 받침 ㅎ: 동사는 규칙(놓아·넣어·쌓아). 형용사(그렇다·하얗다)는 불규칙이라 목록에 든 것만 받는다.
_H_REGULAR_SYLLABLES = frozenset({"놓", "넣", "쌓", "낳", "닿", "찧", "빻", "땋"})

# ---- 받침 ㄴ: '-ㄴ다' 평서형과 겉모양이 같아(쓴다·노크한다) 실제 원형만 목록으로 받는다.
_N_FINAL_LEMMAS = frozenset({"신다", "안다", "껴안다"})

# ---- 받침 ㄹ: '-(으)세요'에서 ㄹ이 떨어지면(갈다 → 가세요) 받침 없는 다른 동사의 지시형과 글자가 같아진다.
# 문법은 맞아도 읽는 사람은 다른 동작으로 읽는다("바닥을 쓰세요" — 쓸다인데 쓰다로 읽힌다). 떨어진 어간이
# 아래 흔한 동사(가다·사다·쓰다·끄다·까다·파다·푸다·자다·차다·타다·나다)이거나 '드'(드시다: 들다 → 드세요는
# '드세요(잡수세요)'로 읽힌다)면 지시형을 확실하지 않은 것으로 본다(Forms.polite = None). 다른 활용형(쓸어·쓸고)은
# 겉모양이 겹치지 않아 그대로 낸다 — 원문 그대로 두는 뒤 절의 동사로는 쓸 수 있다.
_RIEUL_POLITE_CLASH = frozenset({"가", "사", "쓰", "끄", "까", "파", "푸", "자", "차", "타", "나", "드"})

# ---- 같은 '-아/-어' 겉모양을 두 동사가 나눠 쓰는 꼴(ㄷ·ㅅ 불규칙과 ㄹ 어간이 겹친다).
# "걸어서"는 걷다(걸어)와 걸다(걸어) 둘 다다. 이 겉모양으로 끝나는 연결형은 원형을 하나로 정할 수 없어
# 부르는 쪽이 나누지 않는다(지난 시도: '계단으로 걸어서 올라가요' → '계단으로 거세요').
HOMOGRAPH_A_FORMS: dict[str, frozenset[str]] = {
    "걸어": frozenset({"걷다", "걸다"}),
    "물어": frozenset({"묻다", "물다"}),
    "들어": frozenset({"듣다", "들다"}),
    "불어": frozenset({"붇다", "불다"}),
    "이어": frozenset({"잇다", "이다"}),
}


@dataclass(frozen=True)
class Forms:
    lemma: str
    go: str                    # 연결형 '-고'          닦고·열고
    a: tuple[str, ...]         # '-아/-어' 몸통        닦아·놔/놓아·줘/주어
    adnominal: str             # 과거 관형형 '-(으)ㄴ'  닦은·연·실은·주운
    polite: str | None         # 지시형 '-(으)세요'   닦으세요·여세요·실으세요·주우세요 (None: 다른 동사와 겹침)

    def seo(self) -> tuple[str, ...]:
        """'-아서/-어서' 연결형."""
        return tuple(a + "서" for a in self.a)


def conjugate(lemma: str) -> Forms | None:
    """원형의 활용형 표. 확실하지 않으면 None(모듈 설명)."""
    if not is_plain_lemma(lemma):
        return None
    if is_conjugated_form(lemma) and lemma not in _N_FINAL_LEMMAS:
        return None
    stem = lemma[:-1]
    last = stem[-1]
    head = stem[:-1]
    parts = _split(last)
    if parts is None:
        return None
    i, m, f = parts
    if last in _AMBIGUOUS_STEMS or stem in _AMBIGUOUS_STEMS:
        return None
    go = stem + "고"

    if last == "하":
        return Forms(lemma, go, (head + "해", head + "하여"), head + "한", stem + "세요")

    if f == _F_NONE:
        if last == "르" and head:
            return _reu(lemma, stem, go)
        a = _vowel_a_forms(stem, i, m)
        if a is None:
            return None
        return Forms(lemma, go, a, head + _join(i, m, _F_N), stem + "세요")

    if f == _F_L:
        # ㄹ 탈락: 열다 → 여세요·연, 만들다 → 만드세요·만든. '-아/-어'는 받침을 살린다(열어).
        dropped = head + _join(i, m)
        polite = None if dropped in _RIEUL_POLITE_CLASH else dropped + "세요"
        return Forms(lemma, go, (stem + _eo(m),), head + _join(i, m, _F_N), polite)

    if f == _F_D:
        if last in _D_IRREGULAR:
            l_stem = head + _join(i, m, _F_L)
            return Forms(lemma, go, (l_stem + _eo(m),), l_stem + "은", l_stem + "으세요")
        if last not in _D_REGULAR:
            return None
    elif f == _F_B:
        if last in _B_IRREGULAR:
            open_stem = head + _join(i, m)
            return Forms(lemma, go, (head + _B_IRREGULAR[last],), open_stem + "운", open_stem + "우세요")
        if last not in _B_REGULAR:
            return None
    elif f == _F_S:
        if last in _S_IRREGULAR:
            open_stem = head + _join(i, m)
            return Forms(lemma, go, (open_stem + _eo(m),), open_stem + "은", open_stem + "으세요")
        if last not in _S_REGULAR:
            return None
    elif f == _F_H:
        if last not in _H_REGULAR_SYLLABLES:
            return None
        a = (stem + _eo(m),)
        if m == _O:  # 놓아 → 놔
            a = (head + _join(i, _WA), stem + "아")
        return Forms(lemma, go, a, stem + "은", stem + "으세요")

    # 그 밖의 받침(닦·찍·읽·앉·끓 …)은 모두 규칙 활용이다.
    return Forms(lemma, go, (stem + _eo(m),), stem + "은", stem + "으세요")


def is_homograph_a_form(body: str) -> bool:
    """'-아/-어' 몸통(연결 어미 '-서' 앞)이 두 동사가 나눠 쓰는 겉모양으로 끝나는가."""
    return any(body.endswith(form) for form in HOMOGRAPH_A_FORMS)


def _eo(m: int) -> str:
    """양성 모음(ㅏ·ㅗ·ㅑ) 뒤는 '아', 나머지는 '어'."""
    return "아" if m in (_A, _O, _YA) else "어"


def _vowel_a_forms(stem: str, i: int, m: int) -> tuple[str, ...] | None:
    head = stem[:-1]
    if m in (_A, _EO, _YEO):          # 가→가, 서→서, 켜→켜
        return (stem,)
    if m in (_AE, _E):                # 꺼내→꺼내/꺼내어, 세→세/세어
        return (stem, stem + "어")
    if m == _O:
        if stem.endswith("오"):       # '오다'와 그 합성어(가져오다·나오다)는 '와'만 쓴다
            return (head + "와",)
        return (head + _join(i, _WA), stem + "아")   # 보→봐/보아
    if m == _U:                       # 주→줘/주어, 채우→채워
        return (head + _join(i, _WEO), stem + "어")
    if m == _I:                       # 내리→내려/내리어, 붙이→붙여/붙이어
        if not head and i == 7:       # 한 음절 '비-'는 줄이지 않는다(비어, *벼)
            return (stem + "어",)
        return (head + _join(i, _YEO), stem + "어")
    if m == _OE:                      # 되→돼/되어
        return (head + _join(i, _WAE), stem + "어")
    if m in (_WI, _UI):               # 쉬→쉬어, 띄→띄어
        return (stem + "어",)
    if m == _EU:                      # 으 탈락: 쓰→써, 끄→꺼, 모으→모아, 잠그→잠가
        prev = _split(head[-1]) if head else None
        yang = prev is not None and prev[1] in (_A, _O, _YA)
        return (head + _join(i, _A if yang else _EO),)
    return None


def _reu(lemma: str, stem: str, go: str) -> Forms | None:
    head = stem[:-1]  # '르' 앞
    prev = _split(head[-1])
    if prev is None:
        return None
    pi, pm, pf = prev
    adn = head + "른"                 # 누른·고른·따른
    polite = stem + "세요"
    ending = "라" if pm in (_A, _O, _YA) else "러"
    if stem in _REU_EU_DROP:
        return Forms(lemma, go, (head + ending,), adn, polite)
    if stem in _REU_IRREGULAR and pf == _F_NONE:
        return Forms(lemma, go, (head[:-1] + _join(pi, pm, _F_L) + ending,), adn, polite)
    return None
