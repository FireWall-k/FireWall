# 잡카드 (JOB CARD)

발달장애인 직무 현장 AI 코칭 플랫폼입니다.

```text
직무 입력(사업주 말투 한 문단)
→ LLM 맥락적응 분해(업종·환경 반영, 한 단계=한 동작)
→ 자체 AAC 그림 데이터셋(661장, 9개 직무) 검색·자동 채택
→ Google Cloud Text-to-Speech mp3 생성/캐싱
→ 근로자 카드
→ 완료/막힘 체크
→ 대시보드 집계(10초 폴링) + AI 코칭 제안
```

AAC 그림은 더 이상 외부 API(ARASAAC)를 쓰지 않고, **프로젝트가 직접 제작한 로컬 자산**
(`data/aac/`, 조립·카페·청소·포장·마트·배송·진열·주유소·서빙 9개 직무 661장)을 규칙 기반
점수(자카드·동사 원형·직무 맥락) + 임베딩 가산 항으로 매칭합니다. LLM(OpenAI)이나 Google
인증이 없거나 호출에 실패해도 서비스가 멈추지 않도록 각 지점에 규칙 기반/브라우저 fallback이
있습니다.

## 구조

```text
FireWall/
├── ai_service/        AI 하네스 (FastAPI, 8001)
│   ├── main.py           /ai/decompose, /ai/map-symbols, /ai/aac/search, /ai/coaching
│   ├── decompose.py      직무 원문 -> 단계 분해(LLM 우선, 실패 시 규칙 기반 폴백)
│   ├── llm.py             OpenAI 호출 경계(분해 프롬프트, 코칭, 임베딩)
│   ├── local_aac.py       자체 AAC 자산 매칭(점수·채택 판정 decide())
│   ├── embeddings.py      질의·자산 임베딩 가산 항(선택적, 자동 폴백)
│   ├── symbols.py         local_aac 결과를 API 스키마로 변환
│   ├── schemas.py         AI 입출력 스키마
│   └── eval/               매칭 품질 평가 하네스(골든셋·블라인드 테스트) — eval/README.md 참고
├── backend/           백엔드 API (FastAPI, 8000)
│   ├── main.py            직무 생성·배정·로그·대시보드·인증
│   ├── tts.py              Google Cloud TTS 연동 및 mp3 캐싱
│   ├── aac_assets.py       자체 AAC 이미지 정적 서빙 경로 헬퍼
│   ├── photos.py           단계별 현장 사진 업로드(자동 상징 대체)
│   ├── models.py           SQLAlchemy ORM
│   ├── ai_client.py        백엔드↔AI 하네스 경계
│   └── schemas.py          프론트 대면 입출력 스키마
├── frontend/          React + TS + Vite (5173)
│   └── src/pages/
│       ├── LoginPage.tsx      사업주/근로자 로그인
│       ├── ManagerPage.tsx    직무 생성·검토·게시
│       ├── WorkersPage.tsx    근로자 관리
│       ├── WorkerPage.tsx     근로자 오늘 할 일 카드
│       └── DashboardPage.tsx  완료율/소요/막힘/AI 코칭 대시보드
├── data/aac/           프로젝트 소유 AAC 이미지·메타데이터(661장, 9개 직무)
└── scripts/            자산 등록·메타데이터 보강·인덱스/임베딩 생성 스크립트
```

## Docker 실행

`docker-compose.yml`이 보이는 프로젝트 루트에서 실행합니다.

```bash
docker compose up --build
```

접속 주소(127.0.0.1로 고정 — Windows+WSL2에서 `localhost`가 IPv6로 먼저 시도되며 막히는
문제를 피하기 위함):

| 서비스 | 주소 | 설명 |
| --- | --- | --- |
| 프론트엔드 | http://localhost:5173 | 사용자 화면 |
| 백엔드 API | http://localhost:8000 | FastAPI 백엔드 |
| AI 하네스 | http://localhost:8001 | AI 분해/AAC 매칭 |
| 백엔드 헬스체크 | http://localhost:8000/health | 상태 확인 |
| AI 헬스체크 | http://localhost:8001/health | 상태 확인 |

컨테이너 이름:

```text
jobcard-web
jobcard-api
jobcard-ai
```

DB·TTS 캐시·업로드 사진은 Docker named volume `jobcard-data`에 유지됩니다(macOS 바인드
마운트에서 SQLite가 `disk I/O error`를 내는 문제를 피하기 위해 리눅스 VM 내부 볼륨을 사용).
AAC 이미지(`data/aac`)는 읽기 전용 바인드 마운트라 이미지·메타데이터만 바꾸면 컨테이너
재빌드 없이 바로 반영됩니다(코드를 바꾸면 재빌드 필요).

> **스키마 변경**: 정식 마이그레이션 도구(Alembic)는 아직 없습니다. `create_all()`은 없는
> *테이블*만 만들고 기존 테이블에 *컬럼*은 추가하지 않으므로, 모델에 컬럼을 늘리면 이미
> 만들어진 DB에서 조회가 깨집니다. 그 구멍은 `backend/database.py`의
> `apply_pending_columns()`가 서버 기동 시 `ALTER TABLE`로 메웁니다.
> **컬럼을 추가하면 `_ADDED_COLUMNS`에도 등록**하고, 기존 행이 채워지도록 NULL 허용이거나
> 기본값이 있어야 합니다. 컬럼 삭제·타입 변경은 지원하지 않습니다(그때는 Alembic 도입).

초기화가 필요하면 볼륨까지 함께 제거합니다.

```bash
docker compose down -v
```

특정 볼륨만 제거하려면 다음을 실행합니다(OS 공통).

```bash
docker compose down
docker volume rm jobcard_jobcard-data
```

## AAC: 자체 이미지 데이터셋

과거 버전은 ARASAAC 외부 API를 썼지만, 지금은 **프로젝트가 직접 제작·확보한 로컬 이미지**
(`data/aac/images/<job>/<ID>.webp`, 768×768 WebP)를 씁니다. 구성과 메타데이터 스키마는
`data/aac/README.md`, 매칭 알고리즘의 설계·튜닝 기록은 `ai_service/eval/README.md`에
자세히 있습니다.

핵심 동작(`ai_service/local_aac.py`):

1. 단계 문장 + LLM이 뽑은 구체 명사(symbol_query)로 질의를 만든다.
2. 라벨/검색어 텍스트 유사도(자카드·바이그램) + 동사 원형 일치 + 직무 맥락 보정으로 점수를
   매긴다. 선택적으로 임베딩 유사도(`AAC_EMBEDDINGS=auto`, OpenAI `text-embedding-3-large`)를
   가산 항으로 더한다(키·자산 임베딩 파일이 없거나 호출이 실패하면 자동으로 임베딩 없이
   동작 — 서비스가 멈추지 않는다).
3. 1위 점수가 임계값 이상이고, 2위와의 점수 차(여유)가 충분해야 자동 채택한다. 둘 중
   하나라도 부족하면 자동 채택하지 않고, 근거(그림 없음/점수 미달/후보 경합)를 구분해
   돌려준다 — 후보 경합이면 검토 화면에서 사람이 고른다.
4. 성공하면 `/api/aac/images/<job>/<ID>.webp`를 사용하고, 실패하면 `needs_fallback=true`로
   반환해 사업주 사진 등록 흐름으로 넘긴다.

관련 환경변수:

```env
AAC_DATA_DIR=/app/aac
AAC_MATCH_THRESHOLD=0.22          # 임베딩 없을 때 채택 점수 임계값
AAC_MATCH_MIN_MARGIN=0.02         # 임베딩 없을 때 1·2위 점수 차 최소값
AAC_EMBEDDINGS=auto               # off로 끌 수 있음
AAC_EMBED_MATCH_THRESHOLD=0.35    # 임베딩 사용 시 임계값(척도가 올라가 더 높다)
AAC_EMBED_MATCH_MIN_MARGIN=0.02   # 임베딩 사용 시 여유
AAC_EMBED_TIMEOUT=3               # 질의 임베딩 호출 타임아웃(초)
```

자산을 추가·수정하면 `scripts/enrich_aac_metadata.py` → `scripts/build_aac_index.py` →
`scripts/build_aac_embeddings.py` 순서로 다시 돌려야 합니다(README 참고).

## TTS: Google Cloud Text-to-Speech API

`backend/tts.py`에서 Google Cloud Text-to-Speech API를 호출해 단계 문장을 mp3로 생성하고
캐싱합니다. 인증 파일이 없거나 호출에 실패하면 서비스 전체가 멈추지 않도록 근로자 화면에서
브라우저 SpeechSynthesis fallback을 사용합니다.

기본 설정:

```env
GOOGLE_APPLICATION_CREDENTIALS=/app/secrets/google-tts.json
GOOGLE_TTS_LANGUAGE=ko-KR
GOOGLE_TTS_VOICE=ko-KR-Standard-A
GOOGLE_TTS_SPEAKING_RATE=0.9
GOOGLE_TTS_PITCH=0
TTS_CACHE_DIR=/app/data/tts
```

### Google TTS 인증 파일 설정

1. Google Cloud Console에서 Text-to-Speech API를 활성화합니다.
2. 서비스 계정을 만들고 JSON 키를 발급합니다.
3. 프로젝트 루트에 `secrets` 폴더를 만듭니다.
4. JSON 키 파일을 아래 경로로 저장합니다.

```text
secrets/google-tts.json
```

Docker Compose에는 이미 다음 볼륨이 설정되어 있습니다.

```yaml
- ./secrets:/app/secrets:ro
```

실제 JSON 키 파일은 Git에 커밋하지 마세요(`.gitignore`로 제외됩니다).

### Google TTS 동작 방식

```text
사업주가 직무 입력
→ AI가 단계 문장 생성
→ 백엔드가 각 단계 문장을 Google TTS로 mp3 생성
→ /api/tts/<hash>.mp3 URL 저장
→ 근로자 화면에서 mp3 우선 재생
→ mp3가 없거나 재생 실패하면 브라우저 TTS fallback
```

## 로컬 실행

### 1) AI 하네스

```bash
cd ai_service
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8001 --reload
```

로컬 실행 시 `.env`에 `AAC_DATA_DIR`가 도커 전용 경로(`/app/aac`)로 잡혀 있으면 자산을
못 찾습니다 — 로컬에서는 그 변수를 비우거나 지워야 합니다(기본값이 저장소 내
`data/aac`를 가리킵니다).

### 2) 백엔드

Google TTS 인증 파일을 로컬에서도 쓰려면 `GOOGLE_APPLICATION_CREDENTIALS`를 실제 파일
경로로 설정합니다.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
AI_BASE_URL=http://localhost:8001 \
GOOGLE_APPLICATION_CREDENTIALS=../secrets/google-tts.json \
uvicorn main:app --port 8000 --reload
```

### 3) 프론트엔드

```bash
cd frontend
npm install
npm run dev
```

## 사용 흐름

1. http://localhost:5173 접속
2. **로그인** — 사업주 `demo` / `demo1234`, 또는 근로자 접속 코드 `1234`
3. **사업주 · 직무 만들기** 탭에서 업종·작업 환경과 함께 직무를 사업주 말투로 입력
4. `단계로 나누기` 클릭 — LLM이 한 단계=한 동작으로 분해
5. 단계별 AAC 그림과 문장 검토(자동 채택 안 된 단계는 후보를 보여주거나 사업주 사진 등록)
6. `게시하고 근로자에게 보내기` 클릭
7. **근로자 · 오늘 할 일** 탭에서 카드 확인, `다시 듣기` 클릭(mp3 또는 브라우저 음성)
8. `완료`/`막힘` 클릭
9. **사업주 · 대시보드**에서 완료율/소요 시간/다시듣기 횟수/막힌 단계 + AI 코칭 제안 확인
   (10초 자동 갱신)

## 인증 / 권한

토큰 기반 인증(추가 라이브러리 없이 표준 라이브러리로 구현: `backend/auth.py`).

- 비밀번호: `pbkdf2_hmac(sha256, 200k)` + 랜덤 솔트
- 토큰: HMAC-SHA256 서명 JSON (`sub`, `role`, `exp`)
- 모든 자원 엔드포인트는 인증 + **소유권 검사**(타 사업주의 직무는 404)

데모 계정(환경변수로 변경 가능):

| 역할 | 자격증명 | 환경변수 |
| --- | --- | --- |
| 사업주 | `demo` / `demo1234` | `DEMO_EMPLOYER_LOGIN`, `DEMO_EMPLOYER_PASSWORD` |
| 근로자 | 접속 코드 `1234` | `DEMO_WORKER_CODE` |

운영 필수 환경변수:

```env
JOBCARD_SECRET=<강한 랜덤 문자열>   # 미설정 시 dev 기본값, JOBCARD_ENV=prod에서는 기동 거부
JOBCARD_ENV=prod
JOBCARD_TOKEN_TTL=86400
```

주요 엔드포인트:

```text
POST /api/auth/login                        # 사업주 로그인 -> 토큰
POST /api/auth/worker-login                 # 근로자 접속 코드 -> 토큰
GET  /api/tasks                             # (사업주) 내 직무 목록
POST /api/tasks                             # (사업주) 직무 생성 = AI 분해 + AAC 매칭 트리거
GET  /api/tasks/{id}/steps/{step}/symbol-candidates  # (사업주) 후보 경합 시 대체 상징 조회
POST /api/tasks/{id}/publish
POST /api/tasks/{id}/assignments
GET  /api/worker/me/today                   # (근로자) 오늘 배정된 카드(소유자+당일 기준)
POST /api/performance-logs                  # (근로자) 단계 완료/막힘 보고(단계당 업서트)
GET  /api/dashboard/tasks/{id}              # (사업주) 집계
GET  /api/dashboard/tasks/{id}/coaching     # (사업주) AI 코칭 제안
POST   /api/tasks/{id}/steps/{step}/photo   # (사업주) 단계 사진 업로드(상징 대체)
DELETE /api/tasks/{id}/steps/{step}/photo   # (사업주) 사진 제거 -> 기본 상징 복귀
POST /api/aac/search                        # (사업주) 직무별 AAC 자산 수동 검색
GET  /api/aac/images/{path}                 # 자체 AAC 이미지 정적 서빙
```

이후 모든 호출은 `Authorization: Bearer <토큰>` 헤더가 필요합니다.

## AI 기능 (OpenAI)

`OPENAI_API_KEY`를 설정하면 세 가지 AI 기능이 켜집니다. **키가 없으면 규칙 기반/휴리스틱으로
자동 폴백**하므로 서비스는 그대로 동작합니다(AI 호출은 ai_service에만 격리됨 —
`ai_service/llm.py`).

1. **맥락적응 직무 분해** — 직무 생성 시 업종·작업 환경을 함께 보내면, LLM이 한 단계=한
   동작의 명령형 문장과 AAC 그림 검색용 구체 명사(symbol_query)를 생성합니다. 여러 동작이
   대상을 하나만 공유하는 경우(예: "카트 정리하고 배치하세요")도 원문에 없는 대상을 지어내지
   않도록 프롬프트에 규칙과 예시를 두었습니다.
2. **AAC 매칭 임베딩 가산 항** — 규칙 점수에 의미 유사도를 더해서, 표현이 달라도("정리하세요"
   ↔ "놓는다") 정답이 더 잘 올라오게 합니다. 호출이 실패해도 규칙 기반 점수로 그대로
   동작합니다.
3. **사업주 AI 코칭** — 근로자의 막힘·다시듣기·소요시간을 분석해 단계별 개선책(문장 쉽게/사진
   교체/단계 분할)을 제안합니다.

단일 이미지의 한계를 보완하기 위해 **단계별 실제 사진 업로드**도 있습니다. 사업주가 검토
화면에서 현장 사진을 올리면 자동 매칭 결과를 대체하며, 매직바이트 검증·UUID 파일명·5MB
상한으로 안전하게 저장됩니다(jpg/png/webp/gif, SVG 불허).

설정:

```env
OPENAI_API_KEY=sk-...            # 미설정 시 폴백
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_TIMEOUT=20
```

Docker는 호스트의 `OPENAI_API_KEY`를 자동 주입합니다(`docker compose` 실행 전
`export OPENAI_API_KEY=sk-...`).

직무 생성(`POST /api/tasks`)은 선택 필드 `business_type`, `work_environment`,
`worker_note`를 받습니다.

## 매칭 품질 평가 하네스

`ai_service/eval/`에 AAC 그림 매칭 품질을 재는 도구가 있습니다. 자세한 설계·튜닝 기록은
`ai_service/eval/README.md`에 있습니다.

```bash
cd ai_service
python eval/run_match_eval.py              # 골든셋(115케이스) 채점, --sweep으로 임계값 곡선
python -m eval.blind_test                  # 코드를 짠 사람이 아닌 LLM이 문장을 새로 만들어 채점
```

## 테스트

```bash
# AI 하네스(분해·매칭·임베딩) 단위 테스트
cd ai_service && pip install -r requirements.txt pytest && python -m pytest -q

# 백엔드 통합 테스트(인증/소유권/막힘/업서트/입력검증 + TTS 합성 경로)
cd backend && pip install -r requirements.txt pytest && python -m pytest -q
```

프론트엔드는 아직 자동화 테스트가 없습니다(`npm run lint`만 있습니다).

LLM·코칭·임베딩 테스트는 OpenAI 호출만 가짜로 대체해 프롬프트→JSON 파싱→스키마 검증→폴백까지
실제 코드를 실행합니다(실 키 불필요). TTS 합성 테스트는 Google 클라이언트만 가짜로 대체하고
mp3 기록·해시 캐시·URL 반환·예외 폴백까지 실제 코드를 실행합니다(실 네트워크 호출 없음).

## 주의

- `data/aac`의 이미지는 프로젝트가 직접 제작했거나 유료 생성형 AI 플랜으로 만든 것입니다
  (`data/aac/aac_assets.json`의 `license_note` 참고). 제3자 픽토그램으로 교체하려면
  라이선스를 먼저 검토하세요.
- Google TTS는 Google Cloud 과금 계정과 예산 알림 설정이 필요합니다.
