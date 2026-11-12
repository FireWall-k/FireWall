"""두 동작 지시문 나누기 — 확실한 꼴만 자동으로 나누고, 나머지는 사업주에게 나누기를 제안한다.

제품 원칙: 한 단계에는 그림이 하나다. 그래서 "박스를 접어서 분리수거함에 넣으세요"는 두 단계여야 한다.
그런데 단계 문장은 발달장애 근로자가 읽는다. 틀린 문장·뜻이 뒤집힌 문장은 안 나눈 단계보다 훨씬 해롭다
(1·2차 시도: "버리지 말고 모아 두세요" → "버리세요", "비가 와서" → "비가 오세요", "걸어서" → "거세요",
"밥을 양치하세요", "엎어를 두세요". 3차 시도: "음료를 쏟아서 닦으세요" → "음료를 쏟으세요",
"손님께서 카드를 내고 나서" → "손님께서 카드를 내세요", "깨진 컵을 주워서 버리세요" → "컵을 버리세요",
"컵 접시 수저를 씻고" → "접시 수저를 …", "동전을 세고 장부에 적으세요" → "동전을 장부에 적으세요").
그래서 두 갈래로 나눈다.

A) 자동 분할 — 아래 조건을 **모두** 만족할 때만. 하나라도 어긋나면 한 단계로 둔다.
   1. 동작 경계가 연결 어미 `-고`(·`-고 나서`) / `-아서·-어서` / `-(으)ㄴ 다음에·후에·뒤에`다.
      연결 어미 없는 '-어'형("빵을 집어 봉투에 담아요")·`-며`·`-다가`·`-거나`는 자동으로 나누지 않는다.
   2. 앞 절 동사가 **일부러 하는 일 동사 목록(DELIBERATE_ACTIONS)**에 있다. "사건·사고 동사가 아니면 된다"가
      아니라 "근로자가 일부러 하는 손일로 확인된 동사만"이다. 쏟다·베다·깨다·떨어뜨리다 같은 사고 동사, 오다·울리다
      같은 사건 동사, 먹다·드시다처럼 까닭으로 읽힐 수 있는 동사는 목록에 없다.
   3. 앞 절·뒤 절 동사가 모두 사전(그림 원형) 낱말이고, 표 기반 활용기(conjugate)가 지시형을 확실히 만든다.
      경계 어절은 활용기가 만든 꼴과 글자 그대로 같아야 하고(round trip), 분석기가 내는 원형이 하나뿐이어야 하며,
      만든 지시형을 분석기로 다시 읽어도 같은 원형 하나로만 읽혀야 한다.
   4. 앞 절은 근로자가 하는 일이다 — 대상(-을/-를, 또는 대상을 받는 동사의 주제어 -은/-는)이 있고, 근로자가 아닌
      주어가 없다: -이/-가 주어, -께서, 사람 주제어(손님은·팀장님은·동료는), 대상이 따로 있는데 붙은 주제어
      (그 주제어가 주어다), 앞 절 동사의 높임 '-시-'(드시고·고르시고). '잘못·실수로·깜빡' 같은 실수 부사도 없다.
   5. 문장 어디에도 부정이 없다(-지 말다·-지 않다·안/못 + 동사·-면 안 되다·금지·절대).
   6. 문장 어디에도 조건·때·까닭 절이 없다(-면·-기 전에·-ㄹ 때·때까지·경우(에는)·-거든·-다면·-더라도·-도록·
      -자마자·-마다·-니·-니까·혹시·만약).
   7. 보조 용언 묶음(빼 두다·갖다 두다·엎어 두다·꺼내 오다)·연속 동사(눌러 맞추다)가 앞 절 동사가 아니고, 앞 절이
      방법·수단(눌러서 고정·잡고 당기다·밀고 가다·보고 꺼내다)이 아니다. 뒤 절이 '가다/오다'뿐이면 나누지 않는다.
   8. 쉼표·따옴표가 없고, 대상이 나열이 아니다(와/과·이나/나·또는/혹은, 띄어 쓴 명사 둘 이상 "컵 접시 수저를").
   9. `-아서·-어서`는 뒤 절에 제 대상(-을/-를)이 없을 때만 — 뒤 절에 다른 대상이 있으면 대개 방법이다.
  10. 뒤 절이 대상 없이 혼자 서면 뜻이 비는 꼴("큰 봉투에 모아요")이 아니다 — 뒤 절에 제 대상이 있거나, 대상을
      넘겼거나, 대상이 필요 없는 동사(이동·기다리기·앉기 …)이거나, '-는지' 절이 대상 자리에 있어야 한다.
  11. 만든 문장마다 문법 자가 검사(_grammar_ok)를 통과한다. 하나라도 실패하면 나누지 않는다.
  12. 지시하는 문장이다(_ending_ok) — 끝맺음이 '-(으)세요'(…주세요·…두세요) 또는 현재 '-아요/-어요'. 물음표, 묻는 말
      (어디·몇·왜 …), -ㄹ까요·-ㄹ게요·-나요·-ㄹ래요, 과거(넣었어요), '-어야 해요'·'-도 돼요'는 지시가 아니다(5차).
  13. 앞 절이 '-고' 앞의 빼다·제외하다가 아니다 — "설탕을 빼고 커피를 타세요"·"얼음은 빼고 담으세요"는 'X 없이'다(5차).
  14. 앞 절에 정도·평가 부사(덜·너무·대충·거꾸로·많이·늦게, 방법 부사 목록 밖의 '-게' 꼴)가 없고, 뒤 절에 '다시·또'가
      없다 — 지난 실수를 말하는 까닭 절("빨래를 덜 헹궈서 다시 넣으세요")이 실수를 시키는 명령이 된다(5차).
  15. '-어서' 앞 절은 대상과 동사 사이에 방법 부사(납작하게·반듯하게 …)·'-씩'·자리 말만 있다(5차).
  16. 뒤 절에 앞 일을 가리키는 말(그 위에·거기에·그걸)이 없다 — 떼어 낸 단계 혼자서는 뜻이 빈다(5차).
   앞 절은 끝 어절만 지시형으로 바꾸고 나머지는 원문 그대로 둔다. 지시형은 원문 끝맺음에 맞춘다(…세요 → '-(으)세요',
   …아요/어요 → '-아요/-어요'). ㄹ 어간은 ㄹ이 떨어진 꼴(써세요·거세요·빠세요·터세요)이 다른 동사로 읽히므로
   '-어 주세요'(썰어 주세요·털어 주세요)로 쓴다(열다·만들다는 '여세요·만드세요'가 흔해 그대로). 뒤 절은 원문 그대로다.
   대상 넘기기는 좁게만: 뒤 절에 대상이 없고, 앞 동사가 대상을 그대로 남기는 손질(접다·묶다·줍다 …)이고, 뒤 동사가
   그 물건을 옮기거나 놓는 동작(넣다·담다·놓다 …)이고, 뒤 절에 조건이 없고, 앞 절에 도구·수단 '-로'가 없고
   ("물티슈로 손을 닦고 버리세요"에서 버릴 것은 물티슈다), 대상이 몸(손·이·얼굴)이 아닐 때. 씻다·닦다·헹구다(대상이
   몸이나 닦은 자리일 때가 많다)와 빼다·꺼내다(버릴 것·담을 것이 어느 쪽인지 갈린다)는 넘기지 않는다(5차). 절 맨 앞
   출발 자리('선반에서')는 넘기지 않는다. 넘기는 말은 대상 명사구 전체다 —
   꾸밈말이 있으면 꾸밈말까지("깨진 컵을", "유통기한이 지난 우유를"). 명사구 경계가 불확실하면(꾸밈말 꼴이 아닌 말이
   바로 앞에 있음, 사이에 다른 대상·주제어가 있음, 나열) 넘기지 않고, 그러면 10번에 걸려 나누지 않는다.

B) 나누기 제안 — 자동으로 나누지 않은 단계에 동작이 둘 이상이면 단계는 그대로 두고 제안을 붙인다
   (Step.split_suggestion / split_reason). 사업주가 검토 화면에서 고쳐 확정해야만 바뀐다.
   - 부정 문장: 제안 문장을 만들지 않는다(reason="negation") — 사업주가 직접 쓴다.
   - 근로자가 아닌 주어가 있거나 앞 절 동사가 일부러 하는 일 목록에 없으면 초안 없이 힌트만 준다 — 그대로 확정하면
     손님에게 시키는 문장·실수를 시키는 문장이 나가기 때문이다.
   - 'X는 빼고'·정도 부사·뒤 절의 '다시'·지시가 아닌 끝맺음(물음·약속)도 초안 없이 힌트만 준다 — 한 번 눌러 확정하면
     "설탕을 빼세요"·"덜 헹구세요"·"넣을까요"가 지시로 나가기 때문이다(5차).
   - 그 밖: 같은 활용기·같은 문법 검사로 초안을 만든다. 조건절은 그 절이 붙은 단계에 남긴다.
     초안을 못 만들면 문장 없이 힌트만 준다(reason="multi_action", suggestion=None). 대상이 빠진 초안 칸("손님께
     드리세요")은 suggestion_gaps로 알려 검토 화면이 "무엇을 하는지 적어 주세요"를 띄운다.
   - 사고·실수 앞 절("음료를 쏟아서 닦으세요", "상품을 잘못 넣고 다시 빼세요")은 동작으로 세지 않는다 — 시킬 일은
     하나이고, 그림도 시킬 일(닦기·빼기)에 맞춘다.

자동으로 나눈 단계에는 decompose가 split_reason="auto_split"과 원문(split_source)을 붙인다. 검토 화면은 "AI가 나눈
문장" 표시를 하고, 확인하거나 고치기 전에는 보내기를 막으며, "원래 문장으로 되돌리기"를 준다.

닫힌 목록(일 동사·방법 동사·대상 넘기기 동사·사고 동사·사람 명사)은 문장이 아니라 낱말의 뜻 갈래로 정한다 — 정답셋
문구를 예외로 넣지 않는다. 측정은 eval/run_split_eval.py(정답셋 + eval/split_probes.json 사람 라벨 묶음), 기록은
eval/README.md.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache

import conjugate
import korean_verbs as kv

logger = logging.getLogger("ai_harness.step_split")

# ---- 닫힌 목록 ---------------------------------------------------------------------------

# 일부러 하는 일 동사 — 자동 분할·제안 초안의 앞 절은 이 목록 안의 동사만. 뜻 갈래별로 적는다.
DELIBERATE_ACTIONS = frozenset({
    # 집고 옮기고 놓기
    "집다", "줍다", "꺼내다", "빼다", "넣다", "담다", "놓다", "내려놓다", "올리다", "올려놓다", "내리다",
    "싣다", "옮기다", "쌓다", "모으다", "받다", "건네다", "꽂다", "끼우다", "걸다", "깔다", "채우다",
    "비우다", "치우다", "정리하다", "정돈하다", "진열하다", "뽑다", "붙이다", "떼다", "바꾸다", "펼치다",
    "감다", "두다", "버리다",
    # 열고 닫기·켜고 끄기·묶고 풀기
    "열다", "닫다", "잠그다", "켜다", "끄다", "덮다", "풀다", "묶다",
    # 접고 펴기·싸기·자르기
    "접다", "펴다", "개다", "싸다", "포장하다", "뜯다", "자르다", "썰다", "깎다",
    # 씻고 닦기
    "씻다", "헹구다", "닦다", "쓸다", "털다", "빨다", "짜다", "말리다", "소독하다", "청소하다",
    # 입고 벗기
    "입다", "벗다", "끼다", "신다", "두르다", "매다",
    # 조리
    "굽다", "데우다", "붓다", "섞다", "건지다",
    # 세고 확인하고 기록하기
    "세다", "확인하다", "적다", "찍다", "재다", "고르다", "나누다", "분리하다", "스캔하다",
    # 뿌리고 바르기
    "뿌리다", "바르다", "묻히다",
    # 그 밖의 손일
    "준비하다", "계산하다", "결제하다",
})

# 사고·실수 동사 — 앞 절이면 시킬 일이 아니라 일어난 일이다("음료를 쏟아서 닦으세요" → 시킬 일은 닦기 하나).
# 동작으로 세지 않는다. 일부러 할 때도 있는 동사(깨다·찢다)는 여기 넣지 않는다 — 동작으로 세되
# DELIBERATE_ACTIONS에 없어 자동 분할도 초안도 없이 힌트만 받는다.
MISHAP_VERBS = frozenset({
    "쏟다", "흘리다", "엎지르다", "떨어뜨리다", "떨어트리다", "깨뜨리다", "깨트리다", "베다", "데다", "다치다",
    "놓치다", "잃어버리다", "잊어버리다", "부러뜨리다", "망가뜨리다", "넘어뜨리다", "부딪치다", "부딪히다",
    "미끄러지다", "까먹다", "틀리다", "빠뜨리다", "태우다",
})
# 실수를 말하는 부사 — 이 말이 든 앞 절은 일어난 일이다("상품을 잘못 넣고 다시 빼세요").
MISHAP_ADVERBS = frozenset({
    "잘못", "잘못해서", "실수로", "깜빡", "깜박", "깜빡하고", "깜박하고", "모르고", "그만", "실수해서", "엉뚱하게",
})

# 근로자가 아닌 사람을 가리키는 명사(주제어·주어로 오면 앞 절은 그 사람이 하는 일이다). '-님'으로 끝나는 말은 모두.
PERSON_NOUNS = frozenset({
    "손님", "고객", "동료", "기사", "직원", "사장", "팀장", "반장", "점장", "매니저", "주방장", "선배", "후배",
    "아이", "어린이", "사람", "친구", "배달원", "경비", "관리자", "담당자", "엄마", "아빠", "선생",
})

# 방법·수단 동사. '-고/-어서' 꼴로 뒤 동작의 방식·도구·자세·참고를 말할 때가 대부분이라 따로 보여 줄
# 그림이 아니다("손잡이를 잡고 당기다", "카트를 밀어서 옮기다", "뚜껑을 돌려서 닫다", "조심해서 뜯다",
# "주문서를 보고 꺼내다"). 이 동사가 앞 절이면 자동으로 나누지 않고, 동작 수에도 세지 않는다.
MANNER_VERBS = frozenset({
    "누르다", "맞추다", "밀다", "당기다", "잡아당기다", "끌어당기다", "끌다", "돌리다", "잡다", "쥐다",
    "들다", "조심하다", "이용하다", "사용하다", "따르다", "타다", "걷다", "보다", "들여다보다",
})

# 갈라 담기 — "크기별로 나눠 담다", "숟가락과 젓가락을 따로 모아 넣다", "같은 색끼리 모아 걸다"는 물건을 갈래대로
# 그릇·자리에 넣는 동작 하나다(그림도 '분류해 담기' 한 장). 앞 동사가 나누기·모으기이고, 그 절에 갈래 말(-별로·
# -끼리·따로)이나 나열 대상이 있고, 뒤 동사가 담기·넣기·걸기 같은 놓기이면 앞 절을 동작으로 세지 않는다.
# 갈래 말이 없는 "머그컵을 모아 식기세척기에 넣다"는 두 동작 그대로다(2026-11-09 입력 화면 나누기).
SORT_INTO_VERBS = frozenset({"나누다", "모으다", "분류하다", "가르다", "구분하다"})
SORT_INTO_PLACE = frozenset({"담다", "넣다", "걸다", "놓다", "꽂다", "두다", "모아두다"})

# 이동·왕래 동사. 뒤 절이 이것뿐이면 앞 절은 '들고/싣고 가는' 방법일 수 있다("바구니를 밀고 가세요").
BARE_MOTION = frozenset({"가다", "오다", "다니다", "나가다", "나오다", "들어가다", "들어오다"})

# 일어나는 일(상태 변화) 동사 — 지시가 아니다. 대개 주어(-이/-가)와 함께 와 주어 검사에서 빠지지만,
# 주어를 못 알아본 경우를 위해 동사로도 막는다.
EVENT_VERBS = frozenset({
    "울리다", "끝나다", "나다", "비다", "차다", "멈추다", "떨어지다", "생기다", "도착하다", "흐르다",
    "쌓이다", "열리다", "닫히다", "걸리다", "넘어지다", "쏟아지다", "흩어지다", "되다", "출력되다",
})

# 대상을 그대로 남기는 손질 동사 — 손질한 그 물건을 다음 동작에서 옮기거나 놓는다
# ("상자를 접어서 넣다", "봉투를 묶어서 빼다"). 비우다(비운 통이 아니라 내용물을 옮긴다)·착용 동사·확인 동사·
# 바르기 동사는 넣지 않는다.
# 씻다·닦다·헹구다는 넣지 않는다 — 대상이 몸(손·이·얼굴)이나 닦은 자리(바닥·테이블·창문)일 때가 많아, 넘기면
# "물티슈로 손을 닦고 버리세요" → "손을 버리세요"가 된다(5차 검증). 빼다·꺼내다도 넣지 않는다 — "얼음은 빼고 컵에
# 담으세요"(얼음 없이)는 넘기면 뜻이 뒤집히고, "봉투에서 영수증을 꺼내고 버리세요"는 버릴 것이 어느 쪽인지 갈린다.
# 앞 절에 도구·수단 '-로'가 있으면(물티슈로·칼로) 어떤 동사든 넘기지 않는다(_carries).
CARRY_SOURCE = frozenset({
    "접다", "묶다", "줍다", "개다", "받다", "집다", "모으다", "세다", "끼우다", "포장하다", "자르다", "뽑다",
})
# 물건을 옮기거나 놓는 동사 — 앞 절에서 손질한 물건이 그대로 대상이 된다. 기록 동사(적다)·털다·전달하다·
# 정리하다는 넣지 않는다 — "동전을 세고 장부에 적으세요"에서 적는 것은 동전이 아니라 센 수다.
CARRY_TARGET = frozenset({
    "넣다", "담다", "놓다", "내려놓다", "올리다", "올려놓다", "버리다", "모으다", "옮기다", "쌓다",
    "걸다", "꽂다", "가져오다", "가져가다", "싣다", "깔다", "꺼내다", "빼다",
    "건네다", "두다", "모아두다", "보관하다",
})
# 주제어(-은/-는)를 대상으로 보는 동사 — 대상을 받는 것이 분명한 손질 동사만.
# 빼다는 넣지 않는다 — "얼음은 빼고"의 주제어는 빼라는 대상이 아니라 '없이'의 대상이다.
TOPIC_OBJECT_VERBS = CARRY_SOURCE | frozenset({"치우다", "버리다", "정리하다", "닫다", "열다", "씻다", "닦다",
                                               "헹구다", "꺼내다"})
# 대상 없이도 혼자 뜻이 서는 뒤 절 동사(조건 10).
NO_OBJECT_OK = kv.MOTION_VERBS | frozenset({
    "기다리다", "앉다", "서다", "쉬다", "눕다", "일하다", "퇴근하다", "출근하다", "인사하다",
})
# ㄹ 어간 중 ㄹ이 떨어진 지시형이 흔하고 다른 동사와 헷갈리지 않는 것(그 밖의 ㄹ 어간은 '-어 주세요').
RIEUL_POLITE_OK = frozenset({"열다", "만들다"})

# '-고' 앞 절의 빼다·제외하다는 'X는 빼고(= X 없이)' 뜻일 때가 많다("설탕을 빼고 커피를 타세요"). 떼어 내면
# "설탕을 빼세요"라는 엉뚱한 명령이 되므로 자동으로 나누지도, 초안을 만들지도 않는다(힌트만).
EXCEPT_VERBS = frozenset({"빼다", "제외하다", "빼놓다"})
# 정도·평가 부사 — 앞 절에 있으면 그 절은 지난 실수나 까닭을 말할 때가 많다("빨래를 덜 헹궈서 다시 넣으세요",
# "택배를 늦게 받아서"). 떼어 내면 실수를 시키는 명령이 된다. 자동 분할도 초안도 막는다.
DEGREE_ADVERBS = frozenset({
    "덜", "너무", "너무나", "대충", "대충대충", "대강", "거꾸로", "반대로", "많이", "조금", "좀", "더", "막",
    "마구", "함부로", "아무렇게나", "잔뜩", "지나치게", "엉망으로", "세게", "늦게", "일찍", "빨리", "급하게",
    "적게", "헐겁게", "느슨하게", "삐뚤게", "약하게",
})
# 할 방법을 말하는 부사(닫힌 목록). 이 밖의 '-게' 꼴은 정도·평가 부사로 본다.
HOWTO_ADVERBS = frozenset({
    "납작하게", "반듯하게", "가지런히", "가지런하게", "깨끗이", "깨끗하게", "단단하게", "꽉", "잘", "차곡차곡",
    "줄줄이", "길게", "짧게", "작게", "잘게", "얇게", "크게", "평평하게", "똑바로", "나란히", "천천히", "조심히",
    "꼼꼼히", "꼼꼼하게", "끝까지", "먼저", "바로", "모두", "전부", "다", "하나씩", "한꺼번에", "같이", "따로",
    "살짝",
})
# 뒤 절의 '다시·또' — 앞 절이 다시 해야 하는 까닭(지난 실수)일 때가 많다("상자를 대충 접어서 다시 넣으세요").
REDO_WORDS = frozenset({"다시", "또", "도로", "새로"})
# 앞 일을 가리키는 말 — 뒤 절에 있으면 떼어 낸 단계 혼자서는 무엇을 가리키는지 모른다("그 위에 놓으세요").
DEICTIC_WORDS = frozenset({"그", "이", "저", "거기", "여기", "저기", "거기에", "여기에", "저기에", "그곳", "이곳",
                           "그곳에", "이곳에", "그쪽", "이쪽", "그쪽에", "이쪽에"})
_DEICTIC_PREFIXES = ("그거", "그것", "그걸", "이거", "이것", "이걸", "저거", "저것", "저걸")
# 묻는 말 — 문장에 있으면 지시가 아니라 물음이다("상자를 접고 어디에 넣어요").
_QUESTION_PREFIXES = ("어디", "언제", "무엇", "뭐", "뭘", "어떻게", "어떤", "누구", "누가", "몇", "어느", "얼마")
# 지시가 아닌 '-요' 끝맺음(물음·약속·확인·감탄).
_NON_INSTRUCTION_ENDINGS = ("까요", "게요", "래요", "나요", "죠", "지요", "네요", "군요", "는데요", "은데요",
                            "거든요", "잖아요", "던데요", "대요")
# 몸을 가리키는 명사 — 다음 동작으로 넘기면 "손을 버리세요"가 된다.
NO_CARRY_NOUNS = frozenset({"손", "발", "얼굴", "이", "머리", "코", "입", "눈", "몸", "팔", "다리", "손가락",
                            "손톱", "귀", "목", "등", "허리", "머리카락"})
# 도구·수단 '-로'로 보지 않는 '-로' 부사.
_RO_ADVERBS = frozenset({"바로", "따로", "새로", "서로", "스스로"})
# '세요·개요'는 높임 지시형·명사로 읽혀 풀어 쓴 꼴(세어요·개어요)을 쓴다. 그 밖의 한 음절 ㅐ·ㅔ 어간은 줄인 꼴(빼요).
_YO_AMBIGUOUS = frozenset({"세요", "개요"})

# 대상으로 넘기면 뜻이 없는 의존 명사·수량 명사(꾸밈말 없이 홀로 올 때).
_DEPENDENT_NOUNS = frozenset({
    "것", "거", "걸", "데", "수", "개", "장", "명", "번", "줄", "칸", "잔", "병", "통", "봉", "곳",
    "쪽", "위", "아래", "밑", "옆", "앞", "뒤", "안", "속", "밖", "사이", "끝",
})

# 조건·때를 나타내는 말(문장 어디에 있든 자동으로 나누지 않는다).
_TIME_WORDS = frozenset({"전에", "전", "때", "때는", "때에", "때도", "동안", "동안에", "까지", "때까지",
                         "경우", "경우에", "경우에는", "경우엔", "경우라도", "만약", "만일", "혹시"})
# 조건·때·목적 연결 어미(겉모양). '-니'는 어간과 상관없이 까닭으로 본다(모르니·바쁘니·위험하니).
_COND_ENDINGS = ("거든", "다면", "더라도", "도록", "자마자", "마다", "려면", "니")
# '-(으)ㄴ 다음에/후에/뒤에'의 때 명사.
_TEMPORAL_NOUNS = frozenset({"다음에", "후에", "뒤에", "다음", "후", "뒤", "다음엔", "후엔", "뒤엔"})

# '-이'로 끝나지만 주어가 아닌 부사(닫힌 목록 — 일반 한국어 부사). 첩어 + '-이'(줄줄이·겹겹이)는 겉모양으로 본다.
_I_ADVERBS = frozenset({
    "같이", "똑같이", "깨끗이", "많이", "높이", "깊이", "반듯이", "따뜻이", "일일이", "틈틈이",
    "곳곳이", "낱낱이", "겹겹이", "가까이", "길이", "없이", "빈틈없이", "끊임없이", "가지런히",
})
# 대상 명사 앞에 와도 명사를 꾸미지 않는 부사(절 맨 앞에서 건너뛴다).
_LEAD_ADVERBS = frozenset({
    "먼저", "다시", "바로", "꼭", "잘", "같이", "모두", "전부", "하나씩", "한꺼번에", "천천히", "조심히",
    "깨끗이", "이제", "그다음", "그리고",
})
# 자리·때 주제어(-에는·-에서는) — 주어도 대상도 아니다.
_LOCATIVE_TOPICS = ("에는", "에서는", "로는", "으로는", "까지는", "때는", "에게는", "한테는")
# 까닭 연결 어미(-니까·-으니·-므로·-는데) — 조건처럼 다룬다(앞 절을 떼면 까닭이 명령이 된다).
_REASON_ENDINGS = ("니까", "으니", "우니", "하니", "므로", "는데", "은데")
# 장소·도구 조사(대상 명사 바로 앞의 이 말은 꾸밈말이 아니라 동사에 걸린다: "냉장고에서 우유를").
_LOC_ENDINGS = ("에서", "에게", "한테", "께", "에", "으로", "로")

# 부정. 문장 어디에 있든 자동으로 나누지 않는다(앞 절을 떼면 "버리세요"처럼 뜻이 뒤집힌다).
_NEGATION_RE = re.compile(
    r"지\s*(?:말|마|않|못)|않|말고|마세요|마요|말아|금지|절대|안\s*(?:돼|되)|못\s*하|안\s*하"
)
_NEGATION_ADVERBS = ("안", "못")
_QUOTE_CHARS = "\"'“”‘’「」『』"
# 앞 절 동사의 높임 '-시-'(손님께서 고르시고 / 다 드신 후에) — 근로자가 아니라 높일 사람이 하는 일이다.
_HONORIFIC_RE = re.compile(r"(?:시고|시고서|셔서|시어서|신)$")

# 형용사 어간(깨끗하고·빠르고) — 동작이 아니다.
_ADJ_STEMS = frozenset({
    "깨끗", "튼튼", "조용", "깔끔", "안전", "빠르", "느리", "단단", "부드럽", "따뜻", "차갑", "무겁",
    "가볍", "크", "작", "많", "좋", "나쁘", "예쁘", "더럽", "넓", "좁", "높", "낮", "두껍", "얇",
    "밝", "어둡", "정확", "확실", "꼼꼼", "신선", "같", "다르", "맞", "필요",
})


@dataclass
class SplitOutcome:
    """한 조각(문장)을 어떻게 다룰지."""
    steps: list[str]                       # 자동 분할이면 2개 이상, 아니면 [원문]
    auto: bool = False
    suggestion: list[str] | None = None    # 자동 분할하지 않은 여러 동작 단계의 나누기 초안
    reason: str | None = None              # "multi_action" | "negation" | None
    actions: int = 1
    why_not: list[str] = field(default_factory=list)   # 자동으로 나누지 않은 이유(평가·디버그용)
    # 초안 중 대상이 빠진 칸 번호(0부터) — 검토 화면이 그 칸에 "무엇을 하는지 적어 주세요"를 띄운다.
    suggestion_gaps: list[int] | None = None
    source: str | None = None              # 자동 분할이면 원문(검토 화면의 '원래 문장으로 되돌리기'용)
    # 동작으로 세지 않은 동사 수(방법·사건·사고 앞 절, 보조 용언 묶음·연속 동사 "채워 넣다"). 0보다 크면 "동작 하나"
    # 판정이 낱말 목록에 기대고 있어 확실하지 않다 — GPT 분할과 어긋날 때 사업주 확인(split_check)을 띄우는 근거.
    hidden_verbs: int = 0
    # 나눌지가 말뜻에 기대는 꼴 — 규칙과 GPT가 같은 수로 나눠도 사업주가 한 번 볼 만하다(split_check):
    # 앞 동작이 이동("가서 쉬다"는 쉬기 하나일 수도, "가서 여쭤보다"는 둘일 수도), 따옴표 속 말("받아서 '…' 하고
    # 말하다"는 전화 받는 장면 하나일 수도).
    soft_boundary: bool = False
    # 동작 하나라는 판정을 규칙이 꼴로 설명할 수 있는가 — GPT가 나눴는데 규칙이 하나라고 할 때, 이 근거가 있으면
    # 확인 없이 합친다(입력 화면 나누기 1차 검증): 대상 나열("컵과 접시를 닦다" → 물건별로 나누지 않는다),
    # 갈라 담기("크기별로 나눠 담다"), 동시 동작 '-며/-면서'("소독하며 닦다").
    list_object: bool = False
    sorted_into: bool = False
    with_joined: bool = False
    # 초안 문장을 만들 수는 있었지만 앞 절 동사가 일부러 하는 일 목록 밖이거나 앞 절에 '-게' 부사가 있어(not_deliberate·
    # degree_adverb만 걸림) 제안으로 내지 않은 것. 사업주가 쉼표로 이미 끊어 쓴 문장('~고,')을 쉼표에서 나눌 때 문장 모양으로 쓴다(decompose._comma_cut_ok).
    comma_draft: list[str] | None = None
    # 초안을 막은 뜻 위험(_first_verb_blockers: 다른 주어·지시 아님·'X는 빼고'·정도 부사·'다시' …). 부정·세지 않은
    # 동작 때문에 일찍 돌아간 판정은 None이다.
    draft_blockers: list[str] | None = None
    # '-고/-어서'로 이어진 앞 절 중 동작으로 세지 않은 것(방법·사건·사고)의 동사 원형 — 규칙 경로가 "누르고
    # 기다리다"처럼 방법 동사로 본 앞 동작이 실은 따로 그림이 필요한지 확인을 띄우는 데 쓴다("눌러 뚫다"는 넣지 않는다).
    hidden_lemmas: frozenset[str] = frozenset()
    # 사전에 없는 동사가 '-(으)ㄴ 뒤/후/다음' 앞에 있다("물을 끓인 뒤 …") — 동작일 수 있는데 세지 못했다.
    unparsed_verbs: int = 0
    # 형식 동사 '하다'의 연결형·조건에 묶인 연결형처럼 동작일 수 있는데 세지 않은 어절 수(_Sentence.unseen_verbs).
    unseen_verbs: int = 0


@lru_cache(maxsize=1)
def _analyzer() -> kv.Analyzer | None:
    """매칭과 같은 동사 사전(그림 원형). 그림 데이터를 못 읽으면 None — 나누지 않는다."""
    try:
        import local_aac
        return local_aac._verb_analyzer()
    except Exception as e:  # noqa: BLE001 - 사전이 없어도 분해는 돼야 한다
        logger.warning("동사 사전을 못 읽어 단계 나누기를 끕니다: %s", e)
        return None


@lru_cache(maxsize=1)
def _noun_vocab() -> frozenset[str]:
    try:
        import local_aac
        return local_aac._asset_noun_vocab()
    except Exception:  # noqa: BLE001
        return frozenset()


def _final_of(word: str) -> int:
    """마지막 글자의 받침 번호(없으면 0, 한글이 아니면 -1)."""
    parts = kv._split(word[-1]) if word else None
    return parts[2] if parts is not None else -1


def _has_final(word: str) -> bool:
    """마지막 글자에 받침이 있는가."""
    return _final_of(word) > 0


def _josa(noun: str) -> str:
    return "을" if _has_final(noun) else "를"


def _is_adjective(lemma: str) -> bool:
    stem = lemma[:-1]
    if stem.endswith("하"):
        stem = stem[:-1]
    return stem in _ADJ_STEMS


def _is_person(noun: str) -> bool:
    """근로자가 아닌 사람 명사인가(손님·팀장님·택배 기사·동료)."""
    return noun.endswith("님") or any(noun == p or noun.endswith(p) for p in PERSON_NOUNS)


def has_negation(text: str, analyzer: kv.Analyzer | None = None) -> bool:
    """부정 표현이 있는가. '안/못'은 뒤가 동사일 때만 부정으로 본다("차 안 바닥"의 '안'은 자리)."""
    if _NEGATION_RE.search(text):
        return True
    words = kv._TOKEN_RE.findall(text)
    an = analyzer or _analyzer()
    for i, w in enumerate(words[:-1]):
        if w in _NEGATION_ADVERBS and (an is None or an.analyze_word(words[i + 1])):
            return True
    return False


@dataclass
class _Action:
    head: int          # 동사 어절(원형을 가진 어절)
    end: int           # 경계 어절(보조 용언까지 포함한 마지막 어절)
    stop: int          # 이 동작 절의 마지막 어절(-고 나서의 '나서', -ㄴ 다음에의 '다음에' 포함)
    lemmas: frozenset[str]
    boundary: str | None = None   # "go" | "seo" | "adn" | "bare" | "other" | None(마지막 동작)
    compound: bool = False        # 보조 용언 묶음·연속 동사·한 어절 안 보조 용언
    manner: bool = False


class _Sentence:
    def __init__(self, text: str, an: kv.Analyzer, question: bool = False) -> None:
        self.text = text
        self.question = question   # 원문에서 이 조각 뒤에 물음표가 있었다
        self.an = an
        self.matches = list(kv._TOKEN_RE.finditer(text))
        self.words = [m.group() for m in self.matches]
        self.own = [an.analyze_word(w) for w in self.words]
        self.parses: list[list[kv.Parse]] = [[] for _ in self.words]
        for idx, p in an.analyze_text(text):
            self.parses[idx].append(p)
        self.quoted = self._quoted_mask()
        self.kind = self._effective_kinds()

    def _quoted_mask(self) -> list[bool]:
        out = []
        for m in self.matches:
            before = self.text[:m.start()]
            out.append(sum(before.count(q) for q in _QUOTE_CHARS) % 2 == 1)
        return out

    def _effective_kinds(self) -> dict[int, str]:
        """어절의 대표 종류. 조건절 앞 연결형은 조건절 범위다(lemma_roles와 같은 규칙):
        "점심 먹고 오면"의 '먹고'는 할 일이 아니다. '-고 간/온'("두고 간 옷")은 관형절이다."""
        rep: dict[int, str] = {}
        for i, ps in enumerate(self.parses):
            if ps:
                main = [p for p in ps if p.kind in kv.MAIN_KINDS]
                rep[i] = (main or ps)[0].kind
        out: dict[int, str] = {}
        following = None
        # 조건절로 묶인 연결형 어절("맡아 보고 이상하면"의 '보고') — 동작으로 세지 않지만 동작일 수 있다(unseen_verbs).
        self.cond_absorbed: set[int] = set()
        for i in sorted(rep, reverse=True):
            k = rep[i]
            if k in (kv.CONN, kv.BARE) and following == kv.COND:
                k = kv.COND
                self.cond_absorbed.add(i)
            elif (k == kv.CONN and out.get(i + 1) == kv.EXCL
                  and {p.lemma for p in self.parses[i + 1]} & kv.MOTION_VERBS):
                k = kv.EXCL
            out[i] = k
            following = k
        return out

    # 어절 성격 ------------------------------------------------------------------------
    def is_verb_word(self, i: int) -> bool:
        return bool(self.own[i]) or bool(self.parses[i])

    def comma_after(self, i: int) -> bool:
        """i 어절 바로 뒤(다음 어절 앞)에 쉼표가 있는가."""
        stop = self.matches[i + 1].start() if i + 1 < len(self.matches) else len(self.text)
        return any(c in self.text[self.matches[i].end():stop] for c in ",，")

    def _aux_word(self, j: int) -> bool:
        return (not self.parses[j]) and any(q.lemma in kv._AUX_OR_PASSIVE for q in self.own[j])

    def group_end(self, i: int) -> int:
        j = i
        while j + 1 < len(self.words) and self._aux_word(j + 1):
            j += 1
        return j

    def is_object(self, j: int) -> bool:
        w = self.words[j]
        return (len(w) >= 2 and w.endswith(("을", "를")) and not self.quoted[j]
                and not self.is_verb_word(j) and re.fullmatch(r"[가-힣]+", w) is not None)

    def is_topic(self, j: int) -> bool:
        """주제어(-은/-는) 명사인가. 자리·때 말(점심시간에는·창고에서는)과, 명사가 아닌데 바로 뒤에 명사가 오는
        꾸밈말 꼴(작은 상자를·젖은 수건을 — 분석기 사전에 없는 형용사)은 주제어가 아니다."""
        w = self.words[j]
        if not (len(w) >= 2 and w.endswith(("은", "는")) and not self.quoted[j]
                and not self.is_verb_word(j) and re.fullmatch(r"[가-힣]+", w) is not None):
            return False
        if w.endswith(_LOCATIVE_TOPICS):
            return False
        noun = w[:-1]
        if noun in _noun_vocab() or _is_person(noun):
            return True
        nxt = j + 1
        if nxt < len(self.words) and not self.is_verb_word(nxt) and (
                self.words[nxt] in _noun_vocab() or self.words[nxt].endswith(("을", "를", "은", "는", "이", "가"))):
            return False
        return True

    def is_subject(self, j: int) -> bool:
        """조사 '-이/-가'가 붙은 명사인가. 받침에 맞는 조사만 본다(컵이 / 바구니가)."""
        w = self.words[j]
        if (len(w) < 2 or self.quoted[j] or self.is_verb_word(j) or w in _I_ADVERBS
                or w in _noun_vocab() or re.fullmatch(r"[가-힣]+", w) is None):
            return False
        stem = w[:-1]
        half = len(stem) // 2
        if w.endswith("이") and len(stem) % 2 == 0 and half and stem[:half] == stem[half:]:
            return False   # 첩어 부사(줄줄이·겹겹이·틈틈이)
        if w.endswith("이"):
            return _has_final(stem)
        if w.endswith("가"):
            return not _has_final(stem)
        return False

    def _after_bare(self, i: int) -> bool:
        """i 어절 바로 앞이 '-어' 꼴(엎어·빼·꺼내) 또는 '갖다/가져다'인가 — 그러면 i의 두다·놓다·주다·오다는
        보조 용언이다("엎어 두고", "갖다 두고"). 사전에 없는 동사의 '-어' 꼴은 겉모양으로 본다."""
        j = i - 1
        if j < 0 or self.quoted[j]:
            return False
        w = self.words[j]
        if w in kv._CARRY_WORDS or any(q.kind == kv.BARE for q in self.own[j]):
            return True
        return (not self.parses[j] and not self.own[j]
                and re.search(r"(?:어|아|여|워|와|해|봐|줘|놔|둬|려|겨|켜|쳐|혀|펴|껴)$", w) is not None)

    def _serial_next(self, end: int) -> bool:
        """'-어'형 바로 뒤가 사전 동사의 할 일 어절인가(연속 동사). '유통기한'처럼 'X하다' 폴백으로만
        읽히는 명사는 동사로 보지 않는다."""
        j = end + 1
        if j >= len(self.words) or self.quoted[j] or self.kind.get(j) not in kv.MAIN_KINDS:
            return False
        return any(p.lemma in self.an.lemmas for p in self.parses[j])

    def _compound_span(self, i: int) -> frozenset[str]:
        """i 어절의 해석 중 다음 어절까지 걸친 합성 동사 원형(analyze_text가 붙여 본 것)."""
        w = self.words[i]
        return frozenset(p.lemma for p in self.parses[i]
                         if p.kind in kv.MAIN_KINDS and len(p.lemma) - 1 > len(w) and i + 1 < len(self.words))

    def main_lemmas(self, i: int) -> frozenset[str]:
        return frozenset(p.lemma for p in self.parses[i] if p.kind in kv.MAIN_KINDS)

    # 동작 찾기 ------------------------------------------------------------------------
    def actions(self) -> list[_Action]:
        n = len(self.words)
        out: list[_Action] = []
        i = 0
        pending_serial = False
        while i < n:
            if not self.parses[i] or self.quoted[i]:
                i += 1
                continue
            kind = self.kind.get(i)
            lemmas = self.main_lemmas(i)
            end = self.group_end(i)
            if kind in kv.MAIN_KINDS:
                if not lemmas or lemmas <= kv._LIGHT_VERBS or all(_is_adjective(lm) for lm in lemmas):
                    i = end + 1
                    continue
                if self.words[i] in kv._CARRY_WORDS and end + 1 < n and self.parses[end + 1]:
                    pending_serial = True   # "갖다 놓으세요"의 '갖다'는 뒤 동작에 딸린 말 — 뒤 동작은 묶음이다
                    i = end + 1
                    continue
                if kind == kv.BARE and self._serial_next(end):
                    pending_serial = True   # "눌러 맞추세요" — 다음 동사와 한 동작
                    i = end + 1
                    continue
                span = self._compound_span(i)
                if span:
                    # 띄어 쓴 합성 동사("밀어 넣으세요" → 밀어넣다) — 다음 어절까지 한 동작
                    lemmas = span
                    pending_serial = True
                    end = self.group_end(i + 1)
                    kind = self.kind.get(i + 1, kind)
                compound = (pending_serial or end != i or any(p.aux for p in self.parses[i])
                            or (bool(lemmas & kv._AUX_OR_PASSIVE) and self._after_bare(i)))
                pending_serial = False
                act = _Action(head=i, end=end, stop=end, lemmas=lemmas, compound=compound)
                act.manner = bool(lemmas & MANNER_VERBS)
                word = self.words[end]
                if act.manner and kind == kv.CONN and word.endswith("고") and self.comma_after(end):
                    # '-고,'처럼 쉼표로 끊어 쓴 순차 연결이면 방법 동사도 따로 하는 동작이다("컵에 물을 따르고, 테이블에
                    # 놓으세요"). 방법으로 빼는 것은 쉼표 없는 연결("손잡이를 잡고 당기세요")일 때만(2차 검증).
                    act.manner = False
                if kind == kv.CONN:
                    if word.endswith(("고", "고서")) and not word.endswith("다고"):
                        act.boundary = "go"
                        if end + 1 < n and self.words[end + 1] == "나서":
                            act.stop = end + 1
                    elif word.endswith("서") and not word.endswith("면서"):
                        act.boundary = "seo"
                    elif word.endswith(("며", "면서")):
                        act.boundary = "with"   # 동시 동작 — 뒤 동작과 한 단계
                    else:
                        act.boundary = "other"  # -다가·-거나·-지·-도 …
                elif kind == kv.BARE:
                    act.boundary = "bare"
                out.append(act)
                i = act.stop + 1
                continue
            if (kind == kv.EXCL and end + 1 < n and self.words[end + 1] in _TEMPORAL_NOUNS
                    and lemmas == frozenset() and self.parses[i]):
                lem = frozenset(p.lemma for p in self.parses[i])
                if not (lem <= kv._LIGHT_VERBS) and any(self.kind.get(j) in kv.MAIN_KINDS
                                                        for j in range(end + 2, n)):
                    act = _Action(head=i, end=end, stop=end + 1, lemmas=lem, boundary="adn",
                                  compound=end != i)
                    act.manner = bool(lem & MANNER_VERBS)
                    out.append(act)
                    i = act.stop + 1
                    continue
            i = end + 1
        # 동시 동작(-며)은 뒤 동작에 합친다.
        merged: list[_Action] = []
        self.with_joined = False
        for a in out:
            if merged and merged[-1].boundary == "with":
                merged[-1] = a
                self.with_joined = True
                continue
            merged.append(a)
        if merged:
            merged[-1].boundary = None
        return merged

    def unseen_verbs(self) -> int:
        """동작 찾기(actions)가 세지 않았지만 따로 그림이 필요한 동작일 수 있는 어절 수. "동작 하나" 판정이 낱말 목록에
        기대고 있다는 표시(hidden_verbs)에 더한다(입력 화면 나누기 1차 검증):
        - 대상 뒤 형식 동사 '하다'의 연결형("창고 정리를 하고 퇴근하세요") — 동작 찾기는 하다를 건너뛴다.
        - 조건절로 묶인 연결형("냄새를 맡아 보고 이상하면 버리세요"의 '보고') — '먹고 오면'처럼 조건의 일부일 수도,
          '보고 / (이상하면) 버리다'처럼 따로 할 일일 수도 있다."""
        n = 0
        for i in range(len(self.words) - 1):
            if self.quoted[i] or not self.parses[i]:
                continue
            lemmas = frozenset(p.lemma for p in self.parses[i])
            if i in self.cond_absorbed:
                if not lemmas <= kv._LIGHT_VERBS and not all(_is_adjective(lm) for lm in lemmas):
                    n += 1
            elif (self.kind.get(i) == kv.CONN and lemmas <= {"하다"} and i > 0 and self.is_object(i - 1)):
                n += 1
        return n

    def unparsed_adnominals(self) -> int:
        """사전에 없는 말이 관형형 꼴(끝 받침 ㄴ)로 '뒤·후·다음' 앞에 있고 그 뒤에 할 일 동사가 오는 어절 수.
        "물을 끓인 뒤 티백을 넣으세요"의 '끓인'처럼 동작인데 동작 찾기(actions)가 원형을 몰라 건너뛴다(2차 검증)."""
        n = 0
        for i in range(len(self.words) - 1):
            w = self.words[i]
            if (self.parses[i] or self.own[i] or self.quoted[i] or len(w) < 2 or _final_of(w) != 4
                    or w in _noun_vocab() or self.words[i + 1] not in _TEMPORAL_NOUNS):
                continue
            if any(self.kind.get(j) in kv.MAIN_KINDS for j in range(i + 2, len(self.words))):
                n += 1
        return n

    def clause_has_event_subject(self, lo: int, hi: int) -> bool:
        """[lo, hi)에 주어(-이/-가)가 있는가. 조건절·관형절("전화가 울리면", "손님이 입어 본 옷")의
        주어는 그 절 것이라 세지 않는다 — 마지막 비서술 동사 어절 뒤부터 본다."""
        start = self._main_start(lo, hi)
        return any(self.is_subject(j) for j in range(start, hi))

    def _main_start(self, lo: int, hi: int) -> int:
        """[lo, hi)에서 조건절·관형절이 끝난 뒤(마지막 비서술 동사 어절 다음) 위치."""
        start = lo
        for j in range(lo, hi):
            if self.parses[j] and self.kind.get(j) not in kv.MAIN_KINDS:
                start = j + 1
        return start

    def clause_other_subject(self, lo: int, act: _Action) -> bool:
        """앞 절 동작을 근로자가 아닌 사람이 하는가(모듈 설명 A-4).

        -이/-가 주어, -께서, 사람 주어(손님이), 사람 주제어(손님은·팀장님은), 대상이 따로 있는데 붙은 주제어
        (주제어가 주어다: "동료는 상자를 열고"), 앞 절 동사의 높임 '-시-'(고르시고·드신 후에)."""
        hi = act.head
        start = self._main_start(lo, hi)
        # 사전에 없는 관형형(지난·깨진)은 분석기가 못 읽어 _main_start가 관형절을 못 건너뛴다. 대상 명사 바로 앞이
        # 관형형 꼴(받침 ㄴ·ㄹ)이면 그 앞의 사람 아닌 주어는 관형절 주어로 본다("유통기한이 지난 우유를").
        obj = self.clause_object(start, hi)
        rel_end = obj - 1 if obj is not None and obj - 1 >= start and _final_of(self.words[obj - 1]) in (4, 8)             and not self.is_object(obj - 1) and not self.is_topic(obj - 1) else start
        for j in range(start, hi):
            if self.is_subject(j) and not (j < rel_end and not _is_person(self.words[j][:-1])):
                return True
        for j in range(lo, hi):
            w = self.words[j]
            if self.quoted[j] or self.is_verb_word(j):
                continue
            if w.endswith("께서"):
                return True
            if j >= start and w.endswith(("이", "가")) and len(w) >= 2 and _is_person(w[:-1]):
                return True
        topic = self.clause_topic(start, hi)
        if topic is not None:
            if _is_person(self.words[topic][:-1]) or self.clause_object(start, hi) is not None:
                return True
        for k in range(act.head, act.end + 1):
            w = self.words[k]
            if _HONORIFIC_RE.search(w):
                own_forms = set()
                for lm in act.lemmas:
                    f = conjugate.conjugate(lm)
                    if f is not None:
                        own_forms |= {f.go, f.go + "서", f.adnominal, *f.seo(), *f.a}
                if w not in own_forms:
                    return True
        return False

    def clause_mishap(self, lo: int, hi: int) -> bool:
        """[lo, hi]에 실수 부사(잘못·실수로·깜빡)가 있는가."""
        return any(self.words[j] in MISHAP_ADVERBS for j in range(lo, min(hi + 1, len(self.words))))

    def clause_has_embedded_question(self, lo: int, hi: int) -> bool:
        """[lo, hi)에 '-는지/-은지' 절이 있는가("잠겼는지 확인하세요" — 대상 자리를 채운다)."""
        return any(w.endswith("지") and len(w) >= 2 and _final_of(w[:-1]) == 4
                   for w in self.words[lo:hi])

    def clause_object(self, lo: int, hi: int) -> int | None:
        """[lo, hi)에서 대상(-을/-를) 어절 번호(마지막 것)."""
        found = None
        for j in range(lo, hi):
            if self.is_object(j):
                found = j
        return found

    def clause_topic(self, lo: int, hi: int) -> int | None:
        found = None
        for j in range(lo, hi):
            if self.is_topic(j):
                found = j
        return found

    def clause_has_condition(self, lo: int, hi: int) -> bool:
        """[lo, hi)에 조건·때·까닭 절이 있는가. 사전에 없는 동사의 '-(으)면'(녹으면)·'-(으)니까'(미끄러우니)는
        겉모양으로 본다 — 명사(라면·화면)는 그림 명사 사전에 있으면 뺀다."""
        for j in range(lo, hi):
            if self.kind.get(j) == kv.COND or self.words[j] in _TIME_WORDS:
                return True
            w = self.words[j]
            if (not self.quoted[j] and w not in _noun_vocab() and len(w) >= 2
                    and ((w.endswith("면") and not w.endswith("면서")) or w.endswith(_REASON_ENDINGS)
                         or w.endswith(_COND_ENDINGS))):
                return True
            if self.kind.get(j) == kv.EXCL and j + 1 < len(self.words) and self.words[j + 1] in _TIME_WORDS:
                return True
        return False


# ---- 활용 -----------------------------------------------------------------------------------

def _certain_lemma(s: _Sentence, act: _Action) -> str | None:
    """경계 어절의 원형 — 분석기 후보가 하나이고, 사전에 있고, 활용표가 있을 때만."""
    if len(act.lemmas) != 1:
        return None
    lemma = next(iter(act.lemmas))
    if lemma not in s.an.lemmas or _is_adjective(lemma) or lemma in kv._LIGHT_VERBS:
        return None
    if conjugate.conjugate(lemma) is None:
        return None
    return lemma


def _ending_ok(s: _Sentence) -> bool:
    """지시하는 문장인가. 끝맺음이 '-(으)세요'(…주세요·…두세요 포함)이거나 현재 '-아요/-어요'(담아요·둬요)여야 한다.
    물음표·묻는 말(어디·몇·왜)·물음/약속 끝맺음(-ㄹ까요·-ㄹ게요·-나요·-ㄹ래요)·과거(넣었어요)·'-어야 해요'·
    '-도 돼요'·'-면 돼요'는 지시가 아니다 — 떼어 내 지시형으로 바꾸면 물음이 명령이 된다."""
    if not s.words or s.question or any(c in s.text for c in "?？"):
        return False
    if any(not s.quoted[j] and (w == "왜" or w.startswith(_QUESTION_PREFIXES)) for j, w in enumerate(s.words)):
        return False
    last = s.words[-1]
    if last.endswith(_NON_INSTRUCTION_ENDINGS):
        return False
    if last.endswith("세요"):
        return True
    if not last.endswith("요"):
        return False
    for p in s.an.analyze_word(last):
        if p.lemma in kv._LIGHT_VERBS or p.lemma in ("하다", "되다"):
            continue
        forms = conjugate.conjugate(p.lemma)
        if forms is not None and last in {a + "요" for a in forms.a}:
            return True
    return False


def _style(s: _Sentence) -> str | None:
    """원문 끝맺음: '…세요' → "seyo", 그 밖의 '…요'(담아요·올려 두어요) → "yo". 지시가 아닌 문장(_ending_ok)과
    다른 끝맺음은 나누지 않는다."""
    if not _ending_ok(s):
        return None
    last = s.words[-1] if s.words else ""
    if last.endswith("세요"):
        return "seyo"
    if last.endswith("요"):
        return "yo"
    return None


def text_style(text: str) -> str | None:
    """원문 한 문장의 말투 — '…세요'면 "seyo", 그 밖의 지시 '…요'(담아요·올려요)면 "yo", 지시가 아니면 None."""
    an = _analyzer()
    body = text.strip().rstrip(".!。 ")
    if an is None or not body:
        return None
    return _style(_Sentence(body, an))


def restyle(sentence: str, style: str | None) -> str:
    """GPT 단계 문장의 끝맺음을 사업주 원문 말투로 맞춘다(2026-11-13 그림 정확도 조사: '~해요'로 쓴 지시문의
    단계 100개 중 96개를 GPT가 '~세요'로 바꿨다).

    원문이 '-아요/-어요'(style "yo")인데 단계 문장이 '…세요'로 끝날 때만 바꾼다. 끝 어절의 원형이 하나로만 읽히고,
    활용기의 '-(으)세요' 꼴이 그 어절과 글자 그대로 같고, 바꾼 '-아요/-어요' 꼴을 다시 읽어도 그 원형 하나일 때만
    ('넣으세요' → '넣어요', '살펴보세요' → '살펴봐요'). '쓰세요'(쓰다/쓸다)·'끄세요'처럼 읽기가 둘이면 그대로 둔다.
    사전에 없는 'X하세요'(결제하세요)는 'X해요'로 바꾼다. 따옴표 속 말은 건드리지 않는다."""
    if style != "yo":
        return sentence
    an = _analyzer()
    body = sentence.rstrip()
    end = ""
    while body and body[-1] in ".!":
        end = body[-1] + end
        body = body[:-1]
    m = re.search(r"([가-힣]+)$", body)
    if an is None or m is None or not m.group(1).endswith("세요"):
        return sentence
    word = m.group(1)
    if body[:m.start()].count('"') % 2 or body[:m.start()].count("'") % 2:
        return sentence   # 따옴표가 닫히지 않았다 — 끝 어절이 인용 속 말이다
    lemmas = {q.lemma for q in an.analyze_word(word)}
    if not lemmas and word.endswith("하세요") and len(word) > 3:
        new = word[:-3] + "해요"
    elif len(lemmas) == 1:
        lemma = next(iter(lemmas))
        forms = conjugate.conjugate(lemma)
        if forms is None or forms.polite != word:
            return sentence
        new = imperative(lemma, "yo")
        if not new or " " in new or {q.lemma for q in an.analyze_word(new)} != {lemma}:
            return sentence
    else:
        return sentence
    return body[:m.start()] + new + end


def imperative(lemma: str, style: str) -> str | None:
    """원형의 지시형(앞 절 끝 어절을 바꿀 말). 확실하지 않으면 None.

    seyo: '-(으)세요'. ㄹ 어간은 ㄹ이 떨어진 꼴(써세요·거세요·빠세요·터세요)이 다른 동사로 읽혀 '-어 주세요'로 쓴다.
    yo:   '-아요/-어요'. '…세요'로 끝나 높임 지시형처럼 보이는 꼴(세다 → 세요)과 '놔요'는 풀어 쓴 꼴을 고른다.
    """
    forms = conjugate.conjugate(lemma)
    if forms is None:
        return None
    rieul = _final_of(lemma[:-1]) == 8
    if style == "seyo":
        if rieul and lemma not in RIEUL_POLITE_OK:
            return f"{forms.a[0]} 주세요"
        return forms.polite
    if style == "yo":
        stem = lemma[:-1]
        for a in forms.a:
            word = a + "요"
            # 세요(세다)·개요(개다)는 다른 말로 읽힌다 → 풀어 쓴 꼴(세어요·개어요). 그 밖에는 줄인 꼴(빼요·매요).
            if word.endswith("세요") or a.endswith("놔") or word in _YO_AMBIGUOUS:
                continue
            if len(stem) == 1 and a != stem and stem + "요" not in _YO_AMBIGUOUS and stem in forms.a:
                continue   # 줄인 꼴(빼)이 뒤에 있으면 그것을 고른다
            return word
    return None


def _reads_as(phrase: str, lemma: str, an: kv.Analyzer) -> bool:
    """만든 지시형을 분석기로 다시 읽어도 그 원형 하나로만 읽히는가('-어 주세요'는 앞 어절을 본다)."""
    words = phrase.split()
    word = words[0]
    if len(words) == 2:
        if conjugate.is_homograph_a_form(word):
            return False
    lemmas = {q.lemma for q in an.analyze_word(word)}
    if lemma not in lemmas:
        return False
    # 다른 읽기가 ㄹ 탈락 읽기뿐이면 괜찮다(끄세요: 끄다 / 끌다). 활용기는 그런 ㄹ 어간의 '-세요'를 만들지 않고
    # (Forms.polite=None) 이 겉모양을 받침 없는 동사의 것으로 정해 두었다.
    for other in lemmas - {lemma}:
        forms = conjugate.conjugate(other)
        if _final_of(lemma[:-1]) == 8 or forms is None or _final_of(other[:-1]) != 8 or forms.polite is not None:
            return False
    return True


def _rewrite_boundary(s: _Sentence, act: _Action, style: str | None) -> str | None:
    """경계 어절(연결형)을 지시형으로 바꾼 것. 겉모양이 활용기와 글자 그대로 같아야 한다."""
    if act.compound or style is None:
        return None
    lemma = _certain_lemma(s, act)
    if lemma is None:
        return None
    forms = conjugate.conjugate(lemma)
    word = s.words[act.end]
    if act.boundary == "go":
        ok = word in (forms.go, forms.go + "서")
    elif act.boundary == "seo":
        body = word[:-1]
        ok = word in forms.seo() and not conjugate.is_homograph_a_form(body)
    elif act.boundary == "bare":
        ok = word in forms.a and not conjugate.is_homograph_a_form(word)
    elif act.boundary == "adn":
        # 받침 있는 어간의 '-은'과 '-한'만 — 받침 없는 어간의 '-ㄴ'(쓴: 쓰다/쓸다)은 원형이 갈린다.
        ok = word == forms.adnominal and (word.endswith("은") or lemma.endswith("하다"))
    else:
        ok = False
    if not ok:
        return None
    imp = imperative(lemma, style)
    if imp is None or not _reads_as(imp, lemma, s.an):
        return None
    return imp


# ---- 문법 자가 검사 -------------------------------------------------------------------------

_PARTICLES = ("을", "를", "이", "가", "은", "는", "에", "로", "의", "도")


def _grammar_ok(sentence: str, an: kv.Analyzer, carried: bool = False) -> bool:
    """만든 단계 문장의 겉모양 검사. 하나라도 어긋나면 그 문장을 쓰지 않는다.

    - 두 어절 이상이고 마침표로 끝난다.
    - 마지막 어절이 '-요'·'-십시오'로 끝나는 종결 서술어로 분석된다.
    - 마지막 어절 말고는 이어지는 동작(연결형 -고/-어서, 어미 없는 -어)이 남지 않았다.
    - 동사 활용형에 조사가 붙은 어절이 없다("엎어를", "접고를").
    - 대상을 넘겨 붙인 문장(carried)에는 조건·때 꼴이 없다("아이스크림을 녹으면 버리세요").
    """
    if not sentence.endswith(".") or "  " in sentence:
        return False
    body = sentence[:-1].strip()
    words = kv._TOKEN_RE.findall(body)
    if len(words) < 2:
        return False
    last = words[-1]
    if not last.endswith(("요", "십시오")) or last.endswith(_NON_INSTRUCTION_ENDINGS) or "?" in sentence:
        return False
    parsed = an.analyze_text(body)
    last_idx = len(words) - 1
    if not any(q.kind == kv.FINAL for q in an.analyze_word(last)):
        return False
    for i, p in parsed:
        if carried and (p.kind == kv.COND or words[i] in _TIME_WORDS):
            return False
        if i < last_idx and p.kind in (kv.CONN, kv.BARE):
            # 연속 동사·보조 용언 앞 '-어'형은 괜찮다(바로 뒤가 동사).
            if p.kind == kv.BARE and i + 1 <= last_idx and an.analyze_word(words[i + 1]):
                continue
            return False
    if carried and any(w in _TIME_WORDS for w in words):
        return False
    for w in words:
        if an.analyze_word(w) or not w.endswith(_PARTICLES) or len(w) < 2:
            continue
        stem = w[:-1]
        if any(q.kind in (kv.BARE, kv.CONN, kv.FINAL) for q in an.analyze_word(stem)):
            return False
    return True


# ---- 대상 명사구 ------------------------------------------------------------------------------

# 나열 표시: '컵과', '컵이나', '컵이든지' / 낱말 '또는·혹은·및'
_COORD_ENDINGS = ("와", "과", "랑", "이랑", "하고", "및", "이나", "나", "든지", "이든지", "거나")
_COORD_WORDS = frozenset({"또는", "혹은", "및", "아니면"})


def _object_word(s: _Sentence, lo: int, hi: int, lemma: str | None) -> int | None:
    """절의 대상 어절: -을/-를, 없으면(대상을 받는 손질 동사일 때) 주제어 -은/-는."""
    j = s.clause_object(lo, hi)
    if j is None and lemma in TOPIC_OBJECT_VERBS:
        j = s.clause_topic(lo, hi)
        if j is not None and _is_person(s.words[j][:-1]):
            return None
    return j


def _gap(s: _Sentence, j: int) -> str:
    """j-1 어절과 j 어절 사이의 원문(띄어쓰기·쉼표)."""
    return s.text[s.matches[j - 1].end():s.matches[j].start()]


def _bare_noun(s: _Sentence, k: int) -> bool:
    return s.words[k] in _noun_vocab() and not s.is_verb_word(k) and not s.quoted[k]


def _is_list(s: _Sentence, j: int, lo: int) -> bool:
    """대상이 나열인가 — '와/과·이나/나·든지'로 이음, '또는·혹은·및', 쉼표, 띄어 쓴 그림 명사 둘 이상("컵 접시 수저를")."""
    if j - 1 < lo:
        return False
    if any(c in _gap(s, j) for c in ",，·"):
        return True
    prev = s.words[j - 1]
    if prev in _COORD_WORDS:
        return True
    if prev.endswith(_COORD_ENDINGS) and not s.is_verb_word(j - 1):
        return True
    if j - 2 >= lo:
        if s.words[j - 2] in _COORD_WORDS:
            return True
        if _bare_noun(s, j - 1) and _bare_noun(s, j - 2):
            return True
        p2 = s.words[j - 2]
        if p2.endswith(_COORD_ENDINGS) and not s.is_verb_word(j - 2) and _bare_noun(s, j - 1):
            return True
    return False


def _object_np(s: _Sentence, j: int, lo: int) -> str | None:
    """대상 어절의 명사구(조사를 뗀 것). 꾸밈말이 있으면 꾸밈말까지 통째로. 경계가 불확실하면 None.

    - 대상이 절 맨 앞(앞 부사만 있음)이거나 바로 앞말이 장소·도구 말("냉장고에서 우유를")이면 명사만.
    - 바로 앞말이 꾸밈말 꼴(받침 ㄴ·ㄹ: 깨진·남은·지난·다 쓴)이거나 그림 명사(테이프 심)이면 절 앞(앞 부사 뒤)부터
      명사까지 전부("유통기한이 지난 우유", "다 쓴 테이프 심"). 사이에 다른 대상·주제어·쉼표·따옴표가 있으면 None.
    - 나열("컵 접시 수저를", "컵이나 접시를")이면 None.
    """
    noun = s.words[j][:-1]
    if not noun or re.fullmatch(r"[가-힣]+", noun) is None or s.an.analyze_word(noun):
        return None
    if _is_list(s, j, lo):
        return None
    start = lo
    # 앞 부사와 절 맨 앞 출발 자리('선반에서')는 넘기지 않는다 — "선반에서 깨진 병을 버리세요"는 선반에서 버리라는
    # 말로 읽힌다.
    while start < j and (s.words[start] in _LEAD_ADVERBS
                         or (s.words[start].endswith("에서") and not s.is_verb_word(start))):
        start += 1
    prev = s.words[j - 1] if j - 1 >= start else None
    if prev is None or (prev.endswith(_LOC_ENDINGS) and not s.is_verb_word(j - 1)) or prev in _LEAD_ADVERBS:
        return None if noun in _DEPENDENT_NOUNS else noun
    if not (_final_of(prev) in (4, 8) or _bare_noun(s, j - 1)):
        return None
    for k in range(start, j):
        if s.quoted[k] or (k > start and any(c in _gap(s, k) for c in ",，·")):
            return None
        if s.is_object(k) or s.is_topic(k):
            return None
    return s.text[s.matches[start].start():s.matches[j].start()] + noun


def _own_object(s: _Sentence, lo: int, hi: int) -> bool:
    """[lo, hi)에 제 대상(-을/-를·주제어·-도/-만)이 있는가."""
    return (s.clause_object(lo, hi) is not None or s.clause_topic(lo, hi) is not None
            or any(s.words[j].endswith(("도", "만")) and not s.is_verb_word(j) for j in range(lo, hi)))


def _has_tool(s: _Sentence, lo: int, hi: int) -> bool:
    """[lo, hi)에 도구·수단(또는 방향) '-로/-으로' 말이 있는가("물티슈로", "칼로", "창고로")."""
    return any(not s.quoted[j] and not s.is_verb_word(j) and len(s.words[j]) >= 2
               and s.words[j].endswith("로") and s.words[j] not in _RO_ADVERBS for j in range(lo, hi))


def _carries(s: _Sentence, acts: list[_Action]) -> list[str | None]:
    """절마다 앞에 붙일 대상("깨진 컵을"). 좁은 조건(모듈 설명 A)을 모두 만족할 때만, 아니면 None.

    뒤 절에 제 대상이 없고, 경계가 -고/-어서이고, 앞 동사가 대상을 그대로 남기는 손질(CARRY_SOURCE)이고,
    뒤 동사가 그 물건을 옮기거나 놓는 동작(CARRY_TARGET)이고, 뒤 절에 조건·때 꼴이 없고, 앞 절에 도구 '-로'가 없고
    ("물티슈로 손잡이를 닦고 버리세요"에서 버릴 것은 물티슈다), 대상이 몸이 아니고, 앞 대상의 명사구 경계가
    확실할 때만 붙인다.
    """
    out: list[str | None] = [None] * len(acts)
    lo = 0
    prev_lo = 0
    prev_np: str | None = None
    for k, act in enumerate(acts):
        if k > 0:
            prev = acts[k - 1]
            src = next(iter(prev.lemmas)) if len(prev.lemmas) == 1 else None
            if (prev_np and not _own_object(s, lo, act.head) and prev.boundary in ("go", "seo")
                    and src in CARRY_SOURCE and act.lemmas & CARRY_TARGET
                    and not s.clause_has_condition(lo, act.stop + 1)
                    and not _has_tool(s, prev_lo, prev.head)
                    and prev_np.split()[-1] not in NO_CARRY_NOUNS):
                out[k] = f"{prev_np}{_josa(prev_np)}"
        lemma = next(iter(act.lemmas)) if len(act.lemmas) == 1 else None
        j = _object_word(s, lo, act.head, lemma)
        prev_np = _object_np(s, j, lo) if j is not None else (out[k][:-1] if out[k] else None)
        prev_lo = lo
        lo = act.stop + 1
    return out


def _missing_objects(s: _Sentence, acts: list[_Action], carries: list[str | None]) -> list[int]:
    """대상이 있어야 뜻이 서는데 대상이 없는 절의 번호("손님께 드리세요"). 초안 칸에 '무엇을 하는지 적어 주세요'를
    띄우는 데 쓴다. 대상 없이 서는 동사(이동·기다리기)·'X하다' 동사·'-는지' 절이 있는 절은 뺀다."""
    out = []
    lo = 0
    for k, act in enumerate(acts):
        # 대상 표시는 느슨하게 본다('물을'처럼 동사로도 읽히는 말도 대상으로) — 헛 안내보다 빠뜨린 안내가 낫다.
        loose = any(w.endswith(("을", "를")) and len(w) >= 2 for w in s.words[lo:act.head])
        if (not carries[k] and not loose and not _own_object(s, lo, act.head) and not (act.lemmas & NO_OBJECT_OK)
                and not any(lm.endswith("하다") for lm in act.lemmas)
                and not s.clause_has_embedded_question(lo, act.head)):
            out.append(k)
        lo = act.stop + 1
    return out


# ---- 나누기 ------------------------------------------------------------------------------------

def _build(s: _Sentence, acts: list[_Action]) -> list[str] | None:
    """동작 경계마다 앞 절을 지시형으로 바꿔 단계 문장 목록을 만든다. 하나라도 못 만들면 None."""
    style = _style(s)
    if style is None:
        return None
    pieces: list[str] = []
    carries = _carries(s, acts)
    lo = 0
    for k, act in enumerate(acts):
        if k == len(acts) - 1:
            text = s.text[s.matches[lo].start():].strip().rstrip(".!?。 ")
        else:
            imp = _rewrite_boundary(s, act, style)
            if imp is None:
                return None
            head_text = s.text[s.matches[lo].start():s.matches[act.end].start()]
            text = (head_text + imp).strip()
        if carries[k]:
            text = f"{carries[k]} {text}"
        sentence = text + "."
        if not _grammar_ok(sentence, s.an, carried=bool(carries[k])):
            return None
        pieces.append(sentence)
        lo = act.stop + 1
    return pieces


# 초안 대상 잇기(_fill_gaps)에서 빼는 동사. 앞 동사가 살피기·세기면 뒤 동작의 대상은 그 물건이 아니고("동전을 세고
# 장부에 적으세요" — 적는 것은 센 수), 뒤 동사가 적기·알리기면 대상은 물건이 아니라 내용이다.
_NO_FILL_PREV = frozenset({"세다", "확인하다", "재다", "보다", "읽다", "고르다", "찾다", "계산하다", "결제하다",
                           "스캔하다", "점검하다", "살펴보다"})
_NO_FILL_NEXT = frozenset({"적다", "쓰다", "찍다", "기록하다", "말하다", "알리다", "부르다", "묻다", "여쭈다"})


def _fill_gaps(s: _Sentence, acts: list[_Action], pieces: list[str], gaps: list[int]) -> tuple[list[str], list[int]]:
    """나누기 초안(노란 줄)에서 대상이 빠진 뒤 단계에 앞 단계의 대상을 붙인다("걸레를 빨아서 짜 주세요" → "걸레를
    짜 주세요"). 초안은 사업주가 한 번 보는 줄이라 자동 분할(_carries)보다 넓게 붙이지만, 앞 절에 도구 '-로'가
    있거나(버릴 것이 도구일 수 있다) 대상이 몸이거나 뒤 절에 조건·때 꼴이 있으면 붙이지 않는다. 붙인 문장이 문법
    검사를 지나야 한다. 못 붙인 번호는 gaps에 남는다(2차 검증 — 뒤 단계에 '짜 주세요'만 남아 그림 검색어가 없었다)."""
    out = list(pieces)
    left: list[int] = []
    bounds: list[tuple[int, int]] = []
    lo = 0
    for act in acts:
        bounds.append((lo, act.head))
        lo = act.stop + 1
    for k in gaps:
        if k == 0 or k >= len(acts):
            left.append(k)
            continue
        plo, phi = bounds[k - 1]
        prev = acts[k - 1]
        lemma = next(iter(prev.lemmas)) if len(prev.lemmas) == 1 else None
        j = _object_word(s, plo, phi, lemma)
        np_ = _object_np(s, j, plo) if j is not None else None
        nlo = prev.stop + 1
        if (np_ is None or prev.boundary not in ("go", "seo", "bare") or _has_tool(s, plo, phi)
                or np_.split()[-1] in NO_CARRY_NOUNS or s.clause_has_condition(nlo, acts[k].stop + 1)
                or prev.lemmas & _NO_FILL_PREV or acts[k].lemmas & _NO_FILL_NEXT):
            left.append(k)
            continue
        cand = f"{np_}{_josa(np_)} {out[k]}"
        if _grammar_ok(cand, s.an, carried=True):
            out[k] = cand
        else:
            left.append(k)
    return out, left


def _next_lemma_ok(s: _Sentence, act: _Action) -> bool:
    """뒤 절 동사는 원문 그대로 두므로, 원형 후보 중 하나가 사전 낱말이고 활용이 확실하면 된다."""
    return any(lm in s.an.lemmas and lm not in kv._LIGHT_VERBS and not _is_adjective(lm)
               and conjugate.conjugate(lm) is not None for lm in act.lemmas)


def _is_degree_word(s: _Sentence, j: int) -> bool:
    """정도·평가 부사인가(덜·너무·대충·늦게 …, 방법 부사 목록 밖의 '-게' 꼴)."""
    w = s.words[j]
    if s.quoted[j] or w in HOWTO_ADVERBS:
        return False
    if w in DEGREE_ADVERBS:
        return True
    return (len(w) >= 2 and w.endswith("게") and not s.is_verb_word(j) and w not in _noun_vocab()
            and re.fullmatch(r"[가-힣]+", w) is not None)


def _first_verb_blockers(s: _Sentence, acts: list[_Action]) -> list[str]:
    """뜻이 바뀔 위험 — 자동 분할도 초안도 막는다(그대로 확정하면 손님에게 시키거나 실수·물음을 명령으로 바꾼
    문장이 된다). 앞 절(마지막 동작이 아닌 절)마다: 근로자가 아닌 주어, 일부러 하는 일 목록 밖의 동사,
    '-고' 앞의 빼다·제외하다('X는 빼고' = X 없이), 정도·평가 부사(덜·너무·대충·늦게), 뒤 절의 '다시·또'.
    문장 전체: 지시가 아닌 끝맺음(물음·약속·과거)."""
    why: list[str] = []
    if not _ending_ok(s):
        why.append("not_instruction")
    lo = 0
    for k, act in enumerate(acts[:-1]):
        nxt = acts[k + 1]
        nlo = act.stop + 1
        if s.clause_other_subject(lo, act):
            why.append("other_subject")
        if not act.lemmas or not act.lemmas <= DELIBERATE_ACTIONS:
            why.append("not_deliberate")
        if act.boundary == "go" and act.lemmas & EXCEPT_VERBS:
            why.append("except")
        if any(_is_degree_word(s, j) for j in range(lo, act.stop + 1)):
            why.append("degree_adverb")
        if any(s.words[j] in REDO_WORDS for j in range(nlo, nxt.end + 1)):
            why.append("redo")
        lo = nlo
    return why


def _deictic(s: _Sentence, lo: int, hi: int) -> bool:
    """[lo, hi)에 앞 일을 가리키는 말(그 위에·거기에·그걸)이 있는가."""
    return any(not s.quoted[j] and (s.words[j] in DEICTIC_WORDS or s.words[j].startswith(_DEICTIC_PREFIXES))
               for j in range(lo, hi))


_DEPENDENT_OBJECT_RE = re.compile(r"^(?:것|거)(?:을|은|는|이|도|만)?$|^(?:걸|건)$")


def _dependent_object(s: _Sentence, lo: int, hi: int) -> bool:
    """[lo, hi)의 대상이 꾸밈말만 앞에 둔 의존 명사(것·거)인가("유통기한을 확인하고 지난 것은 빼세요"). 떼어 낸
    단계 "지난 것은 빼세요"는 혼자 읽으면 무엇이 지났는지 모른다 — 자동으로 나누지 않고 제안(노란 줄)으로 둔다."""
    return any(not s.quoted[j] and _DEPENDENT_OBJECT_RE.match(s.words[j]) for j in range(lo, hi))


def _seo_between_ok(s: _Sentence, j: int | None, act: _Action) -> bool:
    """'-어서' 앞 절에서 대상과 동사 사이에 방법 부사·'-씩'·자리 말만 있는가. 다른 말이 있으면 그 절은 까닭·결과일
    수 있다("택배를 늦게 받아서", "물을 너무 많이 넣어서")."""
    if j is None:
        return False
    for k in range(j + 1, act.head):
        w = s.words[k]
        if w in HOWTO_ADVERBS or w.endswith("씩"):
            continue
        if w.endswith(_LOC_ENDINGS) and not s.is_verb_word(k) and w not in _RO_ADVERBS:
            continue
        return False
    return True


def _auto_blockers(s: _Sentence, acts: list[_Action]) -> list[str]:
    """자동 분할을 막는 이유(없으면 빈 목록). 모듈 설명 A의 조건."""
    why: list[str] = []
    if any(c in s.text for c in ",，"):
        why.append("comma")
    if any(c in s.text for c in _QUOTE_CHARS):
        why.append("quote")
    if _style(s) is None:
        why.append("style")
    if s.clause_has_condition(0, len(s.words)):
        why.append("condition")
    why += _first_verb_blockers(s, acts)
    carries = _carries(s, acts)
    lo = 0
    for k, act in enumerate(acts[:-1]):
        nxt = acts[k + 1]
        nlo = act.stop + 1
        if act.boundary not in ("go", "seo", "adn"):
            why.append(f"boundary:{act.boundary}")
        if act.compound:
            why.append("compound")
        if act.manner:
            why.append("manner")
        lemma = _certain_lemma(s, act)
        if lemma is None:
            why.append("uncertain_lemma")
        elif lemma in EVENT_VERBS or lemma in kv.MOTION_VERBS:
            why.append("event_or_motion")
        if not _next_lemma_ok(s, nxt):
            why.append("uncertain_next_lemma")
        elif nxt.lemmas <= BARE_MOTION:
            why.append("next_is_motion")
        if s.clause_mishap(lo, act.stop):
            why.append("mishap")
        j = _object_word(s, lo, act.head, lemma)
        if j is None:
            why.append("no_object")
        elif _is_list(s, j, lo):
            why.append("list_object")
        if act.boundary == "seo" and s.clause_object(nlo, nxt.head) is not None:
            why.append("seo_new_object")
        if act.boundary == "seo" and not _seo_between_ok(s, j, act):
            why.append("seo_between")
        if _deictic(s, nlo, nxt.end + 1):
            why.append("deictic")
        if _dependent_object(s, nlo, nxt.head):
            why.append("dependent_object")
        if (not carries[k + 1] and not _own_object(s, nlo, nxt.head) and not (nxt.lemmas & NO_OBJECT_OK)
                and not s.clause_has_embedded_question(nlo, nxt.head)):
            why.append("next_missing_object")
        lo = nlo
    return why


def split_clause(text: str, question: bool = False) -> SplitOutcome:
    """한 조각을 자동 분할·제안·그대로 중 하나로 정한다. question: 원문에서 이 조각 뒤에 물음표가 있었다
    (decompose._split_steps가 문장부호를 떼므로 따로 받는다)."""
    original = text.strip()
    an = _analyzer()
    if an is None or not original:
        return SplitOutcome(steps=[original])
    s = _Sentence(original, an, question=question)
    all_acts = s.actions()
    sure: list[_Action] = []
    acts = _counted(s, all_acts, sure)
    # 갈라 담기(_sorts_into)로 세지 않은 동사는 확실한 쪽이라 hidden에 넣지 않는다.
    unparsed = s.unparsed_adnominals()
    unseen = s.unseen_verbs()
    hidden = (len(all_acts) - len(acts) - len(sure) + sum(1 for a in all_acts if a.compound)
              + unseen + unparsed)
    hidden_lemmas = frozenset(lm for a in all_acts if a not in acts and a not in sure and a.boundary in ("go", "seo")
                              for lm in a.lemmas)
    soft = any(a.lemmas & BARE_MOTION for a in acts[:-1]) or any(s.quoted) or any(
        q in original for q in _QUOTE_CHARS)
    if len(acts) < 2:
        return SplitOutcome(steps=[original], actions=len(acts), hidden_verbs=hidden, unparsed_verbs=unparsed, unseen_verbs=unseen,
                            hidden_lemmas=hidden_lemmas,
                            list_object=_has_list_object(s), sorted_into=bool(sure), with_joined=s.with_joined)
    if has_negation(original, an):
        return SplitOutcome(steps=[original], suggestion=None, reason="negation", actions=len(acts),
                            why_not=["negation"], hidden_verbs=hidden, unparsed_verbs=unparsed, unseen_verbs=unseen,
                            hidden_lemmas=hidden_lemmas,
                            soft_boundary=soft)
    # 세지 않은 동작(방법·사건·사고)이 사이에 있으면 절 경계가 어긋나므로 문장을 만들지 않는다(힌트만).
    if len(all_acts) != len(acts):
        return SplitOutcome(steps=[original], suggestion=None, reason="multi_action", actions=len(acts),
                            why_not=["uncounted_action"], hidden_verbs=hidden, unparsed_verbs=unparsed, unseen_verbs=unseen,
                            hidden_lemmas=hidden_lemmas,
                            soft_boundary=soft)
    why = _auto_blockers(s, all_acts)
    if unparsed:
        why.append("unparsed_verb")
    pieces = _build(s, all_acts)
    if not why and pieces:
        return SplitOutcome(steps=pieces, auto=True, actions=len(acts), source=original, hidden_verbs=hidden,
                            unparsed_verbs=unparsed, unseen_verbs=unseen,
                            hidden_lemmas=hidden_lemmas, soft_boundary=soft)
    draft_why = _first_verb_blockers(s, all_acts)
    suggestion = pieces if pieces and not draft_why else None
    comma_draft = pieces if pieces and draft_why and set(draft_why) <= COMMA_OK_BLOCKERS else None
    gaps = _missing_objects(s, all_acts, _carries(s, all_acts)) if suggestion else None
    if suggestion and gaps:
        suggestion, gaps = _fill_gaps(s, all_acts, suggestion, gaps)
    return SplitOutcome(steps=[original], suggestion=suggestion, reason="multi_action", actions=len(acts),
                        why_not=why or ["grammar"], suggestion_gaps=gaps or None, hidden_verbs=hidden,
                        unparsed_verbs=unparsed, unseen_verbs=unseen,
                        hidden_lemmas=hidden_lemmas, soft_boundary=soft, comma_draft=comma_draft,
                        draft_blockers=draft_why)


def finish_piece(chunk: str, style: str = "seyo") -> str | None:
    """쉼표·순서 접속어 앞에서 끊긴 조각("도착한 우편물을 부서별로 분류하고", "서류를 넣고 복사한 뒤")의 끝 어절을
    지시형으로 바꾼 문장("…분류하세요.", "…복사하세요."). 끝 어절이 '-고(나서)'·'-어서'·'-(으)ㄴ 뒤/후/다음'이고
    원형이 확실할 때만, 아니면 None. 뜻 검사(부정·다른 주어·실수)는 하지 않는다 — 부르는 쪽이 문장 전체로 이미 본다.
    조각 안에 동작이 더 남아 있어도 된다("서류를 넣고 복사하세요") — 부르는 쪽이 그 문장을 다시 나눈다."""
    an = _analyzer()
    text = chunk.strip().rstrip(",， ")
    if an is None or not text:
        return None
    s = _Sentence(text, an)
    n = len(s.words)
    if n == 0:
        return None
    i, boundary = n - 1, None
    if n >= 2 and s.words[-1] in _TEMPORAL_NOUNS:
        i, boundary = n - 2, "adn"
    elif n >= 2 and s.words[-1] == "나서":
        i, boundary = n - 2, "go"
    word = s.words[i]
    if s.quoted[i]:
        return None
    # 'X하고·X해서·X한 뒤'(파쇄하고·복사한 뒤) — 사전에 없는 'X하다'도 지시형은 'X하세요' 하나다. 형용사(깨끗하고)는 뺀다.
    hada = {"go": ("하고", "하고서"), "seo": ("해서",), "adn": ("한",)}
    for b, ends in hada.items():
        if boundary not in (None, b):
            continue
        tail = next((e for e in ends if word.endswith(e)), None)
        if tail is None or len(word) <= len(tail):
            continue
        stem = word[:-len(tail)]
        if stem in _ADJ_STEMS or style != "seyo":
            return None
        sentence = (text[:s.matches[i].start()] + stem + "하세요").strip() + "."
        return sentence if _finished_ok(sentence, an) else None
    if not s.parses[i] or any(p.aux for p in s.parses[i]):
        return None
    if boundary is None:
        if s.kind.get(i) != kv.CONN:
            return None
        if word.endswith(("고", "고서")) and not word.endswith("다고"):
            boundary = "go"
        elif word.endswith("서") and not word.endswith("면서"):
            boundary = "seo"
        else:
            return None
    lemmas = s.main_lemmas(i) if boundary != "adn" else frozenset(p.lemma for p in s.parses[i])
    act = _Action(head=i, end=i, stop=n - 1, lemmas=lemmas, boundary=boundary)
    imp = _rewrite_boundary(s, act, style)
    if imp is None:
        return None
    sentence = (text[:s.matches[i].start()] + imp).strip() + "."
    return sentence if _finished_ok(sentence, an) else None


def _finished_ok(sentence: str, an: kv.Analyzer) -> bool:
    """finish_piece가 만든 문장의 겉모양 — 두 어절 이상, 마침표, 마지막 어절이 '-요' 종결 서술어, 동사에 조사가 붙은
    어절 없음. 안쪽의 연결형(넣고)은 허용한다(_grammar_ok와 다른 점)."""
    body = sentence[:-1].strip()
    words = kv._TOKEN_RE.findall(body)
    if not sentence.endswith(".") or len(words) < 2 or not words[-1].endswith("요"):
        return False
    return any(q.kind == kv.FINAL for q in an.analyze_word(words[-1]))


def _cond_word(s: _Sentence, j: int) -> bool:
    """j 어절이 조건·때 말인가('-(으)면'·'-거든'·'-려면'·'때'·'전에'·'경우에'). 순서 말(뒤·후·다음)과 까닭('-니')은
    아니다 — 앞 동작을 끝내고 하는 일은 나누는 경계다."""
    w = s.words[j]
    if s.quoted[j] or len(w) < 1:
        return False
    if w in _TIME_WORDS:
        return True
    if len(w) >= 2 and w not in _noun_vocab() and (
            (w.endswith("면") and not w.endswith("면서")) or w.endswith(("거든", "다면", "려면"))):
        return True
    return False


def has_condition(text: str) -> bool:
    """문장에 조건·때 말이 있는가(_cond_word). 순서 말(뒤·후·다음)도 있다고 본다 — GPT가 '출근하면'을 '출근한 뒤'로
    바꿔 쓴 것도 조건을 지킨 것이다."""
    an = _analyzer()
    if an is None or not text.strip():
        return False
    s = _Sentence(text.strip(), an)
    return any(_cond_word(s, j) or s.words[j] in _TEMPORAL_NOUNS for j in range(len(s.words)))


def condition_prefix(text: str) -> str | None:
    """조각 맨 앞의 조건·때 절("출근하면", "고객이 화장실을 쓰고 있으면", "일하기 전에"). 첫 할 일 동사보다 앞에
    있을 때만, 아니면 None. GPT 단계 문장이 이 조건을 잃었을 때 첫 단계 앞에 되살리는 데 쓴다(2차 검증)."""
    an = _analyzer()
    text = text.strip()
    if an is None or not text:
        return None
    s = _Sentence(text, an)
    acts = s.actions()
    first = acts[0].head if acts else len(s.words)
    found = None
    for j in range(min(first, len(s.words))):
        if _cond_word(s, j):
            found = j
    if found is None or any(q in text[:s.matches[found].end()] for q in _QUOTE_CHARS):
        return None
    return text[:s.matches[found].end()].strip()


def fix_polite(sentence: str) -> tuple[str, bool]:
    """'-아/어세요' 꼴로 틀린 지시형(눌러세요·알려세요·둘러세요·깔아세요)을 바로잡는다. (문장, 확실한가).

    마지막 어절이 '…세요'이고 '세요' 앞이 어떤 동사의 '-아/-어' 몸통이면(눌러 → 누르다) 그 동사의 지시형으로 바꾼다
    (누르세요·알리세요·두르세요·깔아 주세요). 몸통과 어간이 같은 동사(가세요·켜세요)는 원래 맞다. 틀린 꼴인데 원형을
    하나로 정하지 못하면 문장을 두고 False — 부르는 쪽이 노란 줄을 켠다(2차 검증: GPT 문장의 틀린 명령형)."""
    an = _analyzer()
    body = sentence.rstrip()
    end = ""
    while body and body[-1] in ".!?":
        end = body[-1] + end
        body = body[:-1]
    m = re.search(r"([가-힣]+)세요$", body)
    if an is None or m is None:
        return sentence, True
    stem = m.group(1)
    hits = set()
    for q in an.analyze_word(stem):
        forms = conjugate.conjugate(q.lemma)
        if forms is not None and stem in forms.a and q.lemma not in kv._LIGHT_VERBS:
            hits.add(q.lemma)
    if not hits:
        return sentence, True
    goods = {imperative(lm, "seyo") for lm in hits}
    if stem + "세요" in goods:
        return sentence, True
    if len(hits) != 1 or None in goods:
        return sentence, False
    fixed = goods.pop()
    if not _reads_as(fixed, next(iter(hits)), an):
        return sentence, False
    return body[:m.start()] + fixed + end, True


# 쉼표('~고,')로 이미 끊어 쓴 문장이면 이 이유만으로는 쉼표에서 나누기를 막지 않는다 — 앞 동사가 일부러 하는 일
# 목록 밖(분류하다), 앞 절의 '-게' 부사(빠르게 씻고,).
COMMA_OK_BLOCKERS = frozenset({"not_deliberate", "degree_adverb"})


def _has_list_object(s: _Sentence) -> bool:
    """대상(-을/-를, 없으면 주제어)이 나열인가("컵과 접시를", "컵 접시 수저를")."""
    return any((s.is_object(j) or s.is_topic(j)) and _is_list(s, j, 0) for j in range(len(s.words)))


def _counted(s: _Sentence, acts: list[_Action], sure: list[_Action] | None = None) -> list[_Action]:
    """동작 수에 세는 것만. 빼는 것: 방법·수단 앞 절, 일어나는 일(사건 동사, 주어 있고 대상 없는 앞 절),
    사고·실수 앞 절(사고 동사, 실수 부사가 든 절 — "음료를 쏟아서 닦으세요"의 시킬 일은 닦기 하나다)."""
    out = []
    lo = 0
    for k, act in enumerate(acts):
        skip = bool(act.lemmas and act.lemmas <= EVENT_VERBS)
        if act.boundary is not None:
            if act.manner or bool(act.lemmas & MISHAP_VERBS) or s.clause_mishap(lo, act.stop):
                skip = True
            elif (s.clause_has_event_subject(lo, act.head)
                  and s.clause_object(lo, act.head) is None and s.clause_topic(lo, act.head) is None):
                skip = True
            elif k + 1 < len(acts) and _sorts_into(s, act, acts[k + 1], lo):
                skip = True
                if sure is not None:
                    sure.append(act)
        if not skip:
            out.append(act)
        lo = act.stop + 1
    return out


def _sorts_into(s: _Sentence, act: _Action, nxt: _Action, lo: int) -> bool:
    """앞 절이 갈라 담기의 '나눠·모아'인가(SORT_INTO_VERBS 주석).

    앞 동사가 '-어/-아' 꼴(나눠·모아·나눠서)로 바로 이어질 때만이다. '-고'로 잇거나 쉼표로 끊어 쓴 문장("빨래를
    색깔별로 분류하고 세탁기에 넣으세요", "물건을 종류별로 나누고, 선반에 놓으세요")은 사업주가 두 동작으로 말한
    것이라 둘로 센다(입력 화면 나누기 2차 검증 — 말없이 한 단계로 합쳐 그림 한 장에 두 동작이 남았다)."""
    if not (act.lemmas & SORT_INTO_VERBS) or not (nxt.lemmas & SORT_INTO_PLACE):
        return False
    if act.boundary not in ("bare", "seo") or s.comma_after(act.end):
        return False
    words = s.words[lo:act.head]
    if any(w.endswith(("별로", "끼리")) or w in ("따로", "따로따로") for w in words):
        return True
    obj = s.clause_object(lo, act.head)
    if obj is None:
        obj = s.clause_topic(lo, act.head)
    return obj is not None and _is_list(s, obj, lo)
