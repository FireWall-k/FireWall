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
- `keywords`, `aliases`: 향후 수동 보강용 검색어
- `image`: `images/` 기준 상대 경로
- `source_file`: 원본 추적용 파일명

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
