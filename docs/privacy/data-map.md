# 개인정보 데이터 맵 (잡카드)

> 기준: Phase 0.2 (2026-11-07). 코드가 바뀌면 이 문서도 같이 고친다 — 특히 `backend/privacy.py`, `backend/retention.py`, `backend/main.py`의 AI 호출부, `ai_service/schemas.py`.
> 법무 검토 전 초안이다. 보존기간의 법적 근거는 법무 검토로 확정해야 한다.

## 1. 정보 주체와 데이터 항목

| 주체 | 항목 | 민감도 | 비고 |
|---|---|---|---|
| 근로자(발달장애인) | 표시 이름(`workers.display_name`) | 개인정보 | 사업주가 입력. 실명일 가능성이 높다 |
| 근로자 | 접속 코드 | 인증정보 | 평문 저장 안 함. `HMAC(JOBCARD_SECRET, employer_id:code)` + 뒤 2자리 힌트 |
| 근로자 | 사업주 메모(`workers.note`) | **민감 가능** | 장애 특성·건강 관련 내용이 들어가기 쉽다 |
| 근로자 | 배정 이력(`assignments`) | 개인정보 | 어느 날 어떤 직무를 받았는지 |
| 근로자 | 단계별 수행 로그(`performance_logs`) | **민감 가능** | 소요시간·다시듣기·막힘 — 인지 특성을 추정할 수 있다 |
| 근로자 | 동의 기록(`worker_consents`) | 개인정보 | 동의 종류·주체(당사자/보호자)·방침 버전·일시·철회 일시 |
| 사업주 | 아이디, 비밀번호 해시(PBKDF2), 사업장명 | 개인정보 | |
| 사업주 | 접근 감사 로그(`access_audit_logs`) | 접속기록 | actor id, 행위, 근로자 id, 시각, IP. 이름은 담지 않는다 |
| 사업주 | 직무 원문·단계 문장(`tasks`, `steps`) | 업무 정보 | 사업주가 근로자 이름을 적을 수 있다 → 아래 "별칭" 참고 |
| 사업주 | 단계 사진(`data/photos`) | 업무 정보 | 현장 사진. 사람이 찍힐 수 있다(EXIF 제거는 Phase 0.3) |

## 2. 저장 위치

| 데이터 | 위치 | 비고 |
|---|---|---|
| DB 전체 | SQLite `jobcard.db` (Docker named volume `jobcard-data`, `/app/data`) | WAL 모드. `secure_delete=ON`으로 지운 행을 0으로 덮는다 |
| TTS mp3 | `/app/data/tts/<sha256>.mp3` | 단계 문장 음성. 파일명은 문장 해시 |
| 단계 사진 | `/app/data/photos/<uuid>.<ext>` | |
| 브라우저 | `localStorage`: 토큰, 역할, 표시 이름, 사업장 코드 | 공용 기기는 로그아웃 필요 |
| 내보내기 파일 | 사업주 PC(다운로드) | 서버에는 사본을 남기지 않는다 |

## 3. 외부 전송 (처리 위탁·국외 이전)

| 수신자 | 국가 | 언제 | 보내는 것 | 보내지 않는 것 |
|---|---|---|---|---|
| OpenAI (Chat Completions, `OPENAI_MODEL`) | 미국 | 직무 분해(`/ai/decompose`) | 직무 원문(근로자 이름 → "근로자 A" 별칭), 업종, 작업 환경, 근로자 특성 메모(**허용+동의 시에만**, 별칭 적용) | 근로자 실명, 근로자 id, 접속 코드 |
| OpenAI (Chat Completions) | 미국 | AI 코칭(`/ai/coaching`) | 직무 제목·단계 문장(별칭), 단계별 수행 수치, 업종·환경·직무 분류, 메모(**근로자 지정 + 허용 + 동의 시에만**) | 실명, 근로자 id. **AI 처리 동의가 없거나 철회된 근로자의 기록이 섞이면 LLM을 아예 부르지 않는다**(규칙 기반 제안) |
| OpenAI (Embeddings, `OPENAI_EMBED_MODEL`) | 미국 | 그림(AAC) 검색 | 단계 문장·검색어(별칭 적용) | 메모, 실명 |
| Google Cloud Text-to-Speech | 미국 등 | 단계 음성 합성 | 단계 문장 **원문**(실명이 들어 있으면 그대로) | 근로자 정보 |

- 별칭 매핑은 `backend/privacy.py: Pseudonymizer`. 사업장 근로자 전원의 표시 이름을 등록 순서대로 "근로자 A, B, …"로 바꾸고 응답에서 되돌린다. 매핑은 요청 하나 안에서만 쓰고 저장하지 않는다.
- 한계: 등록된 표시 이름과 **글자가 똑같을 때만** 바꾼다. 성을 뺀 이름·별명은 못 잡는다. 기본 이름 "근로자" 같은 일반 명사는 바꾸지 않는다.
- ai_service는 스키마(`DecomposeContext`, `CoachingContext`)로 허용한 필드만 받고 나머지(예: `worker_name`)는 버린다. 분해 로그에는 원문 대신 길이만 남긴다.
- **남은 위험**: Google TTS는 사람이 듣는 문장이 그대로 필요해 별칭을 쓸 수 없다. 사업주에게 "단계 문장에 이름을 넣지 말 것"을 안내한다. TTS 위탁에 대한 동의 범위는 법무 검토가 필요하다.

## 4. 동의

| 종류(`consent_type`) | 의미 | 없으면 |
|---|---|---|
| `personal_info` | 서비스 제공을 위한 개인정보 수집·이용 | (기록만. 현재 기능 제한 없음 — 운영 정책으로 등록 전 수령) |
| `ai_processing` | AI 코칭을 위한 처리 위탁·국외 이전(OpenAI) | 그 근로자 기록은 LLM 코칭에서 제외, 메모 전송 안 함 |

- 주체: `self`(당사자) / `guardian`(보호자·법정대리인). 동의서 원본은 사업장이 보관하고 서버에는 수령 사실·방침 버전(`PRIVACY_POLICY_VERSION`)·기록한 사업주·일시만 남긴다.
- 철회는 행을 지우지 않고 `revoked_at`을 채운다(유효 기간의 근거). 근로자 삭제 시에는 동의 기록도 지운다.

## 5. 보존기간과 삭제

| 데이터 | 보존 | 삭제 방법 |
|---|---|---|
| 수행 로그 | `PERFORMANCE_LOG_RETENTION_DAYS` (기본 365일, `completed_at` 기준) | `manage.py purge` |
| 접근 감사 로그 | `ACCESS_AUDIT_RETENTION_DAYS` (기본 730일) — 「개인정보의 안전성 확보조치 기준」 제8조: 민감정보 처리 시 접속기록 2년 이상 | `manage.py purge` (앱 코드에 다른 삭제·수정 경로 없음) |
| TTS mp3 | 어느 단계도 참조하지 않으면 `TTS_ORPHAN_GRACE_HOURS`(기본 24시간) 뒤 | `manage.py purge` |
| 근로자 프로필·메모·배정·수행 로그·동의 | 사업주가 삭제할 때까지 | `DELETE /api/workers/{id}` — DB 행 삭제 + `secure_delete` + WAL 체크포인트 |
| 직무·단계·사진 | 사업주가 직무를 삭제할 때까지 | `DELETE /api/tasks/{id}` (사진 파일 정리는 Phase 0.3 고아 파일 GC) |
| 배정(`assignments`) | 근로자·직무 삭제 때까지 | 보존기간 자동 삭제 없음 — 후속 과제 |
| 백업 | 운영자가 정함 | 백업 사본에는 삭제가 반영되지 않는다 — 백업 보존기간을 별도로 정해야 한다 |

### 삭제 스케줄

서버 프로세스 안에 스케줄러를 두지 않는다(백엔드를 여러 개 띄우면 같은 삭제가 겹친다). 호스트 cron으로 하루 한 번:

```cron
15 3 * * * cd /srv/jobcard && docker compose --profile maintenance run --rm purge >> /var/log/jobcard-purge.log 2>&1
```

먼저 확인만 하려면 `docker compose --profile maintenance run --rm purge python manage.py purge --dry-run`.

## 6. 접근 감사

`access_audit_logs`에 남기는 행위(`action`):

| action | 언제 |
|---|---|
| `worker.list` | 근로자 목록 조회 |
| `worker.history` | 근로자별 배정 직무·활동일 조회 |
| `worker.update` | 근로자 이름·메모·AI 메모 허용 변경 |
| `worker.consents` / `worker.consent.grant` / `worker.consent.revoke` | 동의 조회·기록·철회 |
| `worker.export` | 데이터 내보내기 |
| `worker.delete` | 근로자 삭제 (이후에도 id만 남는다) |
| `dashboard.workers` / `dashboard.view` | 대시보드 근로자 목록·근로자별 수행 기록 |
| `coaching.view` | AI 코칭 조회 |

- 같은 사업주·행위·근로자·IP가 `ACCESS_AUDIT_DEDUPE_SECONDS`(기본 60초) 안에 반복되면 한 줄로 합친다(대시보드 3초 폴링).
- ORM으로 수정·삭제하면 예외가 난다(`models.py` 매퍼 이벤트). 지우는 코드는 `retention.py`뿐이다(테스트가 확인).

## 7. 정보주체 권리 대응

| 요구 | 방법 |
|---|---|
| 열람·사본 | 근로자 관리 화면 "내보내기" → `GET /api/workers/{id}/export` (JSON: 프로필, 동의, 배정, 수행 로그) |
| 정정 | 근로자 관리 화면에서 이름·메모 수정 (`PATCH /api/workers/{id}`) |
| 삭제 | 근로자 관리 화면 "삭제" (확인 후) |
| 처리 정지(AI) | "동의 철회 기록" → 이후 AI 코칭은 규칙 기반만 |
