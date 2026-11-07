"""규칙 기반 한국어 동사 활용 분석 — 지시문에서 '해야 할 동작'의 원형을 뽑는다.

왜 형태소 분석기(kiwipiepy 등)가 아니라 규칙인가:
  - 배포 이미지 크기와 결정성. 사전·모델 파일이 붙는 분석기는 수십 MB를 더하고 버전에
    따라 결과가 바뀐다. 우리가 알아야 하는 동사는 그림 인덱스에 있는 600여 개뿐이다.
  - 그래서 '닫힌 사전 + 활용 규칙'으로 푼다. 사전은 호출하는 쪽(local_aac)이 넘긴다.

예전 방식(어간 표면형이 어절 앞부분과 같으면 그 동사로 본다)의 실측 실패(개발셋 180문장):
  - "주세요"·"두세요"·"오세요" 같은 보조 용언이 본동사 자리를 차지했다(14문장이 '주다'만 나옴).
  - "드려요"가 ㄹ탈락형 '드'(들다)로, "들어온"·"들어가면"이 '들다'로, "떨어진"이 '떨다'로,
    "가지런히"가 '가지다'로, "가벼운"이 '가다'로 잡혔다 — 어간 뒤에 무엇이 붙었는지를 안 봤다.
  - 한 글자 어간은 어미가 두 글자 이상일 때만 인정해서 "찍어"·"꺼내 오세요"를 놓쳤다.
  - 25문장은 원형이 0개였다(모아요·문질러요·실어·둘러요 — 모음 축약·르 불규칙을 몰랐다).
    이 모듈로 바꾼 뒤(개발셋 기준) '주다'만 나오는 문장 1('드려요' — 실제로 건네는 동작),
    원형 0개 문장 1('말씀드리세요' — 사전 밖 동사).

이 모듈은 어간 뒤에 남은 부분이 '실제 어미'인지 확인한다. 어미가 아니면 그 어절은 동사가
아니다(명사·부사). 그리고 어미의 종류로 절의 역할을 가른다:
  - FINAL  문장 끝 서술어(-세요/-어요/-ㅂ니다/-ㄴ다) — 지시하는 동작
  - CONN   이어지는 동작(-고/-어서/-면서/-어) — 순서대로 할 동작이라 함께 센다
  - COND   조건·이유(-면/-니까) — "손님이 찾으면"의 '찾다'는 할 일이 아니다
  - EXCL   꾸미는 말·명사형·부사형(-ㄴ/-는/-던/-기/-게/과거형) — "다 붙인 박스"의 '붙이다'
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")

FINAL = "final"
CONN = "conn"
BARE = "bare"   # 어미 없이 '-아/-어'로만 끝난 어절("꺼내 오세요"의 '꺼내'). 다음 어절이 보조 용언일 수 있다.
COND = "cond"
EXCL = "excl"

# 할 일로 세는 종류. 조건절·관형절의 동사는 그림의 동작이 아니라 상황 설명이다.
MAIN_KINDS = frozenset({FINAL, CONN, BARE})

# ---- 한글 자모 ------------------------------------------------------------------
_BASE = 0xAC00
_LAST = 0xD7A3
# 중성 번호(ㅏ=0 … ㅣ=20)
_A, _AE, _YA, _EO, _E, _YEO, _O, _WA, _WAE, _OE, _U, _WEO, _EU, _I = (
    0, 1, 2, 4, 5, 6, 8, 9, 10, 11, 13, 14, 18, 20)
# 종성 번호(없음=0 … ㅎ=27)
_F_NONE, _F_N, _F_D, _F_L, _F_B, _F_S, _F_SS, _F_H = 0, 4, 7, 8, 17, 19, 20, 27


def _split(ch: str) -> tuple[int, int, int] | None:
    code = ord(ch)
    if not (_BASE <= code <= _LAST):
        return None
    idx = code - _BASE
    return idx // 588, (idx % 588) // 28, idx % 28


def _join(i: int, m: int, f: int = 0) -> str:
    return chr(_BASE + i * 588 + m * 28 + f)


def _with_final(ch: str, f: int) -> str | None:
    parts = _split(ch)
    if parts is None or parts[2] != _F_NONE:
        return None
    return _join(parts[0], parts[1], f)


def _drop_final(ch: str) -> str:
    i, m, _ = _split(ch)  # type: ignore[misc]
    return _join(i, m, 0)


def _is_yang(ch: str) -> bool:
    """양성 모음(ㅏ·ㅗ)이면 '-아', 아니면 '-어'가 붙는다."""
    parts = _split(ch)
    return parts is not None and parts[1] in (_A, _O, _YA)  # ㅑ도 양성


# ---- 불규칙 활용 ------------------------------------------------------------------
# 받침 ㄷ·ㅂ·ㅅ 불규칙은 같은 받침의 규칙 동사(닫다·잡다·씻다)와 겉모양으로 구별할 수 없어
# 목록으로 둔다. 규칙형도 함께 만들어 두므로(과생성) 목록이 틀려도 잃는 것은 없다.
# 끝 음절로 본다('깨닫다'의 '닫'처럼 규칙 동사와 겹치는 것은 넣지 않는다).
_D_IRREGULAR = frozenset({"싣", "듣", "걷", "묻"})              # 실어·들어·걸어
_B_IRREGULAR = frozenset({"줍", "굽", "눕", "돕"})              # 주워·구워·누워·도와
_S_IRREGULAR = frozenset({"붓", "젓", "잇"})                    # 부어·저어·이어


def a_forms(stem: str) -> set[str]:
    """'-아/-어' 활용형(해요체·연결형의 몸통). 닦→닦아, 꺼내→꺼내, 채우→채워, 쓰→써."""
    out: set[str] = set()
    if not stem:
        return out
    last = stem[-1]
    head = stem[:-1]
    parts = _split(last)
    if parts is None:
        return out
    i, m, f = parts
    if last == "하":
        return {head + "해", head + "하여"}
    if f != _F_NONE:
        yang = m in (_A, _O, _YA)
        out.add(stem + ("아" if yang else "어"))
        if f == _F_D and last in _D_IRREGULAR:
            out.add(head + _join(i, m, _F_L) + ("아" if yang else "어"))
        if f == _F_B and last in _B_IRREGULAR:
            out.add(head + _join(i, m) + ("와" if last == "돕" else "워"))
        if f == _F_S and last in _S_IRREGULAR:
            out.add(head + _join(i, m) + ("아" if yang else "어"))
        if f == _F_H:  # 놓아 → 놔
            out.add(head + _join(i, _WA if m == _O else m))
        return out
    # 받침 없는 어간
    if last == "르" and head:
        # 르 불규칙: 문지르→문질러, 자르→잘라, 누르→눌러. '따르→따라'(으 탈락)도 함께 만든다.
        prev = head[-1]
        yang = _is_yang(prev)
        with_l = _with_final(prev, _F_L)
        if with_l:
            out.add(head[:-1] + with_l + ("라" if yang else "러"))
        out.add(head + ("라" if yang else "러"))
        return out
    if m == _EU:
        # 으 탈락: 쓰→써, 끄→꺼, 모으→모아, 잠그→잠가. 앞 음절 모음이 양성이면 '-아'.
        yang = bool(head) and _is_yang(head[-1])
        out.add(head + _join(i, _A if yang else _EO))
        return out
    if m == _I:
        out.add(head + _join(i, _YEO))   # 내리→내려, 붙이→붙여, 드리→드려
        out.add(stem + "어")
        return out
    if m == _U:
        out.add(head + _join(i, _WEO))   # 주→줘, 채우→채워
        out.add(stem + "어")
        return out
    if m == _O:
        out.add(head + _join(i, _WA))    # 보→봐, 오→와
        out.add(stem + "아")
        return out
    if m == _OE:
        out.add(head + _join(i, _WAE))   # 되→돼
        out.add(stem + "어")
        return out
    if m in (_A, _EO, _YEO):
        out.add(stem)                    # 가→가, 서→서, 켜→켜
        return out
    if m in (_AE, _E):
        out.add(stem)                    # 꺼내→꺼내, 세→세
        out.add(stem + "어")
        return out
    out.add(stem + "어")
    return out


# ---- 어미 표 ---------------------------------------------------------------------
# 어간(받침 그대로) 뒤
_END_STEM = {
    "다": FINAL, "고": CONN, "고요": FINAL, "지": CONN, "지요": FINAL, "죠": FINAL,
    "자": FINAL, "네요": FINAL, "거나": CONN, "다가": CONN, "더니": CONN,
    "게": EXCL, "기": EXCL, "던": EXCL, "도록": EXCL, "든지": EXCL, "거든": COND,
}
# 받침 있는 어간(ㄹ 제외) 뒤
_END_CONS = {"는": EXCL, "는다": FINAL, "는지": EXCL, "는데": CONN, "습니다": FINAL, "습니까": FINAL}
# 받침 없는 어간·ㄹ탈락 어간 뒤
_END_OPEN = {"는": EXCL, "는지": EXCL, "는데": CONN}
# 매개모음까지 붙은 어간(닦으-, 여-, 쓰-) 뒤: 높임 '-시-'
_END_HON = {
    "세요": FINAL, "셔요": FINAL, "십시오": FINAL, "시오": FINAL, "세": FINAL, "시죠": FINAL,
    "시지요": FINAL, "십니다": FINAL, "시고": CONN, "시며": CONN, "시면서": CONN, "셔서": CONN,
    "시면": COND, "시는": EXCL, "신": EXCL, "실": EXCL, "시던": EXCL, "시게": EXCL, "시기": EXCL,
}
# 매개모음 어간 뒤(ㄹ탈락형 제외 — ㄹ 어간은 '열면'처럼 받침을 살린다)
_END_LINK = {"면": COND, "며": CONN, "면서": CONN, "려고": EXCL, "러": EXCL, "려면": COND,
             "니까": COND, "니": COND}
# ㄹ 어간 원형 뒤(열면·열며·열려고)
# '열세요'·'만들세요'는 규범형(여세요·만드세요)은 아니지만 실제로 많이 쓴다.
_END_RIEUL = {"면": COND, "며": CONN, "면서": CONN, "려고": EXCL, "러": EXCL, "려면": COND,
              "세요": FINAL, "으세요": FINAL}
# 매개모음 어간의 끝 음절에 받침이 녹아든 꼴(간·쓴·닦은 / 갈·쓸·닦을 / 갑니다·씁니다)
_END_FUSED_N = {"": EXCL, "다": FINAL, "지": EXCL, "데": CONN, "다고": EXCL}
_END_FUSED_L = {"": EXCL, "게요": FINAL, "께요": FINAL, "래요": FINAL, "까요": FINAL, "때": EXCL, "수": EXCL}
_END_FUSED_B = {"니다": FINAL, "시다": FINAL, "니까": FINAL}
# '-아/-어' 활용형 뒤
_END_A = {"": BARE, "요": FINAL, "서": CONN, "서요": FINAL, "도": CONN, "야": CONN, "라": FINAL,
          "다": CONN, "다가": CONN}
# 과거형(-었/-았). 지시문의 할 일이 아니라 이미 일어난 일이다("다 썼으면", "떨어졌으면").
_END_PAST = {"어요": EXCL, "어": EXCL, "다": EXCL, "고": EXCL, "으면": EXCL, "으니": EXCL,
             "는데": EXCL, "던": EXCL, "을": EXCL, "습니다": EXCL, "는지": EXCL, "어서": EXCL}

# 앞 동사의 원형만 남기고 자신은 버리는 보조 용언(-어 주다/드리다/두다/놓다/오다/가다/보다/내다).
# "꺼내 오세요"의 할 일은 '꺼내다'고, "닦아 주세요"의 '주다'는 공손함일 뿐이다.
# '-어 버리다'는 넣지 않는다 — "털어 버리세요"처럼 실제로 버리는 동작인 경우가 많다.
# '-어 있다'(비어 있는·접혀 있는)는 상태 지속이라 본동사가 '있다'의 어미를 따른다.
AUXILIARIES = frozenset({"주다", "드리다", "두다", "놓다", "오다", "가다", "보다", "내다", "있다"})
# '-어 지다'(떨어지다·흩어지다·쏟아지다)는 상태 변화라 지시 동작이 아니다.
_PASSIVE_AUX = "지다"


@dataclass(frozen=True)
class Parse:
    lemma: str
    kind: str
    aux: str | None = None   # 같은 어절 안에서 떼어 낸 보조 용언(있으면)


class Analyzer:
    """닫힌 동사 사전 하나로 어절을 분석한다."""

    def __init__(self, lemmas: set[str] | frozenset[str], *, generic_hada: bool = True,
                 rieul_drop_exclude: frozenset[str] = frozenset()) -> None:
        """rieul_drop_exclude: ㄹ탈락형(갈다→가-)을 만들지 않을 원형. 탈락형이 더 흔한 다른
        동사의 어간과 같은 글자가 되는 경우에 쓴다(호출하는 쪽 주석 참고)."""
        self._generic_hada = generic_hada
        # 보조 용언은 사전에 늘 넣는다 — 모르면 "드려요"가 ㄹ탈락형 '드'(들다)로 잘못 잡힌다.
        self.lemmas = frozenset(
            w for w in set(lemmas) | AUXILIARIES | {_PASSIVE_AUX} if is_plain_lemma(w)
        )
        forms: dict[str, list[tuple[str, dict]]] = {}

        def add(surface: str, lemma: str, table: dict) -> None:
            if surface:
                forms.setdefault(surface, []).append((lemma, table))

        for lemma in self.lemmas:
            stem = lemma[:-1]
            last = _split(stem[-1])
            if last is None:
                continue
            final = last[2]
            add(stem, lemma, _END_STEM)
            if final == _F_L:
                add(stem, lemma, _END_RIEUL)
                if lemma in rieul_drop_exclude:
                    links = []
                else:
                    dropped = stem[:-1] + _drop_final(stem[-1])
                    add(dropped, lemma, _END_OPEN)
                    add(dropped, lemma, _END_HON)
                    links = [dropped]
            elif final == _F_NONE:
                add(stem, lemma, _END_OPEN)
                add(stem, lemma, _END_HON)
                add(stem, lemma, _END_LINK)
                links = [stem]
            else:
                add(stem, lemma, _END_CONS)
                links = [stem + "으"]
                head = stem[:-1]
                i, m, _ = last
                if final == _F_D and stem[-1] in _D_IRREGULAR:
                    links.append(head + _join(i, m, _F_L) + "으")
                if final == _F_B and stem[-1] in _B_IRREGULAR:
                    links.append(head + _join(i, m) + "우")
                if final == _F_S and stem[-1] in _S_IRREGULAR:
                    links.append(head + _join(i, m) + "으")
                for link in links:
                    add(link, lemma, _END_HON)
                    add(link, lemma, _END_LINK)
            for link in links:
                for f, table in ((_F_N, _END_FUSED_N), (_F_L, _END_FUSED_L)):
                    fused = _with_final(link[-1], f)
                    if fused:
                        add(link[:-1] + fused, lemma, table)
                if not link.endswith("으"):
                    fused_b = _with_final(link[-1], _F_B)
                    if fused_b:
                        add(link[:-1] + fused_b, lemma, _END_FUSED_B)
            for a_form in a_forms(stem):
                add(a_form, lemma, _END_A)
                past = _with_final(a_form[-1], _F_SS)
                if past:
                    add(a_form[:-1] + past, lemma, _END_PAST)
        self._forms = forms
        self._max_len = max((len(s) for s in forms), default=0)

    # 어절 하나 -------------------------------------------------------------------
    def analyze_word(self, word: str) -> list[Parse]:
        """가장 긴 어간부터 맞춰 보고, 남은 부분이 어미로 설명되는 첫 길이의 해석을 모두 돌려준다.

        긴 어간 우선 — '내려놓으세요'는 '내리다+놓다'가 아니라 사전에 있는 '내려놓다'다.
        """
        return self._analyze(word, depth=0)

    def _analyze(self, word: str, depth: int) -> list[Parse]:
        for k in range(min(len(word), self._max_len), 0, -1):
            entries = self._forms.get(word[:k])
            if not entries:
                continue
            rest = word[k:]
            found = [Parse(lemma, table[rest]) for lemma, table in entries if rest in table]
            # 어미로 바로 설명되면 그것만 쓴다. 아니면 '-아/-어' 뒤에 다른 용언이 붙어 한
            # 어절이 된 꼴(닦아주세요·갈아입으세요)로 본다. 순서가 중요하다 — "꺼내세요"를
            # '꺼내(-어)+세요'로도 읽으면 '세다'라는 없는 동작이 생긴다.
            if not found and rest and depth == 0:
                for lemma, table in entries:
                    if table is not _END_A:
                        continue
                    for sub in self._analyze(rest, depth + 1):
                        if sub.lemma == _PASSIVE_AUX:
                            found.append(Parse(lemma, EXCL, aux=sub.lemma))
                        elif sub.lemma in AUXILIARIES:
                            found.append(Parse(lemma, sub.kind, aux=sub.lemma))
                        else:
                            found.append(Parse(lemma, sub.kind))
                            found.append(Parse(sub.lemma, sub.kind))
            if found:
                return _unique(found)
        if depth == 0:
            generic = generic_hada(word) if self._generic_hada else None
            if generic is not None:
                return [generic]
        return []

    # 문장 ----------------------------------------------------------------------
    def analyze_text(self, text: str) -> list[tuple[int, Parse]]:
        """(어절 번호, 해석) 목록. 띄어 쓴 보조 용언("접어 두세요")을 앞 동사에 합친다."""
        words = _TOKEN_RE.findall(text or "")
        per_word = [self.analyze_word(w) for w in words]
        out: list[tuple[int, Parse]] = []
        skip_next_aux: dict[int, str] = {}
        for idx, parses in enumerate(per_word):
            nxt = per_word[idx + 1] if idx + 1 < len(per_word) else []
            for p in parses:
                if p.lemma == skip_next_aux.get(idx):
                    continue  # 앞 동사에 흡수된 보조 용언
                kind = p.kind
                if kind == BARE and nxt:
                    aux = next((q for q in nxt if q.lemma in AUXILIARIES or q.lemma == _PASSIVE_AUX), None)
                    if aux is not None:
                        # 본동사는 보조 용언의 어미(종결·조건·관형)를 따른다: "꺼내 오세요"는 지시,
                        # "꺼내 온 상자"는 꾸밈.
                        kind = EXCL if aux.lemma == _PASSIVE_AUX else aux.kind
                        skip_next_aux[idx + 1] = aux.lemma
                    # 띄어 쓴 합성 동사가 사전에 있으면(채워 넣다 → '채워넣다') 그것도 넣는다.
                    compound = self._compound(words[idx], words[idx + 1])
                    if compound is not None:
                        out.append((idx, Parse(compound.lemma, compound.kind)))
                elif kind == BARE and len(words[idx]) == 1:
                    # 한 글자 '-어'형(세·내·와)은 수사·대명사·조사와 겉모양이 같다("세 장",
                    # "내 자리"). 뒤에 동사가 이어질 때만 동사로 본다.
                    kind = EXCL
                out.append((idx, Parse(p.lemma, kind, p.aux)))
        return out

    def _compound(self, left: str, right: str) -> Parse | None:
        """띄어 쓴 두 어절을 붙였을 때 사전에 있는 합성 동사가 되면 그 해석.

        한국어 합성 동사·보조 용언은 띄어쓰기가 사람마다 다르다(채워 넣다/채워넣다,
        쓸어 담다/쓸어담다). 사전 쪽은 붙여 쓴 형태가 많아 붙여 보고 확인한다.
        """
        for p in self._analyze(left + right, depth=1):
            if len(p.lemma) - 1 > len(left) and p.aux is None:
                return p
        return None

    def main_lemmas(self, text: str) -> set[str]:
        """지시하는 동작(종결·연결 서술어)의 원형. 조건절·관형절·과거형의 동사는 뺀다."""
        return set(self.lemma_roles(text))

    def lemma_roles(self, text: str) -> dict[str, str]:
        """할 일 동사의 원형 → 역할('head' 문장 끝 서술어 | 'side' 앞 절의 동작).

        한국어 지시문은 마지막 서술어가 지시의 중심이다. "뚜껑을 덮고 꾹 눌러 맞추세요"의
        중심은 '맞추다'이고 '덮다'는 앞 단계다. 연결 어미 없이 바로 이어진 '-어' 형태
        ("눌러 맞추세요"·"주워 모으세요")는 뒤 동사와 한 동작을 이루므로 중심에 넣는다.
        문장에 종결 서술어가 없으면(명사구·검색어) 전부 중심으로 본다.
        """
        words = _TOKEN_RE.findall(text or "")
        parsed = self.analyze_text(text)
        carriers = {i for i, w in enumerate(words) if w in _CARRY_WORDS}
        # 연결 어미(-고/-어서)로 이어진 절은 뒤 조건절의 범위를 따른다. "점심 먹고 오면"의
        # '먹다'는 '오면'과 함께 조건절이고, "화장실을 쓰고 있으면"의 '쓰다'도 그렇다.
        # 관형·명사절(-는지/-ㄴ)은 따르지 않는다 — "찍어 주문과 맞는지 확인해요"의 '찍다'는
        # '맞는지'에 딸린 말이 아니라 '확인해요'와 나란한 할 일이다.
        word_kind: dict[int, str] = {}
        for idx, p in parsed:
            # 한 어절에 해석이 여럿이면 할 일로 읽히는 해석을 대표로 삼는다.
            if idx not in word_kind or (p.kind in MAIN_KINDS and word_kind[idx] not in MAIN_KINDS):
                word_kind[idx] = p.kind
        effective: dict[int, str] = {}
        head_words: set[int] = set()
        following: str | None = None
        for idx in sorted(word_kind, reverse=True):
            kind = word_kind[idx]
            if kind in (CONN, BARE) and following == COND:
                kind = following
            effective[idx] = kind
            if kind == FINAL or (kind == BARE and idx + 1 in head_words):
                head_words.add(idx)
            following = kind
        roles: dict[str, str] = {}
        for idx, p in parsed:
            if p.kind not in MAIN_KINDS or effective.get(idx) not in MAIN_KINDS:
                continue
            if p.lemma in _LIGHT_VERBS:
                continue
            # "갖다 놓으세요"·"가져다 드려요"의 '갖다/가져다'는 '들고 가서'라는 부사 구실이다.
            # 할 일은 뒤의 동사다.
            if idx in carriers and idx + 1 < len(words) and any(q for j, q in parsed if j == idx + 1):
                continue
            role = "head" if idx in head_words or not head_words else "side"
            lemma = _HONORIFIC_SUPPLETION.get(p.lemma, p.lemma)
            # '가져다/갖다 + 주다·드리다'는 한 낱말 '가져다주다'(옮겨다 주다)라 할 일은 '전달'이다.
            # 공손의 '주다'로 버리면 "자리에 가져다 드려요"에서 남는 동작이 없고, '주다'로 두면
            # "거슬러 준다" 같은 엉뚱한 그림과 만난다. 그림 원형에서 이 뜻을 맡는 낱말은 '전달하다'다.
            if lemma == "주다" and idx - 1 in carriers:
                lemma = _CARRY_GIVE_LEMMA
            for item in (lemma, self.aux_compound_main(lemma)):
                if item and roles.get(item) != "head":
                    roles[item] = role
        return roles

    def aux_compound_main(self, lemma: str) -> str | None:
        """사전에 붙여 쓴 '본동사+보조 용언' 원형(눌러주다·뿌려주다·모아두다)의 본동사.

        사전에 이런 낱말이 따로 있어서 가장 긴 어간 우선 규칙이 '눌러주다'를 고른다. 그런데
        다른 그림의 원형은 '누르다'라 둘이 만나지 못한다. 보조 용언을 떼어 본동사도 함께 낸다.

        '-어 주다/드리다/두다/놓다'만 뗀다. '-어 내다/오다/가다/보다'는 굳어서 한 낱말이 된
        경우가 많다('꺼내다'는 '끄다+내다'가 아니고 '가져오다'·'살펴보다'도 그렇다).
        """
        for aux in _DETACHABLE_AUX:
            if lemma.endswith(aux) and len(lemma) > len(aux):
                head = lemma[: -len(aux)]
                for main, table in self._forms.get(head, ()):
                    if table is _END_A and main != lemma:
                        return main
        return None

    def is_verb_word(self, word: str) -> bool:
        """어절이 (종류와 상관없이) 동사 활용형인가."""
        return bool(self.analyze_word(word))


# '갖다/가져다 + 동사'의 앞부분. '가져다'는 '가지다'의 -어다 연결형, '갖다'는 그 준말이다.
_CARRY_WORDS = frozenset({"갖다", "가져다"})

# '가져다주다'(갖다주다)의 뜻을 그림 원형 쪽 낱말로 옮긴 것. 위 lemma_roles 주석 참고.
_CARRY_GIVE_LEMMA = "전달하다"

_DETACHABLE_AUX = ("주다", "드리다", "두다", "놓다")

# 뜻이 거의 없는 형식 동사. "체크를 해요"의 '하다'는 그림의 동작을 가르지 못한다.
_LIGHT_VERBS = frozenset({"하다", "있다", "되다"})

# 높임 보충법: '드리다'는 '주다'의 낮춤말이라 동작은 같다("서류를 드려요" = 서류를 준다).
_HONORIFIC_SUPPLETION = {"드리다": "주다"}


def _unique(parses: list[Parse]) -> list[Parse]:
    seen: set[tuple[str, str]] = set()
    out: list[Parse] = []
    for p in parses:
        key = (p.lemma, p.kind)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def is_plain_lemma(word: str) -> bool:
    """한 어절짜리 '…다' 형태인가(구 'X를 Y한다'나 영어는 사전에서 뺀다)."""
    return (
        isinstance(word, str) and len(word) >= 2 and word.endswith("다")
        and " " not in word and all("가" <= ch <= "힣" for ch in word)
    )


def is_conjugated_form(word: str) -> bool:
    """'갠다'·'건다'·'놓는다'처럼 원형이 아니라 '-ㄴ다/-는다' 평서형인가(겉모양 판정)."""
    if not is_plain_lemma(word) or len(word) < 2:
        return False
    if word.endswith("는다") and len(word) >= 3:
        return True
    parts = _split(word[-2])
    return parts is not None and parts[2] == _F_N


def generic_hada(word: str) -> Parse | None:
    """사전에 없는 'X하다' 동사(복사하세요 → 복사하다). X는 두 글자 이상의 한글.

    한자어 동작 명사 + '하다'는 한국어 동사를 만드는 가장 흔한 방법이라, 사전 밖이어도
    활용 꼴만 맞으면 동사로 본다.
    """
    analyzer = _hada_analyzer()
    for k in range(2, len(word)):
        if word[k] not in "하해했합한할":
            continue
        head = word[:k]
        if not all("가" <= ch <= "힣" for ch in head):
            continue
        for p in analyzer.analyze_word(word[k:]):
            if p.lemma == "하다":
                return Parse(head + "하다", p.kind, p.aux)
    return None


@lru_cache(maxsize=1)
def _hada_analyzer() -> Analyzer:
    # 이 분석기 자신은 'X하다' 폴백을 타지 않는다(무한 재귀 방지).
    return Analyzer({"하다"}, generic_hada=False)
