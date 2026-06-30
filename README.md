# 잡카드 (JOB CARD) — ARASAAC + Google TTS API 버전

발달장애인 직무 현장 AI 코칭 플랫폼입니다.

```text
직무 입력
→ AI 분해
→ ARASAAC AAC 상징 검색
→ Google Cloud Text-to-Speech mp3 생성/캐싱
→ 근로자 카드
→ 완료 체크
→ 대시보드 집계
```

이번 버전은 AAC를 **ARASAAC**, TTS를 **Google Cloud Text-to-Speech API** 기준으로 고정했습니다. Google 인증 파일이 없거나 API 호출에 실패하면 서비스 전체가 멈추지 않도록 근로자 화면에서 브라우저 SpeechSynthesis fallback을 사용합니다.

## 구조

```text
jobcard-skeleton/
├── ai_service/      AI 하네스 (FastAPI, 8001)
│   ├── main.py        /ai/decompose, /ai/map-symbols
│   ├── decompose.py   규칙 기반 분해기. LLM 교체 지점
│   ├── symbols.py     ARASAAC AAC 상징 검색 연동
│   └── schemas.py     AI 입출력 스키마
├── backend/         백엔드 API (FastAPI, 8000)
│   ├── main.py        직무 생성, 배정, 로그, 대시보드
│   ├── tts.py         Google Cloud TTS API 연동 및 mp3 캐싱
│   ├── models.py      SQLAlchemy ORM
│   ├── ai_client.py   백엔드↔AI 하네스 경계
│   └── schemas.py     프론트 대면 입출력 스키마
└── frontend/        React + TS + Vite + Tailwind (5173)
    └── src/
        ├── api.ts
        ├── pages/ManagerPage.tsx
        ├── pages/WorkerPage.tsx
        └── pages/DashboardPage.tsx
```

## Docker 실행

`docker-compose.yml`이 보이는 프로젝트 루트에서 실행합니다.

```bash
docker compose up --build
```

접속 주소:

| 서비스 | 주소 | 설명 |
| --- | --- | --- |
| 프론트엔드 | http://localhost:5173 | 사용자 화면 |
| 백엔드 API | http://localhost:8000 | FastAPI 백엔드 |
| AI 하네스 | http://localhost:8001 | AI 분해/AAC 상징 매핑 |
| 백엔드 헬스체크 | http://localhost:8000/health | 상태 확인 |
| AI 헬스체크 | http://localhost:8001/health | 상태 확인 |

컨테이너 이름:

```text
jobcard-web
jobcard-api
jobcard-ai
```

DB와 TTS 캐시는 Docker named volume `jobcard-data`에 유지됩니다(macOS 바인드 마운트에서 SQLite가 `disk I/O error`를 내는 문제를 피하기 위해 리눅스 VM 내부 볼륨을 사용). 초기화가 필요하면 `-v` 옵션으로 볼륨까지 함께 제거합니다.

```bash
docker compose down -v
```

특정 볼륨만 제거하려면 다음을 실행합니다(OS 공통).

```bash
docker compose down
docker volume rm jobcard_jobcard-data
```

## AAC: ARASAAC 연동

`ai_service/symbols.py`에서 ARASAAC 검색 API를 호출합니다.

기본 동작:

1. AI 분해 결과의 키워드 후보를 받음
2. 한국어 직무 용어를 영어 후보로 보정(`symbols.py`의 한국어→영어 사전)
3. `ARASAAC_LANGS=en`으로 검색(LLM이 symbol_query를 한국어·영어로 함께 제공)
4. 성공하면 `https://api.arasaac.org/v1/pictograms/{id}?download=false` 이미지를 사용
5. 실패하면 `needs_fallback=true`로 반환하여 사업주 사진 등록 흐름으로 넘길 수 있음

관련 환경변수:

```env
ARASAAC_API_BASE=https://api.arasaac.org
ARASAAC_LANGS=en
ARASAAC_SEARCH_TIMEOUT=2.5          # ARASAAC 응답이 ~1초 걸려 넉넉히 둠(0.5초는 자주 타임아웃)
ARASAAC_KEYWORD_SEARCH_LIMIT=2      # 한국어가 안 잡히면 영어 백업 검색까지 시도
ARASAAC_TERM_SEARCH_LIMIT=1
```

## TTS: Google Cloud Text-to-Speech API

`backend/tts.py`에서 Google Cloud Text-to-Speech API를 호출해 단계 문장을 mp3로 생성하고 캐싱합니다.

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

실제 JSON 키 파일은 Git이나 제출 ZIP에 포함하지 마세요. 현재 ZIP에는 안내용 `secrets/README.md`만 들어 있습니다.

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

### 2) 백엔드

Google TTS 인증 파일을 로컬에서도 쓰려면 `GOOGLE_APPLICATION_CREDENTIALS`를 실제 파일 경로로 설정합니다.

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

## ARASAAC 조회 예시

백엔드가 AI 하네스를 통해 ARASAAC 검색을 중계합니다.

```bash
curl -X POST http://localhost:8000/api/arasaac/search \
    -H "Content-Type: application/json" \
    -d '{"term":"box","langs":["en"],"limit":3}'
```

응답 예시:

```json
{
    "term": "box",
    "matches": [
        {
            "language": "en",
            "term": "box",
            "pictogram_id": "24749",
            "image_url": "https://api.arasaac.org/v1/pictograms/24749?download=false"
        }
    ]
}
```

## 사용 흐름

1. http://localhost:5173 접속
2. **로그인** — 사업주 `demo` / `demo1234`, 또는 근로자 접속 코드 `1234`
3. **사업주 · 직무 만들기** 탭에서 직무 입력
3. `단계로 나누기` 클릭
4. 단계별 ARASAAC 그림과 문장 검토
5. `게시하고 근로자에게 보내기` 클릭
6. **근로자 · 오늘 할 일** 탭에서 카드 확인
7. `다시 듣기` 클릭
   - Google TTS mp3가 있으면 서버 생성 음성 재생
   - mp3가 없거나 인증 실패 시 브라우저 음성합성 fallback 재생
8. `완료` 클릭
9. **사업주 · 대시보드**에서 완료율/소요 시간/다시듣기 횟수 확인

## 아직 mock/스켈레톤인 부분

| 영역 | 현재 상태 | 다음 고도화 |
| --- | --- | --- |
| LLM 분해 | **구현됨**: OPENAI_API_KEY 설정 시 맥락적응 LLM 분해(업종·환경·근로자 특성 반영, 구체 명사 symbol_query 생성). 미설정 시 규칙 기반 폴백. **분해 품질 평가 하네스(`ai_service/eval/`)로 정량 채점** | 프롬프트 튜닝 자동화, 다중 모델 비교 |
| AAC 상징 | ARASAAC 검색 연동 + 한국어 후보 사전 | 자체 사진 DB/상징 후보 선택 UI 추가 |
| TTS | Google Cloud TTS API 연동, 실패 시 브라우저 fallback | 음성 선택 UI, SSML 발음 보정 추가 |
| 인증 | **구현됨**: 토큰 기반 로그인 + 역할(사업주/근로자) + 자원 소유권 검사 | 관리자 역할, 비밀번호 정책, 리프레시 토큰 |
| 대시보드 | 직무 목록 + 완료율/소요/다시듣기/**막힌 단계** 집계 + **AI 코칭 제안**(LLM, 폴백은 휴리스틱) | 근로자별·기관별 비교, 기간 추세 |

## 인증 / 권한

v0.3부터 토큰 기반 인증이 적용됩니다(추가 라이브러리 없이 표준 라이브러리로 구현: `backend/auth.py`).

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
POST /api/auth/login           # 사업주 로그인 -> 토큰
POST /api/auth/worker-login    # 근로자 접속 코드 -> 토큰
GET  /api/tasks                # (사업주) 내 직무 목록
POST /api/tasks                # (사업주) 직무 생성 = AI 분해 트리거
POST /api/tasks/{id}/publish
POST /api/tasks/{id}/assignments
GET  /api/worker/me/today      # (근로자) 오늘 배정된 카드 (소유자+당일 기준)
POST /api/performance-logs     # (근로자) 단계 완료/막힘 보고 (단계당 업서트)
GET  /api/dashboard/tasks/{id} # (사업주) 집계
```

이후 모든 호출은 `Authorization: Bearer <토큰>` 헤더가 필요합니다.

## AI 기능 (OpenAI)

`OPENAI_API_KEY`를 설정하면 두 가지 AI 기능이 켜집니다. **키가 없으면 규칙 기반/휴리스틱으로 자동 폴백**하므로 서비스는 그대로 동작합니다(AI 호출은 ai_service에만 격리됨 — `ai_service/llm.py`).

1. **맥락적응 직무 분해(기능 1)** — 직무 생성 시 업종·작업 환경·근로자 특성을 함께 보내면, LLM이 한 단계=한 동작의 명령형 문장과 AAC 그림 검색용 구체 명사(symbol_query)를 생성합니다. 고정 키워드 매핑보다 상징 적중률이 올라갑니다.
2. **사업주 AI 코칭(기능 2)** — 근로자의 막힘·다시듣기·소요시간을 분석해 단계별 개선책(문장 쉽게/사진 교체/단계 분할)을 제안합니다.

상징(그림) 검색 품질도 개선했습니다: ARASAAC `bestsearch` 우선 사용 + 검색어와 키워드가 정확히 일치하는 픽토그램 우선 선택(첫 결과 무비판 사용 제거) + 영어 픽토그램 검색(`en`). LLM은 `symbol_query`를 한국어·영어로 함께 제공하고, 한국어가 안 잡히면 영어 후보를 백업으로 검색해 픽토그램 적중률을 높입니다. 단일 객체 픽토그램의 한계를 보완하기 위해, **단계별 실제 사진 업로드**도 구현했습니다(기능 5). 사업주가 검토 화면에서 현장 사진을 올리면 ARASAAC 자동 상징을 대체하며, 매직바이트 검증·UUID 파일명·5MB 상한으로 안전하게 저장됩니다(jpg/png/webp/gif, SVG 불허).

또한 **동작 시각화**(기능 4)로, 단계의 동작(확인/옮기기/쌓기/분류/담기/청소)을 색·아이콘·라벨 칩으로 그림 위에 표시합니다. 같은 객체 그림이라도 동작이 구분되며, 결정론적이라(네트워크 의존 없음) 폴백 상징에도 항상 적용됩니다.

설정:

```env
OPENAI_API_KEY=sk-...            # 미설정 시 폴백
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_TIMEOUT=20
```

Docker는 호스트의 `OPENAI_API_KEY`를 자동 주입합니다(`docker compose` 실행 전 `export OPENAI_API_KEY=sk-...`).

추가 엔드포인트:

```text
GET /api/dashboard/tasks/{id}/coaching   # (사업주) AI 코칭 제안
POST   /api/tasks/{id}/steps/{step}/photo  # (사업주) 단계 사진 업로드(상징 대체)
DELETE /api/tasks/{id}/steps/{step}/photo  # (사업주) 사진 제거→기본 상징 복귀
POST /ai/coaching                        # (AI 하네스) 코칭 생성
```

직무 생성(`POST /api/tasks`)은 선택 필드 `business_type`, `work_environment`, `worker_note`를 받습니다.

## 테스트

백엔드와 AI 하네스에는 자동화 테스트가 포함됩니다.

```bash
# AI 분해기 단위 테스트 (쉼표 분할 회귀 포함)
cd ai_service && pip install -r requirements.txt pytest && python -m pytest -q

# 백엔드 통합 테스트 (인증/소유권/stuck/업서트/입력검증 + TTS 합성 경로)
cd backend && pip install -r requirements.txt pytest && python -m pytest -q
```

프론트엔드는 Vitest 컴포넌트 테스트가 포함됩니다(근로자 화면 stuck 수집 로직 등).

```bash
cd frontend && npm install && npm test
```

LLM·코칭 테스트는 OpenAI 호출(chat_json)만 가짜로 대체해 프롬프트→JSON 파싱→스키마 검증→폴백까지 실제 코드를 실행합니다(실 키 불필요). TTS 합성 테스트는 Google 클라이언트만 가짜로 대체하고 mp3 기록·해시 캐시·URL 반환·예외 폴백까지 실제 코드를 실행합니다(실 네트워크 호출 없음).


## 주의

ARASAAC 상징은 라이선스 조건을 반드시 확인해야 합니다. 공모전·비영리 PoC와 상용 SaaS는 사용 조건이 달라질 수 있습니다. Google TTS는 Google Cloud 과금 계정과 예산 알림 설정이 필요합니다.
