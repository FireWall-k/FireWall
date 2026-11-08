# Project-owned AAC dataset

이 디렉터리는 잡카드 프로젝트에서 직접 제작한 직무교육용 AAC 이미지 데이터셋입니다.
외부 pictogram API를 호출하지 않으며 런타임에서는 이 디렉터리의 정규화 이미지와
`aac_assets.json` 메타데이터만 사용합니다.

## 구성

- `images/assembly/` — 255장 (2026-09-16 변형 세트 ASSEMBLY_023~038·AUX 확장)
- `images/cafe/` — 121장
- `images/cleaning/` — 241장 (2026-09-23 CLEANING_051~190 140장 추가)
- `images/packaging/` — 179장 (2026-09-23 120장 추가)
- `images/retail/` — 97장
- `images/delivery/` — 68장 (배송·택배, 2026-09-21 추가)
- `images/display/` — 92장 (진열·재고·손님 안내)
- `images/gas/` — 57장 (주유소·세차)
- `images/serving/` — 103장 (홀 서빙·퇴식)
- 총 1,213장 (2026-11-08 갭 해소용 새 카드 111장 + 수작업 카드 53장 추가 — 아래 '새 카드' 절) — 정확한 수는 `aac_assets.json`의 `asset_count`/`jobs`가 기준이며,
  `ai_service/tests/test_aac_data.py`가 이미지·메타데이터·인덱스·임베딩의 정합성을 CI에서 검사한다.

새 직무 4개는 `scripts/import_aac_images.py`로 등록했다(원본 PNG 1254px 등 → 768×768 WebP,
원본은 저장소 밖 `_aac_originals/`에 두고 커밋하지 않는다). 번호가 겹친 파일(DELIVERY_035 두 장)은
한 장만 새 번호(DELIVERY_047)를 받았다. 등록 후 `enrich_aac_metadata.py --job <job> --output
data/aac/aac_assets.json` → `build_aac_index.py --resume` → `build_aac_embeddings.py` 순서로 돌린다
(enrich는 기본 출력이 `aac_assets.enriched.json`이라 `--output`을 주지 않으면 반영되지 않는다).

모든 런타임 이미지는 768×768 WebP로 정규화되어 있습니다(2026-11-06: packaging 164장이 1254/1024px 원본 그대로
커밋돼 있던 것을 재정규화했고, 같은 그림이 다른 ID로 두 번 들어간 9쌍과 메타데이터 없는 GAS_046을 정리했다).

## 새 카드 (2026-11-08)

평가셋의 갭 문항(맞는 그림 없음)을 해소하려고 111장을 추가했다(ASSEMBLY_176~, CAFE_091~, CLEANING_191~,
PACKAGING_165~, RETAIL_093~, DELIVERY_049~). 기존 그림 2장을 참조로 넣어 같은 캐릭터·직무 유니폼을 유지했고,
판정자가 참조 그림과 나란히 놓고 캐릭터·유니폼·동작·글자 유무·안전을 검수해 통과한 것만 넣었다(118장 중 111장).
`source_file`은 설계 단계 id(`<JOB>_NEW_<번호>.png`)다. enrich 규칙 필드는 새 카드에만 적용했고(기존 자산은 그대로),
`aac_index.json` 항목은 build_aac_index.py와 같은 규칙·검증 함수로 만들었다.
임베딩(`aac_embeddings.npz`)은 새 카드를 포함한 1,213장 전체를 로컬 모델로 다시 만들었다(아래 절).

### 수작업 카드 53장 (2026-11-08)

API 크레딧이 떨어져 못 만든 진열·서빙·주유 중심 카드와 검수 불합격분 7장을 ChatGPT 구독(웹)으로 손수 만들었다(API 호출 없음).
DISPLAY_055~072, SERVING_074~090, GAS_046~057, CAFE_109~110, ASSEMBLY_195, CLEANING_218, DELIVERY_060, RETAIL_113.
57장 중 53장이 직무별 검수(여러 검수자가 본 카드는 모두 통과해야 합격)를 통과했다. 불합격 4장(커터칼 2장은 칼질 방향 안전,
배송 2장은 캐릭터 차이)은 재작업 대상이다. 인덱스 항목은 Claude 에이전트가 같은 규칙·검증 함수로 만들었고,
정답지 추가는 제안자와 독립 검토자, 상위 3위 교차 직무 쌍은 판정자 2명이 모두 맞다고 한 것만 넣었다.

## 메타데이터

`aac_assets.json`의 주요 필드:

- `id`: 앱 내부에서 사용하는 고유 AAC ID
- `group_id`: 같은 행동의 여러 시각 변형을 묶는 ID
- `job`: `assembly | cafe | cleaning | packaging | retail | delivery | display | gas | serving`
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

## aac_embeddings.npz — 임베딩 가산 항용 자산 벡터

자산마다 두 벡터(라벨, 라벨+`keywords_ko/en`)를 임베딩해 저장한다. 질의 시점에 질의를 **같은 모델**로
임베딩해 코사인 유사도를 규칙 점수에 더한다(`ai_service/embeddings.py`, `local_aac._EMBED_DEFAULTS`).
**기본은 꺼져 있다**(`AAC_EMBEDDINGS=off`). 로컬 모델이 블라인드셋에서 오답 채택을 늘려서다
(`ai_service/eval/README.md` 2026-11-08 블라인드셋 확인). `AAC_EMBEDDINGS=auto`로 켠다.

- **모델(기본, `AAC_EMBED_PROVIDER=local`)**: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
  (384차원, 50여 개 언어·한국어 포함). fastembed가 받는 양자화 ONNX(약 230MB)를 CPU로 돌린다 — torch·키·
  네트워크가 필요 없고 무료다. 질의 하나 ≈ 10ms, 모델 로딩 ≈ 3초(서비스 시작 때 미리 불러 둔다).
  도커 이미지는 빌드 때 모델을 `/opt/embed-models`(`AAC_EMBED_CACHE_DIR`)에 받아 두고 실행 중에는 내려받지 않는다.
- **OpenAI(`AAC_EMBED_PROVIDER=openai`)**: `text-embedding-3-large` 256차원(키 필요). 이 제공자로 바꾸면 파일도
  그 제공자로 다시 만들어야 한다.

파일에 모델·차원과 텍스트 digest가 들어 있어, 지금 제공자의 모델과 다르거나 `aac_index.json`의 라벨·검색어를 고치고
다시 만들지 않으면 서비스가 어긋난 벡터를 쓰지 않고 임베딩을 끈다(규칙 점수와 임베딩 없는 임계값으로 동작).

    cd ai_service
    python ../scripts/build_aac_embeddings.py           # 만들기(로컬 모델, 1,160장 ≈ 35초. 처음 한 번 모델 내려받기)
    python ../scripts/build_aac_embeddings.py --check   # 낡았는지 확인(모델 호출 없음)
