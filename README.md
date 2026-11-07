# 잡카드 (JOB CARD)

발달장애인 직무 현장 AI 코칭 플랫폼입니다.

```text
직무 입력(사업주 말투 한 문단)
→ LLM 맥락적응 분해(업종·환경 반영, 한 단계=한 동작)
→ 자체 AAC 그림 데이터셋(1,049장, 9개 직무) 검색·자동 채택
→ Google Cloud Text-to-Speech mp3 생성/캐싱
→ 근로자 카드
→ 완료/막힘 체크
→ 대시보드 집계(3초 폴링) + AI 코칭 제안
```

AAC 그림은 더 이상 외부 API(ARASAAC)를 쓰지 않고, **프로젝트가 직접 제작한 로컬 자산**
(`data/aac/`, 조립·카페·청소·포장·마트·배송·진열·주유소·서빙 9개 직무 1,049장)을 규칙 기반
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
│   ├── photos.py           단계별 현장 사진 업로드(EXIF 제거·리사이즈·WebP 재인코딩)
│   ├── media.py            사진·TTS 소유 레코드·서명 URL·고아 파일 정리(gc-media)
│   ├── models.py           SQLAlchemy ORM
│   ├── db_migrate.py       Alembic 실행기(레거시 DB 보정·stamp·기동 시 head 확인)
│   ├── migrations/         Alembic 리비전(스키마 변경은 여기로만)
│   ├── manage.py           운영 명령(migrate, create-employer, set-password, purge, gc-media)
│   ├── ai_client.py        백엔드↔AI 하네스 경계
│   └── schemas.py          프론트 대면 입출력 스키마
├── frontend/          React + TS + Vite (5173)
│   └── src/pages/
│       ├── LoginPage.tsx      사업주/근로자 로그인
│       ├── ManagerPage.tsx    직무 생성·검토·게시
│       ├── WorkersPage.tsx    근로자 관리
│       ├── WorkerPage.tsx     근로자 오늘 할 일 카드
│       └── DashboardPage.tsx  완료율/소요/막힘/AI 코칭 대시보드
├── data/aac/           프로젝트 소유 AAC 이미지·메타데이터(1,049장, 9개 직무)
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

초기화가 필요하면 볼륨까지 함께 제거합니다.

```bash
docker compose down -v
```

특정 볼륨만 제거하려면 다음을 실행합니다(OS 공통).

```bash
docker compose down
docker volume rm jobcard_jobcard-data
```

### 스키마 변경과 마이그레이션 (Alembic)

스키마는 `backend/migrations/versions/`의 Alembic 리비전으로만 바꿉니다. `docker compose up`을
하면 일회성 `migrate` 서비스가 `python manage.py migrate`로 DB를 최신(head)으로 올린 뒤에야
`backend`가 뜹니다(`depends_on: service_completed_successfully`). 요청을 받는 서버 프로세스는
스키마를 바꾸지 않습니다.

- **운영(`JOBCARD_ENV=prod`)**: DB가 head가 아니면 백엔드가 "먼저 `python manage.py migrate`를
  실행하라"는 메시지와 함께 **기동을 거부**합니다.
- **개발**: `uvicorn main:app`만 띄워도 기동 시 자동으로 head까지 올립니다(편의).

모델을 바꿨다면 리비전을 만들고, 생성된 파일을 검토한 뒤 함께 커밋합니다.

```bash
cd backend
alembic revision --autogenerate -m "workers에 xxx 컬럼 추가"   # 생성 파일을 반드시 손으로 확인
python manage.py migrate                                        # 로컬 DB에 적용
alembic check                                                   # 모델과 리비전이 일치하는지(CI도 검사)
```

SQLite는 `ALTER TABLE`로 컬럼 변경·삭제를 못 하므로 `render_as_batch=True`(테이블 재생성 + 복사)로
동작합니다. 새 컬럼은 기존 행을 채울 수 있게 NULL 허용이거나 `server_default`가 있어야 합니다.

#### Alembic 도입 전 볼륨(`jobcard-data`) 업그레이드

이전 버전으로 만든 DB에는 `alembic_version` 테이블이 없고, 일부 컬럼(`tasks.business_type`,
`tasks.work_environment`, `tasks.job`, `steps.symbol_query`)이 빠져 있을 수 있습니다. 이런 DB에
`alembic upgrade head`를 바로 하면 이미 있는 테이블을 또 만들려다 실패하므로, **반드시
`manage.py migrate`를 씁니다**(compose는 자동으로 이 명령을 실행합니다). 이 명령은

1. `alembic_version`이 없고 앱 테이블이 있으면 레거시 DB로 판단하고,
2. 빠진 컬럼을 `NOT NULL DEFAULT ''`로 추가하고(예전 코드가 NULL 허용으로 붙인 컬럼은 NULL을 ''로
   채운 뒤 NOT NULL로 조임), 빠진 테이블은 baseline 정의로 만든 다음,
3. baseline 리비전(`0001_baseline`)으로 `stamp`하고, 이어서 `upgrade head` 합니다.

데이터는 지우지 않으며 여러 번 실행해도 안전합니다. 업그레이드 전 백업을 권장합니다(아래 "백업").
명령은 추가한 컬럼과 **NOT NULL로 바꾼 컬럼**(기존 NULL은 빈 문자열로 채움)을 출력하므로 백업과 대조할 수 있습니다.

```bash
docker compose build                 # backend 이미지(jobcard-backend)를 한 번만 빌드 — migrate·purge도 이 이미지를 쓴다
docker compose run --rm migrate      # 출력 예: 기존(Alembic 도입 전) DB를 baseline으로 등록했습니다 ... / NOT NULL로 바꾼 컬럼: ...
docker compose up -d
```

`migrate`·`purge` 등은 `build` 없이 `image: jobcard-backend` + `pull_policy: never`로 backend가 빌드한
이미지를 같이 씁니다(이중 빌드 방지). 그래서 `docker compose run --rm migrate`만 단독으로 처음 실행하면
"이미지가 없다"는 오류가 나므로 먼저 `docker compose build`를 합니다(`up`은 알아서 먼저 빌드합니다).

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
GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/google_tts_credentials   # compose가 Docker secret으로 넘긴다
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

Docker Compose는 이 파일 하나만 Docker secret(`google_tts_credentials`)으로 backend 컨테이너의
`/run/secrets/google_tts_credentials`에 넘깁니다(예전처럼 `./secrets` 폴더 전체를 마운트하지 않습니다).
처음에는 `sh scripts/init-secrets.sh`(Windows: `scripts\init-secrets.ps1`)로 빈 자리표시자 파일을
만들어 두세요 — 원본 파일이 없으면 compose가 기동을 거부합니다. 파일이 비어 있으면 TTS는 ADC(Workload
Identity 등)를 시도하고, 그것도 없으면 브라우저 음성으로 대체됩니다.

실제 JSON 키 파일은 Git에 커밋하지 마세요(`.gitignore`로 제외됩니다). 서비스 계정 키 대신 단기
자격증명을 쓰는 방법과 키 교체 절차는 [docs/security/secrets.md](docs/security/secrets.md)에 있습니다.

### Google TTS 동작 방식

```text
사업주가 직무 입력
→ AI가 단계 문장 생성
→ 백엔드가 각 단계 문장을 Google TTS로 mp3 생성
→ 사업장별 캐시(data/tts/<hash>.mp3)에 저장하고 소유 레코드(media_files)를 만든다
→ 응답에는 단기 서명 URL(/api/media/<id>?exp=&sig=)을 싣는다(정적 공개 경로 없음)
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
2. **로그인** — 사업주 `demo` / `demo1234`, 또는 근로자 탭에서 사업장 코드 `DEMO01`(기기에 한 번만 입력) + 접속 코드 `1234`
3. **사업주 · 직무 만들기** 탭에서 업종·작업 환경과 함께 직무를 사업주 말투로 입력
4. `단계로 나누기` 클릭 — LLM이 한 단계=한 동작으로 분해
5. 단계별 AAC 그림과 문장 검토(자동 채택 안 된 단계는 후보를 보여주거나 사업주 사진 등록)
6. `게시하고 근로자에게 보내기` 클릭
7. **근로자 · 오늘 할 일** 탭에서 카드 확인, `다시 듣기` 클릭(mp3 또는 브라우저 음성)
8. `완료`/`막힘` 클릭
9. **사업주 · 대시보드**에서 완료율/소요 시간/다시듣기 횟수/막힌 단계 + AI 코칭 제안 확인
   (3초 자동 갱신)

## 인증 / 권한

토큰 기반 인증(추가 라이브러리 없이 표준 라이브러리로 구현: `backend/auth.py`).

- 비밀번호: `pbkdf2_hmac(sha256, 200k)` + 랜덤 솔트
- 토큰: HMAC-SHA256 서명 JSON (`sub`, `role`, `exp`)
- 모든 자원 엔드포인트는 인증 + **소유권 검사**(타 사업주의 직무는 404)
- 근로자 로그인 = **사업장 코드 + 접속 코드**. 사업장 코드는 사업주마다 서버가 만드는 6자리
  대문자·숫자(헷갈리는 0/O/1/I 제외)이고 근로자 관리 화면에 보인다. 근로자 기기의 로그인 화면에
  한 번 입력하면 그 기기에 저장되고(바꾸려면 "이 기기 사업장 변경"), 근로자는 자기 접속 코드만 누른다.
  접속 코드는 **사업장 안에서만** 겹치지 않으면 되므로 다른 사업장과 같은 코드를 써도 되고,
  다른 사업장 근로자의 코드를 알아내거나 그 코드로 로그인할 수 없다.
- 접속 코드는 평문으로 저장하지 않는다: `HMAC-SHA256(JOBCARD_SECRET, "사업주id:코드")` 해시와 뒤 2자리
  힌트만 둔다. 평문은 근로자 추가·코드 재발급 응답에서 **한 번만** 보여 주고, 목록·대시보드에는
  힌트(`••34`)만 나온다. 그래서 **`JOBCARD_SECRET`를 바꾸면 기존 접속 코드가 모두 무효**가 된다 —
  키를 교체했다면 근로자 관리 화면에서 코드를 전부 다시 만들어 근로자에게 알려 줘야 한다.
  Alembic 리비전 `0002_workplace_code`가 예전 평문 코드를 마이그레이션 시점의 `JOBCARD_SECRET`로
  해시하므로 migrate 서비스와 backend는 같은 키를 받아야 한다(docker-compose.yml에 반영됨).
- 근로자 접속 코드: 비워 두면 서버가 겹치지 않는 **6자리 무작위 숫자**를 발급한다. 직접 정할 때는
  4~12자리 숫자만 받는다(4자리는 자동 발급 6자리보다 대입에 약하니 짧게 정할수록 로그인 시도
  제한이 실질적인 방어선이 된다). 예전의 짧은 코드는 계속 로그인되지만 근로자 관리 화면에서 경고하고
  "코드 새로 만들기"(`POST /api/workers/{id}/access-code`)로 바꿀 수 있다. 바꾸면 그 근로자의 기존
  로그인 토큰도 바로 무효가 된다. 코드를 직접 정하는 요청도 같은 사업장 안 중복(409)을 시험하는
  통로가 될 수 있어 근로자 로그인과 같은 시도 제한을 사업주 단위로 건다.
- 로그인 시도 제한(`backend/ratelimit.py`): 사업주는 IP·계정별 15분에 10회, 근로자는 IP별 10분에
  30회 실패하면 잠시 막는다(429). 한 작업장이 IP 하나를 같이 쓰므로 근로자 쪽은 넉넉하게 잡았다.
  프로세스 메모리에서 세므로 **uvicorn 단일 프로세스** 운영을 전제로 한다.
- 단계 그림 URL은 이 서버의 AAC 이미지·업로드 사진만 받는다(외부 이미지를 근로자 화면에 못 띄움).

데모 계정(개발 모드에서만 자동 생성, 환경변수로 변경 가능):

| 역할 | 자격증명 | 환경변수 |
| --- | --- | --- |
| 사업주 | `demo` / `demo1234` | `DEMO_EMPLOYER_LOGIN`, `DEMO_EMPLOYER_PASSWORD` |
| 근로자 | 사업장 코드 `DEMO01` + 접속 코드 `1234` | `DEMO_WORKPLACE_CODE`, `DEMO_WORKER_CODE` |

데모 값은 데모 사업주가 **처음 만들어질 때만** 쓰인다. 이 변경 전에 만든 개발 DB에서는 마이그레이션이
데모 사업장에도 무작위 사업장 코드를 발급하므로, 사업주 `demo`로 로그인해 근로자 관리 화면에서 확인한다.

운영 설정은 아래 [운영 배포](#운영-배포)를 따른다. `JOBCARD_ENV=prod`에서는 데모 계정을 만들지 않는다.

주요 엔드포인트:

```text
POST /api/auth/login                        # 사업주 로그인 -> 토큰
POST /api/auth/worker-login                 # 근로자 사업장 코드 + 접속 코드 -> 토큰
GET  /api/workplace                         # (사업주) 내 사업장 코드
POST /api/workers                           # (사업주) 근로자 추가(접속 코드 비우면 자동 발급)
POST /api/workers/{id}/access-code          # (사업주) 접속 코드 재발급(평문은 이 응답에서만)
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

Docker에서는 키를 환경변수가 아니라 Docker secret 파일 `secrets/openai_api_key.txt`에 넣습니다
(컨테이너에는 `/run/secrets/openai_api_key`로 보이고 `OPENAI_API_KEY_FILE`이 그 경로를 가리킨다).
환경변수 키는 `docker inspect` 등에 그대로 보이기 때문입니다. compose는 이제 `OPENAI_API_KEY` 환경변수를
**넘기지 않습니다**. `.env`에 키를 두던 설치본은 `sh scripts/init-secrets.sh`(Windows: `scripts\init-secrets.ps1`)를
한 번 실행하면 그 값을 `secrets/openai_api_key.txt`로 옮겨 줍니다(값은 화면에 출력하지 않음). 옮긴 뒤 `.env`의
값은 지웁니다. 컨테이너 밖 로컬 실행(`uvicorn` 직접)은 예전처럼 환경변수 `OPENAI_API_KEY`도 읽습니다 —
자세한 우선순위는 [docs/security/secrets.md](docs/security/secrets.md).

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

# 프론트엔드 컴포넌트 테스트(Vitest + Testing Library, frontend/tests/)
cd frontend && npm install && npm test
```

`frontend/tests/`에는 로그인·근로자 화면(오늘 할 일/지난 일 보기)·사업주 화면(사진 업로드/다인
배정/자동 선택 그림 확인)·근로자 관리(접속 코드 발급·재발급)·대시보드·동작 시각화 테스트가 있습니다.

푸시·PR마다 GitHub Actions(`.github/workflows/ci.yml`)가 세 부분의 테스트와 프론트엔드 린트·빌드를
돌립니다. 외부 API 키 없이 돕니다(AI 호출·TTS는 테스트에서 목으로 대체).

LLM·코칭·임베딩 테스트는 OpenAI 호출만 가짜로 대체해 프롬프트→JSON 파싱→스키마 검증→폴백까지
실제 코드를 실행합니다(실 키 불필요). TTS 합성 테스트는 Google 클라이언트만 가짜로 대체하고
mp3 기록·해시 캐시·URL 반환·예외 폴백까지 실제 코드를 실행합니다(실 네트워크 호출 없음).

## 운영 배포

단일 서버에 `docker compose`로 올리는 구성이다. 순서대로 확인한다.

1. **비밀값 파일 만들기** — `sh scripts/init-secrets.sh` 후 값을 넣는다(비밀값은 `.env`에 두지 않는다,
   [docs/security/secrets.md](docs/security/secrets.md)).
   - **새 설치**: 키를 새로 만든다.
     ```bash
     python -c "import secrets; print(secrets.token_urlsafe(48))" > secrets/jobcard_secret.txt
     printf '%s' 'sk-...' > secrets/openai_api_key.txt      # 없으면 규칙 기반으로 동작
     ```
   - **기존 설치본 업그레이드**: `JOBCARD_SECRET`를 **새로 만들지 않는다.** 지금 쓰던 값(`.env`의
     `JOBCARD_SECRET`)을 그대로 `secrets/jobcard_secret.txt`로 옮긴다 — 값이 바뀌면 발급된 로그인 토큰,
     근로자 접속 코드 해시, 사진·TTS 서명 URL이 **전부 무효**가 되어 근로자 전원의 접속 코드를 다시 발급해야
     한다. `.env`에 값이 있으면 `sh scripts/init-secrets.sh`가 파일이 없거나 비어 있을 때 그대로 옮겨 준다
     (`OPENAI_API_KEY`도 같이, 값은 출력하지 않음). 옮긴 뒤 `.env`의 두 값을 지운다.
   - 비밀값은 프로세스가 **기동할 때 한 번** 읽는다. 파일을 바꾼 뒤에는
     `docker compose up -d --force-recreate backend ai_service`로 다시 띄워야 반영된다.
   **`.env` 채우기** (`.env.example` 참고, 비밀값이 아닌 설정만)
   ```env
   JOBCARD_ENV=prod
   CORS_ORIGINS=https://jobcard.example.kr
   PUBLIC_BACKEND_URL=https://api.jobcard.example.kr
   VITE_API_BASE=https://api.jobcard.example.kr
   TRUST_FORWARDED_FOR=1          # HTTPS 리버스 프록시 뒤일 때만
   ```
   `JOBCARD_ENV=prod`인데 시크릿이 비었거나 32자 미만이면 백엔드가 **기동을 거부**한다.
2. **HTTPS**: 컨테이너 포트는 `127.0.0.1`에만 열려 있다. 앞에 리버스 프록시(Caddy/nginx)를 두고
   프론트(5173)와 API(8000)를 각 도메인으로 연결한다. 근로자 접속 코드가 평문으로 오가므로 HTTP로 공개하지 않는다.
3. **기동 후 사업주 계정 만들기** (운영에서는 데모 계정이 없다). `up`이 `migrate` 서비스로 스키마를 먼저
   올린다(위 "스키마 변경과 마이그레이션" 참고).
   ```bash
   docker compose up -d --build
   docker compose exec backend python manage.py create-employer --login itda --org "잇다 보호작업장"
   ```
4. **Google TTS**: 서비스 계정 JSON을 `secrets/google-tts.json`에 두고, **해당 GCP 프로젝트에 결제가
   연결돼 있어야 한다**(없으면 403 → 브라우저 음성으로 대체되며, 실패 후 5분간은 호출을 건너뛴다).
5. **보존기간 삭제**: `scheduler` 서비스가 `up`과 함께 떠서 하루 한 번 `purge`(보존기간 지난 수행 로그·접근
   감사 로그 + 고아 사진·TTS 정리)를 돌린다. crontab 등록은 필요 없다. 마지막 성공은 `GET /health`의
   `purge.last_success_at`·`age_hours`·`stale`로 확인한다(정책: [docs/privacy/data-map.md](docs/privacy/data-map.md) 5절).
6. **백업**: DB는 named volume `jobcard-data`의 `jobcard.db`(SQLite, WAL 모드). 예:
   `docker compose exec backend python -c "import sqlite3; s=sqlite3.connect('/app/data/jobcard.db'); d=sqlite3.connect('/app/data/backup.db'); s.backup(d)"`

알려진 한계: DB는 SQLite만 지원한다(날짜 집계가 SQLite 전용 문법). 로그인 시도 제한이 프로세스
메모리 기반이라 uvicorn 워커를 늘리려면 Redis 같은 공유 저장소로 바꿔야 한다.

## 주의

- `data/aac`의 이미지는 프로젝트가 직접 제작했거나 유료 생성형 AI 플랜으로 만든 것입니다
  (`data/aac/aac_assets.json`의 `license_note` 참고). 제3자 픽토그램으로 교체하려면
  라이선스를 먼저 검토하세요.
- Google TTS는 Google Cloud 과금 계정과 예산 알림 설정이 필요합니다.
