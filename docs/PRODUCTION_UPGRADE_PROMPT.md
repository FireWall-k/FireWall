# 잡카드(JobCard) 프로덕션 등급 업그레이드 프롬프트

> 이 프롬프트는 2026-11-06 기준 코드베이스(브랜치 `dev`, 커밋 dd98583 + AAC 데이터 정리분)를 4개 영역(backend, ai_service, frontend, infra) × 독립 검증 에이전트로 감사해 **확인된 격차 72건**을 바탕으로 작성했다. 추측이 아니라 파일·줄 단위 근거가 있는 항목만 담았다.

---

## 역할

너는 발달장애인 직무 현장 AI 코칭 플랫폼 **잡카드(JobCard)** 저장소를 담당하는 시니어 스태프 엔지니어다. 목표는 이 코드베이스를 **대형 IT 기업의 프로덕션 서비스 기준**(보안·신뢰성·관측성·테스트·배포 자동화·접근성·개인정보)으로 끌어올리는 것이다. 사용자는 취약계층(발달장애 근로자)이므로 접근성과 개인정보 보호는 "있으면 좋은 것"이 아니라 핵심 요구사항이다.

## 현재 상태 (사실)

- 스택: FastAPI 백엔드(8000, SQLite, 1126줄 `backend/main.py` 단일 파일) · FastAPI AI 하네스(8001, OpenAI + 자체 AAC 매칭) · React 19 + TS + Vite + Tailwind 프론트(5173) · Docker Compose · GitHub Actions(pytest/vitest만).
- 테스트: backend 96, ai_service 76(데이터 정합성 테스트 포함), frontend 40. 전부 통과. 커버리지 게이트 없음.
- AAC 데이터: 1,049장(9개 직무), 메타데이터·인덱스·임베딩 정합. 매칭 골든셋 115케이스 기준 **top1 0.875 / recall@3 0.977 / 오답채택률 0.139**(LLM 경로), **0.852 / 0.955 / 0.183**(규칙 폴백 경로). 이 수치가 회귀 기준선이다.
- 린터·포매터·타입체커·pre-commit·lockfile·Dependabot·릴리스 파이프라인·마이그레이션 도구·구조적 로깅·메트릭·트레이싱: **전부 없음**.

## 절대 규칙

1. **잘 만들어진 것은 유지한다.** 다음은 이미 프로덕션 수준이므로 재작성하지 말고 그 위에 쌓는다.
   - 소유권 검사(`_owned_task`, 404로 존재 숨김)와 교차 테넌트 테스트
   - 로그인 브루트포스 방어(`backend/ratelimit.py`, Retry-After, `TRUST_FORWARDED_FOR`)
   - 근로자 토큰 폐기용 `cf` 지문, prod에서 약한 `JOBCARD_SECRET` 기동 실패
   - 사진 업로드 매직바이트 검사·크기 제한·UUID 파일명·SVG 거부, `_is_own_image_url`
   - LLM 호출 단일 경계 `ai_service/llm.py:chat_json()` + 규칙 기반 폴백 체계(분해·코칭·임베딩 3단계 모두)
   - 임베딩 digest 검증, 2단계 채택 게이트(임계값+여유)와 거절 사유 구분, 115케이스 골든셋 + 90케이스 홀드아웃 평가 문화
   - 대시보드 폴링의 탭 가시성·중복 요청·stale 응답 처리, 드래그 정렬 낙관적 UI + 롤백
   - 코드 주석이 "왜"를 설명하는 관례(한국어). 새 코드도 같은 관례를 따른다.
2. **작게, 검증 가능하게.** 한 PR = 한 관심사. 모든 PR은 기존 테스트 전부 통과 + 새 동작에 대한 테스트 포함. 매칭 평가 지표가 위 기준선 아래로 내려가면 머지 금지.
3. **마이그레이션 경로를 깨지 않는다.** 기존 SQLite 볼륨(`jobcard-data`)을 가진 설치본이 무중단으로 업그레이드돼야 한다. 스키마 변경은 Alembic 리비전으로만.
4. **비밀값을 절대 커밋하지 않는다.** `.env`, `secrets/*.json`은 건드리지 않는다. 설정 예시는 `.env.example`로만.
5. **외부 API(OpenAI, Google TTS)는 CI에서 호출하지 않는다.** 모두 목/레코딩으로 대체.
6. **커밋 메시지는 기존 관례**(`feat(backend): ...`, `fix(aac): ...`, 한국어 본문)를 따른다.
7. 각 Phase가 끝나면 **변경 파일 목록, 테스트 결과(수치), 평가 지표 전후, 남은 리스크**를 보고한다. 못 한 것은 못 했다고 쓴다.

---

## Phase 0 — 즉시 조치 (보안·법적·접근성 치명 결함)

### 0.1 근로자 접속 코드가 전역 네임스페이스 + 타 테넌트 코드 오라클
- 근거: `backend/main.py:236` 로그인이 employer 스코프 없이 `Worker.access_code`만 조회, `models.py:57` 전역 unique, `POST /api/workers`가 409로 "다른 사업주의 코드가 존재함"을 알려주며 스로틀 없음.
- 할 일: uniqueness를 `(employer_id, access_code)`로 변경(Alembic), 로그인에 사업장 식별(사업장 코드 또는 기기 등록 토큰) 추가, 코드는 해시 저장(`access_code_hash` + 뒤 2자리 힌트)하고 **생성/재발급 응답에서 단 한 번만** 평문 반환, 목록·대시보드 응답에서 제거. 코드를 시험할 수 있는 모든 엔드포인트에 기존 `LoginThrottle` 적용. 교차 테넌트 충돌을 절대 노출하지 않도록 서버가 코드를 생성하거나 409 대신 다른 코드로 201.
- 완료 기준: 테넌트 A의 코드로 테넌트 B에서 로그인·탐지 불가 테스트, 응답 본문에 평문 코드가 없는 테스트.

### 0.2 발달장애 근로자 개인정보가 해외 LLM/TTS로 전송·무기한 보관
- 근거: `ai_service/llm.py:262-263` worker_note를 OpenAI 프롬프트에 주입, `main.py:1043-1066` 근로자 이름+수행 데이터를 코칭 프롬프트에 전송, 동의·보존·삭제·접근감사 없음.
- 할 일: LLM 호출 전 PII 최소화(이름→익명 ID, worker_note는 사업주가 명시적으로 허용한 항목만), 데이터 맵 + `docs/privacy/개인정보처리방침.md`, 근로자별 동의 기록(버전·일시), performance_logs/사진/TTS 보존기간과 스케줄 삭제, 근로자 데이터 열람 감사 로그(append-only), 사업주 셀프서비스 내보내기·삭제(파일까지).
- 완료 기준: 프롬프트 스냅샷 테스트에 실명·노트가 없음, 삭제 API 후 DB·디스크 모두 비어 있음 테스트.

### 0.3 사진·TTS 파일이 인증 없이 공개 서빙, EXIF/GPS 보존, 소유자 레코드 없음
- 근거: `main.py:104-107` StaticFiles 무인증 마운트, `photos.py:40-45` 원본 바이트 그대로 저장, Photo 테이블 없음, `update_step`이 prefix만 맞으면 타 테넌트 이미지 URL 수용.
- 할 일: Photo/Audio 테이블(employer_id FK, 상대 키 저장), 응답 시점에 절대 URL 생성, 인증 엔드포인트 또는 단기 서명 URL로 서빙, 업로드 시 Pillow로 EXIF 제거·리사이즈·재인코딩, `symbol_url` 검증을 prefix가 아닌 소유 레코드 조회로.
- 완료 기준: 타 테넌트 사진 URL 접근 403, 업로드 후 EXIF 없음 테스트, 고아 파일 GC 잡.

### 0.4 근로자 화면 핵심 접근성 클래스가 정의되지 않아 CSS가 생성되지 않음
- 근거: `WorkerPage.tsx`가 `min-h-touch`, `text-worker`, `text-worker-lg`를 20곳 이상 사용하지만 `tailwind.config.js`에 정의 없음 → 터치 타깃·큰 글씨가 실제로 적용되지 않는다.
- 할 일: `theme.extend.minHeight.touch='80px'`, `fontSize.worker/worker-lg` 정의, `eslint-plugin-tailwindcss`(`no-custom-classname: error`)로 CI에서 차단, Playwright+axe로 버튼 높이 ≥80px 단언.

### 0.5 비밀값 전달·스캐닝
- 근거: compose가 OPENAI 키를 env로 주입, `./secrets` 전체를 바인드 마운트, gitleaks/secret scanning 없음, 로컬 `.env`에 실키가 클라우드 동기화 폴더에 있음.
- 할 일: Docker `secrets:`(`/run/secrets/...`) 또는 SOPS/age 암호화 `.env.enc`, Google은 Workload Identity 또는 단기 토큰, pre-commit + CI에 gitleaks, GitHub secret scanning/push protection 활성화 문서화.

---

## Phase 1 — 엔지니어링 기반 (도구·CI·컨테이너·마이그레이션)

1. **Python 툴체인**: 루트 `pyproject.toml`에 ruff(E,F,I,B,UP,S,N,ASYNC; line-length 100) + ruff-format + `mypy --strict`(backend, ai_service). `CurrentUser`를 dict 대신 dataclass로. `uv.lock` 또는 `pip-compile --generate-hashes`로 전이 의존성 고정(`google-cloud-texttospeech>=2.18,<3` 범위 제거).
2. **TypeScript**: `strict: true` + `noUncheckedIndexedAccess`, `typescript-eslint` strict-type-checked, `eslint-plugin-jsx-a11y` strict, Biome 또는 Prettier, `typecheck`/`format:check`/`test:coverage`/`test:e2e` 스크립트, `engines`+`.nvmrc`.
3. **pre-commit**: ruff, ruff-format, mypy, eslint, prettier/biome, gitleaks, hadolint, check-yaml. Husky/lint-staged 또는 Lefthook.
4. **Dependabot** (`pip` ×2, `npm`, `github-actions`, 주간 그룹).
5. **CI 확장** (`.github/workflows/ci.yml`): lint+typecheck 잡을 테스트 앞에, `pytest --cov --cov-fail-under=80` + Codecov, `docker compose build && up --wait && curl /health`, Playwright e2e 잡, `timeout-minutes`, 액션 커밋 SHA 고정, `paths-ignore`.
6. **릴리스 파이프라인** (`release.yml`, `v*.*.*` 태그): `docker/build-push-action` → GHCR(`:sha`, `:semver`), Trivy(HIGH/CRITICAL 실패), syft SBOM, cosign 서명.
7. **컨테이너**: 3개 Dockerfile 모두 멀티스테이지, `python:3.12-slim@sha256:<digest>`, `USER 10001`, `HEALTHCHECK`, `COPY --chown`, tini. 프론트는 `nginxinc/nginx-unprivileged` 8080, `server_tokens off`, gzip/brotli, CSP/HSTS/Permissions-Policy 헤더. compose에 `restart: unless-stopped`, 리소스 제한, `read_only` + tmpfs, `cap_drop: [ALL]`, 로그 로테이션.
8. **Alembic**: `env.py`를 SQLAlchemy metadata에 바인딩, 현재 스키마를 baseline 리비전으로, `database.py`의 `_ADDED_COLUMNS`/`apply_pending_columns()` 제거, `alembic upgrade head`는 lifespan이 아니라 compose 일회성 서비스(`depends_on: service_completed_successfully`)로, CI에 `alembic check`와 "빈 DB에서 전체 마이그레이션 적용" 테스트. 기존 볼륨에서 `alembic stamp` 경로 문서화.

---

## Phase 2 — 백엔드 구조·API·도메인 정합성

1. **패키지 레이아웃**: `backend/app/{api/v1/{auth,workers,tasks,steps,assignments,worker,dashboard}.py, services/, repositories/, core/{config,security,deps}.py, models/, schemas/}` + `create_app()` 팩토리. `get_owned_task/step/worker`를 `Depends`로. 라우터 `prefix="/api/v1"` + 태그, v0 경로는 deprecation 헤더로 한 릴리스 유지.
2. **설정**: `pydantic-settings` `Settings` 하나(typed, `SecretStr`, `Literal['dev','prod']`, prod 불변식 validator). import 시점 `os.getenv` 전부 제거. `.env.example`을 Settings에서 생성해 CI로 drift 검사.
3. **오류 모델**: RFC 9457 `application/problem+json` + `ErrorCode` enum. `RequestValidationError`, `HTTPException`, `IntegrityError`, bare `Exception` 글로벌 핸들러. 내부 메시지 절대 노출 금지(현재 규칙 유지).
4. **인증**: PyJWT/joserfc 액세스 토큰 15분(`kid`, `iss/aud/jti`) + 해시 저장 refresh 토큰(회전·재사용 탐지) + `Employer.token_version` 폐기 + `/logout` `/refresh`. Argon2id(`argon2-cffi`)로 전환하며 로그인 시 투명 재해시. 비밀키는 Settings에 한 번 로드.
5. **데이터 정합성**: `INSERT ... ON CONFLICT DO UPDATE`로 check-then-insert 레이스 제거, `assignments(task_id, worker_id) WHERE status != 'done'` 부분 유니크, `Idempotency-Key` 테이블(POST /tasks, /assignments, /performance-logs). 삭제는 204.
6. **발행 버전 불변성**: `TaskVersion/StepVersion`, 배정은 버전에 고정, 발행 후 편집은 새 초안 버전 생성, step soft-delete로 performance_log 보존(현재 `delete_step`이 로그를 하드 삭제함).
7. **Assignment 상태기계**: scheduled → in_progress → done | cancelled | expired, `scheduled_for`, 이월 정책, 취소/재배정 엔드포인트. 현재는 자정 지나면 미완료 작업이 사라진다.
8. **'막힘' 규칙 단일화**: 임계값(3회 재생/120초)이 프론트·AI 서비스에 중복되고 백엔드는 클라이언트 값을 신뢰함. 서버에 원시 이벤트(help_requested_at, replay, started/completed) append-only 저장 후 서버 측 파생, 막힘은 단조 증가.
9. **성능·목록**: 커서 페이지네이션(`{items, next_cursor}`), `selectinload(Task.steps)`, 대시보드 집계는 GROUP BY 단일 쿼리로 N+1 제거.
10. **AI 경계**: `httpx.AsyncClient`(app.state) + `tenacity`(지터, 멱등 호출만, 총 데드라인) + 서킷브레이커, 또는 `POST /tasks`를 202 잡으로 전환(arq/RQ)하고 상태 폴링. 요청당 `ThreadPoolExecutor` 생성 제거. lifespan teardown에서 클라이언트 close.
11. **보안 헤더·CORS**: 명시적 method/header 허용 목록, `TrustedHostMiddleware`, prod에서 `docs_url=None`, `secure` 미들웨어, uvicorn `--proxy-headers --forwarded-allow-ips`. LLM 기반 엔드포인트(`/tasks`, `/aac/search`, `/coaching`)에 사업주별 토큰버킷 + 일일 LLM 예산.
12. **근로자 공용 태블릿 세션**: 근로자 역할 토큰 TTL을 교대 길이로, 유휴 자동 로그아웃, 재개 시 본인 확인.
13. **DB 전환 준비**: `DateTime(timezone=True)`, `ZoneInfo('Asia/Seoul')`, SQLite 전용 `date(col, '+9 hours')` 제거 → Postgres(psycopg3) 지원. 레이트리밋 상태를 Redis로 옮겨 멀티 프로세스 허용.
14. **테스트**: 트랜잭션 롤백 픽스처(모듈 전역 SQLite 파일 공유 제거), `pytest-xdist`, `pytest-randomly`, 커버리지 85%.

---

## Phase 3 — AI 서비스 (ai_service)

1. **설정 통합**: `ai_service/config.py` `Settings`(범위 검증: `match_threshold: Field(0.22, ge=0, le=1)` 등), lifespan에서 한 번 로드, `decide()`/`_score_asset()`에 파라미터로 주입. 현재 `.env`의 `AAC_MATCH_THRESHOLD=0.14`와 compose의 `0.22`처럼 값이 갈라지는 문제를 기동 시 로그로 노출.
2. **LLM 호출 신뢰성·비용**: `chat_json`/`embed_texts`를 tenacity로 감싸기(408/429/5xx/Timeout만, Retry-After 존중, 총 데드라인). 호출마다 구조적 이벤트: model, `PROMPT_VERSION`(예: `decompose/v3`), prompt/completion tokens, latency_ms, finish_reason, outcome. `usage`를 읽어 사업주별 일일 토큰 예산.
3. **프롬프트 안전**: 사업주 자유 텍스트·worker_note를 구분자로 격리(현재 문자열 join), 출력 모더레이션(한국어 규칙 + moderation API), 응답 로깅은 PII 마스킹. 코칭 결과는 항목 단위로 정규화(한 항목의 enum 오류가 전체 폴백을 유발하지 않게) + 테스트.
4. **백엔드↔AI 계약**: `jobcard_contracts` 공유 패키지 또는 ai_service OpenAPI → `datamodel-codegen`로 백엔드 모델 생성. `ai_client`에서 Pydantic으로 응답 검증(현재 raw dict 인덱싱 → KeyError 500). CI에 schemathesis/Pact 계약 테스트. `AacMatch` 중복 정의 제거. AI는 `image: "retail/RETAIL_029.webp"` 상대 키만 반환하고 URL은 백엔드가 만든다.
5. **내부 인증**: `AI_SERVICE_TOKEN`(Docker secret) + 상수시간 비교 `Depends`, compose `networks: internal: true`로 격리.
6. **평가 CI 게이트**: `eval/baselines/match_{full,sentence}.json` 커밋, pytest에서 절대 하한 단언(현재 기준선 full top1 ≥0.875, wrong_accept ≤0.139, recall@3 ≥0.977; 개선되면 베이스라인을 올린다), PR에 지표 델타 표(Job Summary). 분해 평가(`eval/dataset.json`, 현재 15케이스)를 50케이스 이상으로 늘리고 루브릭을 현재 프롬프트 계약과 일치시킨다. `OPENAI_API_KEY`가 있는 야간 스케줄 워크플로로 LLM 경로 평가.
7. **성능**: 질의당 ~2,100회 `difflib.SequenceMatcher` 순차 호출 → `rapidfuzz`, 자산별 피처 사전 계산, job/verb_class 프리필터, lifespan에서 워밍업, `pytest-benchmark` p95 예산(<30ms) + `aac_search_seconds` 히스토그램.
8. **코드 품질**: `src/` 레이아웃 패키지화(`sys.path` 해킹 제거), 자산 dict의 `_`접두 매직 키를 `@dataclass(frozen=True, slots=True) Asset`으로, `MatchDecision` 타입화. `local_aac.infer_job`과 `taxonomy.infer_job_text`의 동점 규칙이 반대인 문제를 하나로 통합 + 동점 테스트.
9. **관측성**: structlog JSON + `asgi-correlation-id`(백엔드의 `X-Request-ID`전파), OpenTelemetry FastAPI/httpx, Prometheus(`decompose_mode_total{mode}`, `symbol_decision_total{reason}`, `embed_cooldown_total`). `/health/live`와 `/health/ready` 분리(ready는 자산·인덱스·임베딩 로드 상태 검사).
10. **에러 응답**: problem+json + `code` enum, 예외 텍스트 노출 금지, `/v1` 라우터.
11. **스크립트·데이터**: `scripts/enrich_aac_metadata.py`의 약 1,850줄 분류 사전을 `data/aac/taxonomy/*.yaml`(JSON Schema 검증)로 분리, `scripts/`를 `[project.scripts]`로 설치 가능하게, `infer_action/infer_objects` 단위 테스트. AAC 데이터셋 매니페스트(파일별 sha256, 버전, 출처·라이선스 필드) + CI에서 인덱스/임베딩 staleness 검사(`build_aac_embeddings.py --check`). 이미지·npz는 Git LFS.

---

## Phase 4 — 프론트엔드

1. **데이터 계층**: TanStack Query v5(`queryKeys` 팩토리, 대시보드 `refetchInterval: 3000` + `refetchIntervalInBackground: false`, 모든 쓰기는 `useMutation` + `invalidateQueries`), `AbortSignal`·타임아웃·재시도, 전역 `QueryCache.onError`로 `AuthError` → 로그아웃. `uploadStepPhoto`의 중복 401 처리 제거.
2. **타입 안전**: `openapi-typescript` + `openapi-fetch`(CI에서 스키마 diff 검사) 또는 Zod `schema.parse`. `ApiError { kind: 'auth'|'forbidden'|'validation'|'http'|'network', fieldErrors }`로 FastAPI 422 `detail[]` 평탄화. `src/types/index.ts`의 죽은 타입(pick/place/check, a11yPrefs) 삭제. `ACTION_META`를 `Record<ActionType, ...>`로 만들어 taxonomy(wear/operate/assemble 누락) 불일치를 컴파일 오류로.
3. **복원력·성능**: `react-error-boundary` + 한국어 폴백 + 재시도 버튼, 페이지별 `React.lazy`(근로자 라우트가 recharts를 받지 않게), `manualChunks`, 폰트 self-host + preload, `size-limit` CI 예산(현재 단일 655KB 번들).
4. **텔레메트리**: `@sentry/react`(release = git SHA) 또는 OTel web, `web-vitals`, 요청별 `X-Request-Id`(crypto.randomUUID) 생성·백엔드 에코. `WorkerPage.tsx`의 빈 `catch {}` 제거 → 보고 + 사용자 피드백.
5. **인증·세션**: httpOnly/Secure/SameSite 쿠키(백엔드 발급) 또는 메모리 액세스 토큰 + refresh. `AuthProvider` 컨텍스트, 401 시 상태 갱신·네비게이션. nginx CSP(`default-src 'self'; connect-src <api>`), 근로자 역할은 sessionStorage/짧은 TTL + 유휴 로그아웃.
6. **접근성**: `eslint-plugin-jsx-a11y` strict, 모든 페이지 테스트에 `vitest-axe`, `@dnd-kit/core` + `KeyboardSensor`로 키보드 정렬, 캘린더 팝오버·`window.confirm`을 Radix/React Aria Dialog로(포커스 트랩, Escape), 이모지 `aria-hidden` + 텍스트 라벨, 근로자 화면 첫 오디오는 명시적 '시작하기' 제스처 뒤 자동재생 + 재생/실패 표시.
7. **구조**: `src/features/{tasks,workers,dashboard,worker}/{api,hooks,components,model}`로 분할(ManagerPage 808줄·20 useState, DashboardPage 591줄). 순수 규칙(`needsConfirm`, `isStuck`)은 `model.ts`. ESLint `max-lines: 300`. UI 문자열은 `src/i18n/messages.ko.ts`로(현재 ManagerPage/WorkersPage에 같은 문구 중복).
8. **오프라인·진행 보존**: `vite-plugin-pwa`로 근로자 라우트·AAC 이미지·TTS 프리캐시, `POST /api/performance-logs` Background Sync 큐, 진행 상태(`assignment_id, stepIdx, startedAt`) IndexedDB 보존 후 재개.
9. **테스트**: MSW 핸들러를 Vitest·Playwright가 공유(`api.ts` 실제 커버, 401/403/422 픽스처), `@vitest/coverage-v8` 임계값, Playwright 골든 패스 2개(사업주: 로그인→분해→그림 확인→게시/배정, 근로자: 코드 로그인→전 단계 완료→대시보드 100%)를 compose 스택에 대해 실행.
10. **런타임 설정**: `VITE_API_BASE` 빌드 타임 고정 제거 → entrypoint가 `config.json` 생성, 앱이 부팅 시 읽음. 컨테이너 HEALTHCHECK.
11. `frontend/README.md`를 현재 아키텍처(라우트 표, env, 스크립트, 테스트 전략)로 재작성(현재 존재하지 않는 mock 프로토타입을 설명함).

---

## Phase 5 — 관측성·운영

1. 백엔드·AI 공통: structlog JSON(request_id, employer_id, task_id, latency), `asgi-correlation-id`, OpenTelemetry(FastAPI/SQLAlchemy/httpx → OTLP), `prometheus-fastapi-instrumentator` RED 메트릭, Sentry. `/healthz`(liveness) / `/readyz`(SELECT 1 + ai_service `/health` + data dir 쓰기 가능) 분리. uvicorn `--timeout-graceful-shutdown 30`.
2. 운영 compose: `compose.yml` + `compose.prod.yml` 오버레이(Caddy/Traefik 자동 TLS, 127.0.0.1 포트 바인딩 제거, 내부 네트워크), 로그 로테이션.
3. 백업: 단기 Litestream 사이드카(WAL 연속 복제) + 야간 `sqlite3 .backup` 30일 보존 + **복구 리허설 문서(`docs/RUNBOOK.md`)**; 중기 Postgres 전환(`pg_dump` 잡).
4. 시작 시 DDL·시드가 요청 프로세스에서 실행되는 구조 제거(Phase 1.8과 연결).

---

## Phase 6 — 문서·거버넌스

- `LICENSE`(코드) + `data/aac/LICENSE`(이미지, 현재 `license_note`만 존재), `CONTRIBUTING.md`(셋업·테스트·커밋 컨벤션), `CODEOWNERS`(`backend/auth.py`, `**/Dockerfile`, `.github/`), `SECURITY.md`, `CHANGELOG.md`(release-please), `docs/adr/`(MADR: SQLite+named volume, 로컬 AAC 채택, 선택적 임베딩, 폴링 vs SSE, 토큰 저장 위치), `RUNBOOK.md`(장애 유형별), C4 L2 아키텍처 다이어그램, OpenAPI `summary/tags/responses`(problem+json 예시). `dev`·`main` 브랜치 보호 규칙(리뷰 1명 + CI 필수).

---

## 작업 순서와 보고 형식

- 순서는 Phase 0 → 1 → 2/3(병렬 가능) → 4 → 5 → 6. Phase 0·1 없이 뒤 단계를 시작하지 않는다.
- 각 항목마다: (a) 근거 파일·줄을 먼저 다시 확인하고, (b) 실패하는 테스트를 먼저 쓰고, (c) 구현하고, (d) 전체 테스트 + 매칭 평가(`python -m eval.run_match_eval`, `--query-mode sentence`)를 돌린 뒤, (e) 보고한다.
- 보고 템플릿:
  ```
  ## <Phase>.<항목>
  변경: <파일 목록>
  테스트: backend N passed / ai_service N passed / frontend N passed / e2e N passed
  평가: full top1 x.xxx (기준 0.875) · wrong_accept x.xxx (기준 0.139) · sentence top1 x.xxx (기준 0.852)
  마이그레이션: <리비전 ID 또는 없음>
  남은 리스크·후속: ...
  ```
- 하지 말 것: 한 PR에 여러 Phase 섞기, 테스트 삭제·skip으로 통과시키기, 기준선 JSON을 낮춰서 통과시키기, 비밀값 커밋, 한국어 사용자 문구를 영어로 바꾸기, 기존 "왜" 주석 삭제.
