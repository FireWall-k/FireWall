# Project-owned AAC dataset

이 디렉터리는 잡카드 프로젝트에서 직접 제작한 직무교육용 AAC 이미지 데이터셋입니다.
외부 pictogram API를 호출하지 않으며 런타임에서는 이 디렉터리의 정규화 이미지와
`aac_assets.json` 메타데이터만 사용합니다.

## 구성

- `images/assembly/` — 106장
- `images/cafe/` — 101장
- `images/cleaning/` — 74장
- `images/packaging/` — 44장
- `images/retail/` — 76장
- 총 401장

모든 런타임 이미지는 768×768 WebP로 정규화되어 있습니다.

## 메타데이터

`aac_assets.json`의 주요 필드:

- `id`: 앱 내부에서 사용하는 고유 AAC ID
- `group_id`: 같은 행동의 여러 시각 변형을 묶는 ID
- `job`: `assembly | cafe | cleaning | packaging | retail`
- `asset_type`: `action | tool | support`
- `variant`: 동일 행동 이미지의 변형 번호
- `label`: 한국어 행동/사물 라벨
- `keywords`, `aliases`, `objects`, `action`, `search_text`: `scripts/enrich_aac_metadata.py`가
  채운 검색/분류 보강 필드(2026-09-14, `feature/local-aac` 병합분). 이전에는 401건 전부
  비어 있던 데드 필드였다 — `ai_service/local_aac.py`의 `load_assets()`가 이 필드들을
  원래도 읽고 있었으므로 데이터만 채워지면 코드 변경 없이 검색에 반영된다.
- `image`: `images/` 기준 상대 경로
- `source_file`: 원본 추적용 파일명

## 두 개의 보강 파이프라인이 공존합니다

같은 문제(라벨만으로는 검색이 부실함)를 두 갈래로 풀었고, 둘 다 살려서 씁니다.

| | `scripts/enrich_aac_metadata.py` | `scripts/build_aac_index.py` |
|---|---|---|
| 저장 위치 | `aac_assets.json`에 직접(`keywords`/`aliases`/`objects`/`action`) | 별도 파일 `aac_index.json` |
| 성격 | 사람이 보강 가능한 원본 필드 | LLM이 만든 재생성 가능한 파생 데이터 |
| `local_aac.py` 사용처 | 검색어 가방(Jaccard) | 동사 원형 직접매칭, 사물카드 게이트 등 |

새 자산을 넣거나 라벨을 고치면 **둘 다** 다시 돌리는 게 안전합니다. 어느 한쪽만
돌리면 그 자산만 검색 품질이 떨어집니다.

## 구조화 인덱스 (`aac_index.json`)

라벨을 `동작 + 대상 + 도구` 구조로 분해한 **파생 데이터**입니다. 원본(`aac_assets.json`)과
분리해 둔 이유는 LLM이 생성한 것이라 재생성·검수 이력을 따로 관리해야 하고, 원본을 다시
임포트해도 덮어쓰지 않아야 하기 때문입니다.

### 왜 필요한가

기존 매칭은 질의 문장과 라벨의 **문자열 유사도**뿐이라 두 가지가 구조적으로 안 됩니다.

- **동사가 무시된다** — "원두를 갈아주세요" → "원두를 준비한다"(0.000 동점).
  명사만 겹치면 동작이 달라도 상위로 올라옵니다.
- **도구 카드가 동작 카드를 이긴다** — "얼음통을 씻어주세요" → 도구 카드 "얼음통".
  문장에 언급된 물건 이름이 그대로 그 물건 그림을 끌어옵니다.

가중치로는 못 풉니다. 문제는 점수 크기가 아니라 **무엇을 비교하는가**입니다.

### 필드

| 필드 | 의미 |
|------|------|
| `frame.verb` | 동작의 기본형(`쓸어낸다` → `쓸다`). 사물 카드는 `null` |
| `frame.verb_class` | `observe/move/stack/sort/pack/clean/wear/operate/other`. 질의의 `action_type`과 같은 축 |
| `frame.object` | 대상의 핵심 명사(`빈 포장 봉투` → `봉투`) |
| `frame.object_detail` | 떼어낸 수식어(`빈 포장`) |
| `frame.instrument` | 사용 도구(`바닥을 빗자루로 쓸어낸다` → `빗자루`) |
| `frame.location` | 장소/위치 |
| `frame.is_object_card` | **물건만 보여주는 그림인가.** 도구 카드 54건 전부 `true` |
| `keywords_ko` / `keywords_en` | **라벨에 없는** 다른 표현(`분쇄한다` → `갈다`, `박스` → `상자`) |
| `reviewed` | 사람 검수 여부. 생성 직후는 전부 `false` |

`is_object_card`가 핵심입니다. 사물 카드는 "그 물건을 가리킬 때"만 맞고 "그 물건으로
무언가 할 때"는 틀린데, 문자열 유사도는 이 둘을 구분하지 못합니다.

### 재생성

```bash
# .env 또는 환경변수에 OPENAI_API_KEY 필요
python scripts/build_aac_index.py                  # 전체
python scripts/build_aac_index.py --job cafe --limit 20   # 소량 확인
python scripts/build_aac_index.py --resume --batch-size 8 # 누락분 이어서
```

배치마다 저장하므로 중단돼도 `--resume`으로 이어집니다. LLM이 배치에서 항목을 빠뜨리거나
검증(수식어 잔존, 라벨 되풀이 등)에 걸리면 로그에 남고 그 항목만 빠지므로, 마지막에
`401/401`이 아니면 `--resume`을 다시 돌리면 됩니다.

`source_digest`는 원본 자산의 `id+label` 해시입니다. 원본을 바꿨는데 인덱스를 재생성하지
않으면 이 값이 어긋납니다.

### 검수 (`scripts/review_aac_index.py`)

401건을 눈으로 훑는 대신 자동 점검으로 형태 오류를 잡고, 플래그된 것만 사람이 본다.
현재 매칭이 쓰는 프레임 필드는 `verb` / `verb_class` / `is_object_card` / `keywords_ko`
뿐이므로 점검도 이 넷에 집중한다.

```bash
python scripts/review_aac_index.py                 # 점검만
python scripts/review_aac_index.py --fix           # 기계적 수정 적용
python scripts/review_aac_index.py --list needs-human
```

`reviewed` 값:

| 값 | 뜻 |
|----|----|
| `true` | 사람이 확인함 |
| `"auto"` | 규칙이 수정함(활용형 verb → 사전형, `도구` 접두사 제거 등) |
| `"checked"` | 자동 점검 통과, 사람 미확인 |
| `false` | 미검토 |

재생성 시 `--resume`은 기존 항목을 건드리지 않으므로 검수 결과가 보존된다.

**2026-09-11 1차 검수:** 자동 수정 22건(verb 형태 5, `도구` 접두사 오염 15, verb_class
누락 2), 사람 확인 7건. **매칭 지표는 변동 없었다** — 정답셋이 걸린 실패는 이 항목들과
무관했다. 즉 검수는 품질 정리이지 성능 개선이 아니다.

### 남은 흠 (2차 검수 대상)

- `object` 에 붙여 쓴 복합명사를 과하게 자름(`얼음통` → `"통"`).
- `object_detail` 이 저신호다 — `사용한`, `잘못된`, `정상` 같은 관형어나 `부품`, `작업`
  같은 복합명사 조각이 대부분. **매칭에 쓰려면 이 필드를 다시 만들어야 한다.**
- `verb_class` 경계 애매(`모으다` → `stack` vs `sort`).

> `object` / `object_detail` 을 매칭에 쓰는 실험은 실패했다(회귀). 자산 쪽 품질 문제가
> 아니라 **질의 쪽에 대상 추출이 없어서**다. `ai_service/local_aac.py` 의 관련 주석 참고.

## 원본 이미지 재가져오기

원본 `ACC` 폴더를 다시 정규화하려면 프로젝트 루트에서:

```bash
pip install Pillow
python scripts/import_aac_assets.py /path/to/ACC
```

스크립트는 원본의 `#Uxxxx` 형태 파일명을 한국어 라벨로 복원하고, 이미지 파일명은
ASCII 기반의 안정적인 내부 ID로 다시 저장합니다.

## 검색

1차 검색기는 `ai_service/local_aac.py`에 있습니다. 현재는 네트워크나 별도 모델 없이
문장/키워드 유사도 + 업종 컨텍스트를 사용합니다. 이후 임베딩/벡터 검색을 추가하더라도
`/ai/map-symbols`, `/api/aac/search` 계약은 유지하도록 설계했습니다.
