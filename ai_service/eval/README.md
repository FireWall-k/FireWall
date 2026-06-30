# 직무 분해 평가 하네스 (점수판)

프롬프트(`llm.py`의 `_DECOMPOSE_SYSTEM`)를 바꿀 때마다 분해 품질을 **점수**로 확인하는 도구.
눈대중 대신 정량으로 개선/회귀(regression)를 잡는다.

## 실행

```bash
cd ai_service

# 전체 채점
python -m eval.run_eval

# 특정 케이스만
python -m eval.run_eval --case cafe_close

# 점수를 JSON으로 저장(프롬프트 전/후 비교용)
python -m eval.run_eval --json before.json
# ...프롬프트 수정 후...
python -m eval.run_eval --json after.json
```

## 두 가지 동작 모드

| 모드 | 조건 | 의미 |
|------|------|------|
| **LLM** | `OPENAI_API_KEY` 설정됨 | 실제 LLM 분해를 채점 → 프롬프트 개선 효과 측정 |
| **규칙기반 폴백** | 키 없음 | 폴백 분해를 채점. `symbol_query`가 비어 LLM 전용 지표는 낮게 나옴 → **점수 하한선**(LLM이 왜 필요한지 보여줌) |

> 프롬프트 개선 효과를 보려면 `OPENAI_API_KEY`를 설정하고 돌려야 한다.

## 채점 기준 (rubric)

`dataset.json`의 `rubric_weights`로 가중치를 조절한다.

| 지표 | 측정 |
|------|------|
| `steps_in_range` | 기대 단계 수 범위 안인가 |
| `sentence_brevity` | 문장이 권장 글자수(`brevity_max_chars`, 기본 20자) 이내 비율 |
| `imperative_ending` | 명령형(`~요/~세요/~다`)으로 끝나는 비율 |
| `symbol_query_quality` | 단계별 `symbol_query`에 한글+영어가 함께 있는 비율 (LLM 지표) |
| `action_typed` | `action_type`이 `other`가 아닌(구체 분류된) 비율 |
| `keyword_coverage` | 기대 키워드가 결과에 등장하는 비율 |

## 정답셋 늘리기

`dataset.json`의 `cases` 배열에 추가:

```json
{
  "id": "고유_id",
  "domain": "cafe 또는 office",
  "raw_input": "사업주가 입력하는 원문 직무 지시",
  "context": {"business_type": "카페", "work_environment": "홀"},
  "expect": {
    "min_steps": 3,
    "max_steps": 4,
    "must_have_keywords": ["꼭 등장해야 할 단어"]
  }
}
```
