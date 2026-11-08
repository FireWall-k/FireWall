"""단계 나누기(step_split) — 확실한 꼴만 자동으로 나누고, 나머지는 한 단계로 두고 제안한다.

여기 문장은 정답셋 문장이 아니라 일반 일터 지시문으로 새로 썼다. 지난 시도들이 검증에서 걸린 꼴
(1·2차: 부정 뒤집힘·사건 절·걸어서·대상 잘못 넘기기·'엎어를' / 3차: 사고·실수 앞 절, 남이 하는 일, 꾸밈말을 잃은
대상, 잘린 나열, 기록 동사로 넘긴 대상, 조건 앞에 붙인 대상, ㄹ 탈락 지시형, 보조 용언 묶음 / 4차: 도구 '-로' 절의
대상 넘기기, 물음·약속을 지시로 바꿈, '경우·-거든' 조건, 'X는 빼고'(= X 없이), 정도 부사·'다시'가 든 까닭 절,
앞 일을 가리키는 '그 위에')을 그대로 반례로 둔다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import step_split  # noqa: E402
from step_split import split_clause  # noqa: E402

# ---- 자동으로 나누는 꼴 ------------------------------------------------------------------

SAFE = [
    # -고: 대상이 있는 두 동작, 뒤 절은 원문 그대로
    ("손을 씻고 장갑을 끼세요.", ["손을 씻으세요.", "장갑을 끼세요."]),
    ("쓰레기를 버리고 손을 씻으세요.", ["쓰레기를 버리세요.", "손을 씻으세요."]),
    ("상자를 접고 나서 테이프를 붙이세요.", ["상자를 접으세요.", "테이프를 붙이세요."]),
    # -어서: 같은 물건을 이어서 다룬다 → 대상을 넘긴다(손질 동사 → 옮기기·놓기 동사)
    ("상자를 접어서 분리수거함에 넣으세요.", ["상자를 접으세요.", "상자를 분리수거함에 넣으세요."]),
    ("봉투를 묶어서 밖으로 꺼내세요.", ["봉투를 묶으세요.", "봉투를 밖으로 꺼내세요."]),
    # 끝맺음을 원문에 맞춘다(…어요 → …어요)
    ("영수증을 받아서 상자에 넣어요.", ["영수증을 받아요.", "영수증을 상자에 넣어요."]),
    # 꾸밈말이 있는 대상은 명사구 통째로 넘긴다(주제어 -은/-는은 -을/-를로)
    ("빈 병은 모아서 박스에 담으세요.", ["빈 병은 모으세요.", "빈 병을 박스에 담으세요."]),
    ("깨진 컵을 주워서 버리세요.", ["깨진 컵을 주우세요.", "깨진 컵을 버리세요."]),
    ("유통기한이 지난 우유를 모아서 버리세요.", ["유통기한이 지난 우유를 모으세요.", "유통기한이 지난 우유를 버리세요."]),
    # 절 맨 앞 출발 자리('선반에서')는 넘기지 않는다
    ("선반에서 깨진 병을 집어서 버리세요.", ["선반에서 깨진 병을 집으세요.", "깨진 병을 버리세요."]),
    # 사전 밖 동사 + 보조 용언("엎어 두세요")은 뒤 절 그대로 — 조사를 붙이지 않는다
    ("그릇을 모아서 건조대에 엎어 두세요.", ["그릇을 모으세요.", "그릇을 건조대에 엎어 두세요."]),
    # 한 음절 ㅐ 어간의 '-요'는 줄인 꼴(빼어요 ×)
    ("박스를 묶고 빼요.", ["박스를 묶어요.", "박스를 빼요."]),
    # -(으)ㄴ 다음에/후에/뒤에(받침 있는 어간 '-은', '-한'만)
    ("손을 씻은 후에 장갑을 끼세요.", ["손을 씻으세요.", "장갑을 끼세요."]),
    ("선반을 정리한 뒤에 바닥을 닦으세요.", ["선반을 정리하세요.", "바닥을 닦으세요."]),
    # ㄹ 어간은 '-어 주세요'(쓰세요·터세요로 읽히지 않게)
    ("바닥을 쓸고 쓰레기를 버리세요.", ["바닥을 쓸어 주세요.", "쓰레기를 버리세요."]),
    ("걸레를 빨고 창문을 닦으세요.", ["걸레를 빨아 주세요.", "창문을 닦으세요."]),
    # 세 동작 — 경계가 모두 안전할 때만
    ("상자를 열고 컵을 집고 선반에 올리세요.", ["상자를 여세요.", "컵을 집으세요.", "컵을 선반에 올리세요."]),
]


@pytest.mark.parametrize("text,expected", SAFE)
def test_safe_patterns_are_split(text, expected):
    out = split_clause(text)
    assert out.auto, (text, out.why_not)
    assert out.steps == expected
    assert out.suggestion is None and out.reason is None


def test_every_generated_sentence_passes_the_grammar_check():
    an = step_split._analyzer()
    for text, _ in SAFE:
        for piece in split_clause(text).steps:
            assert step_split._grammar_ok(piece, an), piece
            assert not step_split.has_negation(piece)


# ---- 자동으로 나누지 않는 꼴 -----------------------------------------------------------

NEGATION = [
    "버리지 말고 모아 두세요.",
    "장갑을 벗지 말고 칼을 닦으세요.",
    "약품을 섞지 말고 따로 보관하세요.",
    "상자를 접고 테이프는 버리지 마세요.",
    "포장을 뜯지 않고 선반에 올려요.",
    "기계를 끄지 않고 청소하면 안 돼요.",
    "물을 틀면 안 되고 걸레로 닦으세요.",
    "전원을 안 끄고 필터를 갈면 위험해요.",
]


@pytest.mark.parametrize("text", NEGATION)
def test_negation_is_never_split(text):
    out = split_clause(text)
    assert not out.auto and out.steps == [text]
    assert out.suggestion is None          # 초안을 만들지 않는다 — 떼면 뜻이 뒤집힌다
    assert out.reason in (None, "negation")


def test_negation_with_two_actions_gets_hint_without_draft():
    out = split_clause("장갑을 벗지 말고 칼을 닦으세요.")
    assert out.reason == "negation" and out.suggestion is None


def test_location_an_is_not_negation():
    assert not step_split.has_negation("차 안 바닥 매트를 꺼내세요.")
    assert step_split.has_negation("뚜껑을 안 닫았어요.")


# 사고·실수 앞 절 — 시킬 일은 뒤 절 하나다. 나누지 않고, 힌트·초안도 없다(초안을 그대로 확정하면 "쏟으세요").
MISHAP = [
    "음료를 쏟아서 휴지로 닦으세요.",
    "커피를 쏟은 후에 걸레로 닦으세요.",
    "음료를 쏟고 나서 바로 휴지로 닦으세요.",
    "손가락을 베어서 반장님께 말하세요.",
    "손을 베고 밴드를 붙이세요.",
    "상품을 잘못 넣고 다시 빼세요.",
    "주문을 잘못 받아서 다시 받아요.",
    "실수로 컵을 넣어서 다시 꺼내요.",
    "가격표를 잘못 붙여서 다시 붙여요.",
    "접시를 떨어뜨려서 빗자루로 쓸어 주세요.",
    "우유를 흘리고 걸레로 닦아요.",
]


@pytest.mark.parametrize("text", MISHAP)
def test_mishap_clause_is_not_an_order(text):
    out = split_clause(text)
    assert not out.auto and out.steps == [text]
    assert out.suggestion is None


# 일부러 할 때도 있는 동사(찢다·깨다)는 동작으로 세되 초안 없이 힌트만
@pytest.mark.parametrize("text", ["옷을 찢어서 반장님께 보여 주세요.", "컵을 깬 후에 장갑을 끼고 치우세요."])
def test_ambiguous_mishap_verb_gets_no_draft(text):
    out = split_clause(text)
    assert not out.auto and out.suggestion is None


# 근로자가 아닌 사람이 하는 앞 절 — 나누지 않고 초안도 없다(그대로 확정하면 손님에게 시키는 문장).
OTHER_SUBJECT = [
    "손님께서 카드를 내고 나서 영수증을 드리세요.",
    "팀장님은 박스를 접고 나서 테이프를 붙여요.",
    "기사님은 짐을 내리고 나서 서명을 받아요.",
    "동료는 상자를 열고 나서 물건을 꺼내요.",
    "손님이 카드를 주고 나서 영수증을 드리세요.",
    "메뉴를 고르시고 나서 주문을 받으세요.",
    "사장님이 문을 열고 나서 불을 켜세요.",
    "동료가 바닥을 닦고 나서 의자를 내리세요.",
]


@pytest.mark.parametrize("text", OTHER_SUBJECT)
def test_other_persons_action_is_not_an_order(text):
    out = split_clause(text)
    assert not out.auto and out.steps == [text]
    assert out.suggestion is None


MUST_NOT_SPLIT = [
    # 보조 용언 묶음(갖다·엎어 + 두다 포함)
    "상자를 빼 두고 바닥을 닦으세요.",
    "컵을 닦아 주고 쟁반에 놓으세요.",
    "그릇을 갖다 두고 손을 씻으세요.",
    "접시를 엎어 두고 행주를 빠세요.",
    # 방법·수단
    "손으로 눌러서 고정하세요.",
    "부품을 홈에 맞춰서 끼우세요.",
    "계단으로 걸어서 올라가요.",
    "카트를 밀고 가세요.",
    "손잡이를 잡고 당기세요.",
    "물건을 들고 창고로 가세요.",
    "주문서를 보고 컵을 꺼내세요.",
    # 조건·때·까닭 절(문장 어디에 있든)
    "출근하면 카드를 찍고 이름을 쓰세요.",
    "일하기 전에 손을 씻고 장갑을 끼세요.",
    "점심을 먹고 오면 앞치마를 입으세요.",
    "아이스크림을 꺼내서 녹으면 버리세요.",
    "컵을 씻고 마르면 선반에 올리세요.",
    "바닥이 미끄러우니까 걸레로 닦고 표지판을 세우세요.",
    # 일어나는 일(주어 -이/-가)
    "비가 와서 우산을 챙기세요.",
    "손님이 나가고 테이블을 닦으세요.",
    "기계가 멈추고 불이 꺼지면 문을 여세요.",
    # 나열 대상(쉼표·와/과·이나/나·또는·띄어 쓴 명사 여럿)
    "컵, 접시, 수저를 씻고 정리하세요.",
    "숟가락과 젓가락을 씻어서 통에 넣으세요.",
    "컵 접시 수저를 씻고 건조대에 올리세요.",
    "컵이나 접시를 씻어서 선반에 올리세요.",
    "포크 또는 나이프를 닦아서 통에 넣으세요.",
    # 넘길 대상이 아닌 뒤 동사(기록·털기) — 뒤 절이 대상 없이 남는다
    "동전을 세고 장부에 적으세요.",
    "매트를 꺼내서 털고 다시 깔아 주세요.",
    "휴지통을 비워서 큰 봉투에 모으세요.",
    # 일부러 하는 일 목록 밖 앞 동사
    "밥을 먹은 후에 양치하세요.",
    "반죽을 치대고 오븐에 넣으세요.",
    # 원형이 둘인 겉모양·다른 동사로 읽히는 지시형
    "옷을 옷걸이에 걸어서 정리하세요.",
    "주문을 들어서 포스에 입력하세요.",
    "옷을 걸고 문을 닫으세요.",
    # 연결 어미 없는 '-어'형(제안만)
    "빵을 집어 봉투에 담아요.",
    # '-어서' 뒤 절에 다른 대상 — 방법으로 읽힌다
    "물을 뿌려서 먼지를 씻어내세요.",
    # 뒤 절이 한 어절뿐(대상을 넘길 근거 없음)
    "카드를 받아서 결제하세요.",
    # 받침 없는 어간의 '-ㄴ 다음에'(연: 열다/여다?)
    "상자를 연 다음에 물건을 꺼내세요.",
    # 뒤 절이 가다/오다뿐
    "문을 열고 들어가세요.",
    # 인용
    '전화를 받고 "네, 매장입니다" 하고 말해요.',
    # 동시 동작
    "손잡이를 소독하며 닦으세요.",
    # 끝맺음이 '-요'가 아님
    "상자를 접고 박스에 넣습니다.",
    # 씻다·닦다·헹구다·꺼내다는 대상을 넘기지 않는다 — 뒤 절이 대상 없이 남아 자동으로 나누지 않는다
    "컵을 씻어서 건조대에 엎어 두세요.",
    "냉장고에서 우유를 꺼내서 버리세요.",
    "빈 컵은 헹궈서 바구니에 모아 두세요.",
]

# 4차 검증 반례(검증자 문장과 같은 꼴). 자동으로 나누지 않는다.
TOOL_PHRASE = [   # 도구 '-로'가 있으면 대상을 넘기지 않는다 — 버릴 것·꽂을 것은 도구다
    "물티슈로 손잡이를 닦고 버리세요.",
    "휴지로 테이블을 닦아서 버리세요.",
    "칫솔로 이를 닦고 컵에 꽂으세요.",
    "칼로 고기를 자르고 칼꽂이에 꽂으세요.",
    "가위로 끈을 자르고 서랍에 넣으세요.",
    "집게로 쓰레기를 줍고 통에 넣으세요.",
    "걸레로 창문을 닦아서 빨래통에 넣으세요.",
]
NOT_INSTRUCTION = [   # 물음·약속·과거·'-어야 해요'·'-도 돼요'
    "상자를 접고 넣을게요.",
    "상자를 접고 어디에 넣어요",
    "상자를 접어서 넣을까요",
    "컵을 씻고 선반에 올릴까요",
    "상자를 접고 창고에 넣어야 해요.",
    "컵을 씻고 선반에 올려도 돼요.",
    "어제 상자를 접고 창고에 넣었어요.",
    "상자를 접고 창고에 넣으실래요",
]
CONDITION_MORE = [   # '경우'·'-거든'·'-다면'·'-니'·'-자마자'·'되도록'·'-마다'
    "급한 경우 장갑을 벗고 손을 씻으세요.",
    "주문이 들어오는 경우에는 컵을 꺼내고 얼음을 담으세요.",
    "필요한 경우 장갑을 끼고 칼을 씻으세요.",
    "상자가 다 차거든 테이프를 붙이고 창고에 옮기세요.",
    "주문이 끝났다면 컵을 씻고 선반에 올리세요.",
    "혹시 모르니 장갑을 끼고 칼을 씻으세요.",
    "바쁘니 컵을 씻고 선반에 올리세요.",
    "출근하자마자 손을 씻고 앞치마를 입으세요.",
    "되도록 장갑을 끼고 칼을 씻으세요.",
    "매일 아침마다 문을 열고 불을 켜세요.",
]
EXCEPT = [   # 'X(는) 빼고' = X 없이 — 힌트만, 초안 없음
    "설탕을 빼고 커피를 타세요.",
    "얼음은 빼고 컵에 담으세요.",
    "양파는 빼고 접시에 놓으세요.",
    "고기는 빼고 그릇에 담아요.",
    "통 뚜껑을 빼고 넣으세요.",
]
DEGREE_REDO = [   # 정도·평가 부사, 뒤 절의 '다시' — 지난 실수를 말하는 까닭 절. 힌트만, 초안 없음
    "빨래를 덜 헹궈서 다시 세탁기에 넣으세요.",
    "상자를 대충 접어서 다시 넣으세요.",
    "봉투를 느슨하게 묶어서 다시 넣으세요.",
    "택배를 늦게 받아서 바로 창고에 두세요.",
    "물을 너무 많이 넣어서 조금 버리세요.",
    "라벨을 거꾸로 붙이고 다시 떼세요.",
    "손님이 입어 본 옷은 개어서 다시 걸어 주세요.",
]
DEICTIC = [   # 뒤 절이 앞 일을 가리킨다 — 떼어 낸 단계 혼자서는 뜻이 비어 자동으로 나누지 않는다
    "접시를 놓고 그 위에 빵을 올리세요.",
    "상자를 열고 그 안에 컵을 넣으세요.",
]


@pytest.mark.parametrize("text", MUST_NOT_SPLIT + TOOL_PHRASE + NOT_INSTRUCTION + CONDITION_MORE + EXCEPT
                         + DEGREE_REDO + DEICTIC)
def test_unsafe_patterns_stay_one_step(text):
    out = split_clause(text)
    assert not out.auto, (text, out.steps)
    assert out.steps == [text]


@pytest.mark.parametrize("text", TOOL_PHRASE)
def test_tool_phrase_never_carries_the_object(text):
    """도구 '-로' 절의 대상(닦은 손·자른 고기)은 뒤 동작(버리기·꽂기)으로 넘기지 않는다 — 초안에도."""
    out = split_clause(text)
    obj = next(w for w in text.split() if w.endswith(("을", "를")))
    for piece in (out.suggestion or [])[1:]:
        assert obj not in piece, piece


@pytest.mark.parametrize("text", EXCEPT + DEGREE_REDO + NOT_INSTRUCTION)
def test_meaning_risks_get_no_draft(text):
    """초안을 그대로 확정하면 '설탕을 빼세요'·'덜 헹구세요'·'넣을까요'가 지시로 나간다 — 초안을 만들지 않는다."""
    assert split_clause(text).suggestion is None


def test_question_mark_from_the_raw_text_blocks_the_split():
    import decompose
    plans = decompose.plan_steps("상자를 접어서 창고에 넣을까요? 컵을 씻으세요.")
    assert not plans[0].auto and plans[0].suggestion is None
    plans = decompose.plan_steps("상자를 접어서 창고에 넣으세요.")
    assert plans[0].auto


def test_draft_marks_the_box_without_an_object():
    # 앞 단계 대상을 이을 수 있으면 잇는다(2차 검증: 뒤 단계에 무엇을 하는지가 없었다). 못 이으면 칸을 표시한다.
    out = split_clause("영수증을 뽑아서 손님께 드리세요.")
    assert out.suggestion == ["영수증을 뽑으세요.", "영수증을 손님께 드리세요."]
    assert out.suggestion_gaps is None
    out = split_clause("동전을 세고 장부에 적으세요.")
    assert out.suggestion == ["동전을 세세요.", "장부에 적으세요."]
    assert out.suggestion_gaps == [1]
    out = split_clause("출근하면 카드를 찍고 이름을 쓰세요.")
    assert out.suggestion_gaps is None


def test_auto_split_keeps_the_original_sentence():
    out = split_clause("상자를 접어서 분리수거함에 넣으세요.")
    assert out.auto and out.source == "상자를 접어서 분리수거함에 넣으세요."


def test_drafts_never_carry_an_object_into_a_verb_that_does_not_take_it():
    out = split_clause("밥을 먹은 후에 양치하세요.")
    for piece in out.suggestion or []:
        assert "밥을 양치" not in piece
    out = split_clause("컵 접시 수저를 씻고 건조대에 올리세요.")
    assert out.suggestion is None or all("접시 수저를 건조대" not in p for p in out.suggestion)
    out = split_clause("동전을 세고 장부에 적으세요.")
    assert out.suggestion is None or all("동전을 장부" not in p for p in out.suggestion)


def test_condition_stays_with_its_step_in_the_draft():
    out = split_clause("출근하면 카드를 찍고 이름을 쓰세요.")
    assert out.reason == "multi_action"
    assert out.suggestion == ["출근하면 카드를 찍으세요.", "이름을 쓰세요."]


def test_no_object_is_put_before_a_condition():
    out = split_clause("아이스크림을 꺼내서 녹으면 버리세요.")
    assert not out.auto
    assert all("아이스크림을 녹으면" not in p for p in out.suggestion or [])


def test_bare_a_form_gets_a_draft_in_the_original_ending():
    out = split_clause("빵을 집어 봉투에 담아요.")
    assert out.reason == "multi_action"
    assert out.suggestion == ["빵을 집어요.", "빵을 봉투에 담아요."]


def test_single_action_has_no_hint():
    for text in ("바닥을 닦으세요.", "의자를 테이블 안으로 밀어 넣으세요.", "솔로 문질러 닦으세요.",
                 "창고에서 상자를 꺼내 오세요.", "비가 와서 우산을 챙기세요.", "음료를 쏟아서 휴지로 닦으세요."):
        out = split_clause(text)
        assert out.reason is None and not out.auto, (text, out)


def test_grammar_check_rejects_broken_forms():
    an = step_split._analyzer()
    assert not step_split._grammar_ok("상자를 접고를 넣으세요.", an)
    assert not step_split._grammar_ok("상자를 접고 넣으세요.", an)       # 연결형이 남음
    assert not step_split._grammar_ok("넣으세요.", an)                  # 한 어절
    assert not step_split._grammar_ok("상자를 접으세요", an)            # 마침표 없음
    assert not step_split._grammar_ok("상자를 접은.", an)               # 종결 서술어 아님
    assert step_split._grammar_ok("상자를 접으세요.", an)
    assert not step_split._grammar_ok("상자를 넣을까요.", an)          # 물음
    assert not step_split._grammar_ok("상자를 넣을게요.", an)          # 약속
    assert not step_split._grammar_ok("상자를 넣으세요?", an)
    # 대상을 넘겨 붙인 문장에는 조건·때 꼴이 없어야 한다
    assert not step_split._grammar_ok("상자를 다 차면 버리세요.", an, carried=True)
    assert not step_split._grammar_ok("상자를 퇴근할 때 버리세요.", an, carried=True)


# ---- 지시형 만들기 --------------------------------------------------------------------

@pytest.mark.parametrize("lemma,style,expected", [
    ("접다", "seyo", "접으세요"), ("줍다", "seyo", "주우세요"), ("싣다", "seyo", "실으세요"),
    ("열다", "seyo", "여세요"), ("끄다", "seyo", "끄세요"), ("세다", "seyo", "세세요"),
    # ㄹ 어간: ㄹ 탈락 지시형(써세요·거세요·빠세요·터세요) 대신 '-어 주세요'
    ("썰다", "seyo", "썰어 주세요"), ("걸다", "seyo", "걸어 주세요"), ("빨다", "seyo", "빨아 주세요"),
    ("털다", "seyo", "털어 주세요"), ("쓸다", "seyo", "쓸어 주세요"),
    # '-요' 끝맺음
    ("받다", "yo", "받아요"), ("정리하다", "yo", "정리해요"), ("끄다", "yo", "꺼요"),
    ("놓다", "yo", "놓아요"), ("개다", "yo", "개어요"), ("세다", "yo", "세어요"), ("썰다", "yo", "썰어요"),
    ("빼다", "yo", "빼요"), ("매다", "yo", "매요"),
])
def test_imperative_forms(lemma, style, expected):
    assert step_split.imperative(lemma, style) == expected


def test_homograph_imperative_is_rejected():
    an = step_split._analyzer()
    assert not step_split._reads_as("걸어 주세요", "걸다", an)   # 걷다/걸다
    assert step_split._reads_as("끄세요", "끄다", an)            # 끌다 읽기는 ㄹ 탈락뿐


# ---- 위험 꼴 묶음(eval/split_probes.json, 사람 라벨) ------------------------------------

def test_probe_set_has_no_violations():
    from eval.run_split_eval import evaluate_probes, load_probes
    res = evaluate_probes(load_probes())
    assert res["negation_auto"] == 0
    assert res["violations"] == [], res["violations"]
