# 비밀값 관리 (Phase 0.5)

잡카드가 쓰는 비밀값을 어디에 두고, 어떻게 컨테이너에 넘기고, 어떻게 교체하고, 새어 나가지 않게
어떻게 검사하는지 정리한다. 실제 값은 이 문서·`.env.example`·커밋 어디에도 적지 않는다.

## 1. 비밀값 목록과 전달 경로

| 비밀값 | 쓰는 서비스 | 원본 파일(호스트, git 제외) | 컨테이너 안 경로 | 앱이 읽는 변수 |
|---|---|---|---|---|
| OpenAI API 키 | ai_service | `secrets/openai_api_key.txt` | `/run/secrets/openai_api_key` | `OPENAI_API_KEY_FILE` |
| 토큰·접속 코드 해시·서명 URL 키 | backend, migrate, purge | `secrets/jobcard_secret.txt` | `/run/secrets/jobcard_secret` | `JOBCARD_SECRET_FILE` |
| Google 서비스 계정 JSON(선택) | backend | `secrets/google-tts.json` | `/run/secrets/google_tts_credentials` | `GOOGLE_APPLICATION_CREDENTIALS` |
| 웹 푸시 VAPID 개인 키 PEM(선택, 3-0) | backend | `secrets/vapid_private.pem` | `/run/secrets/vapid_private_key` | `VAPID_PRIVATE_KEY_FILE` (공개 키는 비밀이 아니라 `.env`의 `VAPID_PUBLIC_KEY`) |

- `docker-compose.yml`의 top-level `secrets:`가 원본 파일을 정의하고, 각 서비스에는 **필요한 것만** 연결한다
  (OpenAI 키는 backend에 없고, Google 자격증명은 ai_service에 없다).
- 예전에는 `./secrets` 디렉터리 전체를 backend에 바인드 마운트했다. 그러면 backend가 쓰지 않는 파일까지
  읽을 수 있고, 나중에 그 폴더에 넣는 비밀값도 자동으로 노출된다. 지금은 파일 단위로만 넘긴다.
- 왜 환경변수가 아닌가: 환경변수 값은 `docker inspect`, `/proc/<pid>/environ`, 오류 리포트·디버그 덤프,
  자식 프로세스에 그대로 보인다. Docker secret은 해당 컨테이너의 `/run/secrets/` 파일로만 보인다.

### 앱의 읽기 우선순위 (`backend/secret_env.py`, `ai_service/secret_env.py`)

1. `<이름>_FILE`이 가리키는 파일 내용(끝 개행 `\n`/`\r\n`과 UTF-8 BOM 제거) — 운영 경로
2. `<이름>` 환경변수 직접 값 — 로컬 개발·기존 설치본 하위호환. 1의 파일이 **비어 있을 때도** 여기로 온다
   (이때 "파일로 옮기라"는 경고를 한 번 남긴다. 값은 로그에 남기지 않는다).
3. 기본값(`JOBCARD_SECRET`은 개발용 키 — 운영에서는 기동 실패, `OPENAI_API_KEY`는 빈 값 → 규칙 기반 폴백)

compose는 `OPENAI_API_KEY`를 환경변수로 넘기지 않는다(파일로만). 2번(환경변수 직접 값)은 컨테이너 밖 로컬
실행(`uvicorn` 직접)과 아직 `JOBCARD_SECRET`를 파일로 옮기지 않은 기존 설치본을 위한 것이다.

비밀값은 **프로세스가 기동할 때 한 번** 읽는다(backend `auth._secret()`은 lifespan에서 읽어 캐시, ai_service
`llm.OPENAI_API_KEY`는 import 시). 요청마다 파일을 다시 열지 않으므로, 파일을 바꾼 뒤에는 컨테이너를 다시
띄워야 반영된다(3절). 테스트는 `auth.reset_secret_cache()`로 캐시를 비운다(conftest가 매 테스트 앞뒤로 부른다).

`<이름>_FILE`을 줬는데 파일이 **없으면** 예외로 멈춘다. 경로 오타·마운트 누락을 조용히 개발용 키로 덮으면
운영이 위조 가능한 키로 뜰 수 있기 때문이다.

Google 자격증명 파일이 비어 있으면(0바이트뿐 아니라 공백·개행·BOM만 있어도) `backend/tts.py`가 `GOOGLE_APPLICATION_CREDENTIALS`를 지우고
ADC(Application Default Credentials: Workload Identity·메타데이터 서버 등)로 넘어간다. 그것도 없으면
합성이 실패하고 근로자 화면은 브라우저 음성으로 대체된다(기존 동작).

## 2. 처음 설정

```bash
sh scripts/init-secrets.sh
# Windows: powershell -ExecutionPolicy Bypass -File scripts\init-secrets.ps1
```

네 원본 파일을 **없을 때만** 만든다(이미 값이 있는 파일은 건드리지 않는다, 권한은 소유자만).
`vapid_private.pem`은 3-0에서 더했다 — 그 전에 설치했으면 **다음 `docker compose up` 전에 한 번 다시 실행**한다
(없으면 compose가 기동을 거부한다).
compose는 원본 파일이 없으면 `up`을 거부하므로 이 단계가 필요하다. 빈 파일이면 앱은 예전 동작을 한다.
`.env`에 `OPENAI_API_KEY`·`JOBCARD_SECRET` 값이 있고 대응하는 파일이 없거나 비어 있으면(공백·개행만 포함),
빈 파일 대신 **그 값을 그대로 옮긴다**. 값은 화면에 출력하지 않고 "옮김"과 경로만 알린다. `.env` 위치는
`ENV_FILE`(PowerShell: `-EnvFile`)로 바꿀 수 있다.

값 넣기(끝 개행은 앱이 지우므로 `echo`/`print`로 써도 된다):

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))" > secrets/jobcard_secret.txt
printf '%s' 'sk-...' > secrets/openai_api_key.txt
cp ~/Downloads/<서비스계정키>.json secrets/google-tts.json   # 가능하면 4절의 키 없는 방식을 쓴다
chmod 600 secrets/*.txt secrets/google-tts.json
```

PowerShell 5에서 `>`/`Out-File`은 UTF-16으로 저장해 앱이 읽지 못한다. `Set-Content -NoNewline -Encoding ascii`를 쓴다.

### 웹 푸시 키(VAPID, 선택)

빈 `secrets/vapid_private.pem`이면 웹 푸시가 꺼진 채로 뜬다(설정·메뉴의 '도움 알림 받기'가 '켤 수 없어요'). 켜려면:

```bash
docker compose run --rm -v "$PWD/secrets:/out" backend python manage.py vapid-keys --out /out/vapid_private.pem
# 화면의 VAPID_PUBLIC_KEY=... 한 줄을 .env에 넣는다(공개 키라 비밀 아님). VAPID_SUBJECT=mailto:<운영 연락처>도 .env에.
docker compose up -d backend
```

빈 자리 파일은 `--force` 없이 덮어쓴다. 키가 든 파일을 바꾸면 사업주 기기의 알림 구독을 모두 다시 켜야 한다.

### 기존 설치본 옮기기(`.env`에 키를 두던 경우)

1. `sh scripts/init-secrets.sh`(Windows: `scripts\init-secrets.ps1`)를 실행한다. `.env`의 `JOBCARD_SECRET`·
   `OPENAI_API_KEY` 값을 **그대로** `secrets/jobcard_secret.txt`·`secrets/openai_api_key.txt`로 옮긴다
   (파일이 없거나 비어 있을 때만, 값은 출력하지 않음). 손으로 옮겨도 된다.
   - `JOBCARD_SECRET`는 **새로 만들지 않는다.** 새 값이면 기존 근로자 접속 코드 해시·토큰·서명 URL이 모두 어긋난다.
   - **`OPENAI_API_KEY`는 반드시 옮긴다.** compose가 더 이상 환경변수로 넘기지 않으므로, 옮기지 않으면
     ai_service가 키 없이(규칙 기반 폴백으로) 뜬다. 이 기회에 3절에 따라 교체를 권장한다.
2. `.env`에서 두 줄의 값을 지운다.
3. `docker compose up -d --force-recreate` 후 `docker inspect jobcard-api jobcard-ai`의 `Env`에 키 값이 없는지 확인한다.

compose에는 하위호환을 위해 `JOBCARD_SECRET: "${JOBCARD_SECRET:-}"` 줄이 남아 있다(파일이 비어 있을 때만 쓰인다).
키를 `.env`에만 둔 설치본이 업그레이드하자마자 개발용 기본 키로 바뀌어 접속 코드가 전부 어긋나는 일을 막는다.
모든 설치본이 옮긴 뒤 다음 정리 때 없앤다. `OPENAI_API_KEY` 줄은 없앴다(키가 바뀌어도 데이터가 깨지지 않고
규칙 기반으로 폴백할 뿐이라, `.env` 값이 `docker inspect`에 보이는 위험을 남겨 둘 이유가 없다).

### 한계

- `docker compose`(Swarm이 아님)의 secret은 원본 파일의 읽기 전용 바인드 마운트다. `uid`/`gid`/`mode` 옵션은
  무시되고 호스트 파일 권한이 그대로 보인다. Phase 1.7에서 컨테이너를 비루트(`USER 10001`)로 바꿀 때는
  원본 파일을 그 UID가 읽을 수 있게(예: `chown 10001` 또는 그룹 권한) 해야 한다.
- 서버 디스크의 원본 파일 자체는 평문이다. 더 높은 수준이 필요하면 SOPS/age로 암호화해 두고 배포 시
  복호화하거나, 클라우드 비밀 관리자(GCP Secret Manager 등)에서 기동 시 받아 오는 방식으로 옮긴다.

## 3. 키 교체(로테이션) 절차

공통 원칙: **새 키 발급 → 배포·동작 확인 → 옛 키 폐기** 순서. 유출이 의심되면 옛 키를 먼저 폐기한다.

### OpenAI API 키

1. OpenAI 대시보드(API keys)에서 프로젝트 단위 키를 새로 만든다. 가능하면 프로젝트별 사용 한도·권한을 건다.
2. `secrets/openai_api_key.txt`를 새 값으로 바꾸고 `docker compose up -d --force-recreate ai_service`
   (키는 기동 시 한 번 읽는다).
3. `/health`와 직무 생성 1건으로 LLM 경로가 동작하는지 확인한다(로그에 폴백 경고가 없어야 한다).
4. 옛 키를 대시보드에서 삭제하고, 사용량(Usage) 화면에서 교체 전 이상 사용이 없었는지 본다.

### JOBCARD_SECRET

교체하면 ① 발급된 모든 로그인 토큰 ② 근로자 접속 코드 해시(HMAC) ③ 사진·TTS 서명 URL이 **모두 무효**가 된다.

1. 공지 후 점검 시간에 새 값을 만든다:
   `python -c "import secrets; print(secrets.token_urlsafe(48))" > secrets/jobcard_secret.txt`
2. `docker compose up -d --force-recreate backend` (migrate·purge도 같은 파일을 읽는다). backend는 키를
   기동 시 한 번 읽어 캐시하므로, 파일만 바꾸고 다시 띄우지 않으면 옛 키를 계속 쓴다.
3. 사업주가 다시 로그인한 뒤, 근로자 관리 화면에서 근로자 접속 코드를 **전부 재발급**해 전달한다.
4. 유출이 원인이었다면 접근 감사 로그에서 교체 전 이상 접근을 확인한다.

### Google 서비스 계정 키(JSON을 쓰는 경우)

```bash
SA=jobcard-tts@<프로젝트>.iam.gserviceaccount.com
gcloud iam service-accounts keys create new-key.json --iam-account="$SA"
mv new-key.json secrets/google-tts.json && chmod 600 secrets/google-tts.json
docker compose up -d --force-recreate backend      # TTS 합성 1건으로 확인
gcloud iam service-accounts keys list --iam-account="$SA"
gcloud iam service-accounts keys disable <옛 KEY_ID> --iam-account="$SA"   # 며칠 지켜본 뒤
gcloud iam service-accounts keys delete  <옛 KEY_ID> --iam-account="$SA"
```

키 수명을 90일 이하로 운영하고, 서비스 계정에는 Text-to-Speech 호출에 필요한 최소 권한만 준다.

## 4. Google TTS를 서비스 계정 키 없이 쓰기(권장)

서비스 계정 JSON 키는 만료가 없는 장기 자격증명이라 한 번 새면 폐기할 때까지 계속 쓸 수 있다. 아래 방식은
단기 토큰만 쓰므로 원본 파일에 개인 키가 없다. 어느 방식이든 `secrets/google-tts.json`은 **빈 파일**로 두거나
(ADC가 실행 환경에서 자격증명을 찾음) 개인 키가 없는 자격증명 구성 파일만 둔다. 코드 변경은 필요 없다
(`tts.py`는 `texttospeech.TextToSpeechClient()`로 ADC를 그대로 쓴다).

| 실행 환경 | 방법 | `secrets/google-tts.json` |
|---|---|---|
| GKE | Workload Identity Federation for GKE: Kubernetes 서비스 계정을 GCP 서비스 계정에 바인딩(`roles/iam.workloadIdentityUser`) | 빈 파일(마운트 불필요) |
| Compute Engine VM | VM에 서비스 계정을 연결하면 메타데이터 서버가 단기 토큰을 발급. 컨테이너에서 `169.254.169.254` 접근 허용 | 빈 파일 |
| AWS·Azure·온프레미스(OIDC) | Workload Identity Federation: 워크로드 ID 풀·공급자를 만들고 `gcloud iam workload-identity-pools create-cred-config ... --output-file=google-tts.json`으로 **자격증명 구성 파일**(type `external_account`, 개인 키 없음)을 만든다. 외부 ID 토큰 파일 경로도 컨테이너에 넘겨야 한다 | 구성 파일 |
| 개발자 PC | `gcloud auth application-default login --impersonate-service-account=$SA` — 사용자 자격증명으로 서비스 계정을 가장해 1시간짜리 토큰을 쓴다(사용자에게 `roles/iam.serviceAccountTokenCreator` 필요) | 쓰지 않음(로컬 실행) |

조직 정책 `iam.disableServiceAccountKeyCreation`을 켜서 새 서비스 계정 키 발급 자체를 막는 것을 권한다.

## 5. 비밀값 스캔 (gitleaks)

- 설정: 저장소 루트 `.gitleaks.toml` — 기본 규칙 전체 + 최소 예외 두 가지.
  1. 개발용 자리표시자 `_DEV_SECRET`(값 하나).
  2. `secrets/google-tts.json.example`(경로 하나): 사용자가 복사해 쓰는 서비스 계정 JSON 틀이라 개인 키 형식을 담는다.
     경로째 빼면 누가 여기에 진짜 키를 붙여 넣어도 gitleaks가 못 잡으므로, `backend/tests/test_secret_placeholders.py`가
     "private_key 본문이 100자 미만(자리표시자)"과 "예외 경로가 이 파일 하나뿐"을 단언해 대신 막는다
     (진짜 RSA 2048 키 본문은 약 1,600자 — 들어가면 CI 테스트가 실패한다).
  예외를 늘릴 때는 왜 진짜 비밀값이 아닌지 주석으로 남긴다. 디렉터리째 빼는 예외는 쓰지 않는다.
- CI: `.github/workflows/ci.yml`의 `secret-scan` 잡이 히스토리 전체(`fetch-depth: 0`)를 `--redact`로 스캔한다.
  gitleaks 바이너리는 버전과 SHA-256을, checkout 액션은 커밋 SHA를 고정한다.
- 커밋 전: `.pre-commit-config.yaml`의 gitleaks 훅(같은 버전, 커밋 SHA 고정).
  설치: `pip install pre-commit && pre-commit install`.
- 로컬 수동 스캔:

  ```bash
  gitleaks git . --config .gitleaks.toml --redact --verbose     # 히스토리 전체
  gitleaks dir . --config .gitleaks.toml --redact               # 작업 트리(커밋 안 된 파일 포함)
  # 바이너리 없이 Docker로(버전 고정, 값은 --redact로 가림). Git Bash에서는 MSYS_NO_PATHCONV=1을 앞에 붙인다.
  docker run --rm -v "$PWD:/repo:ro" --entrypoint sh zricethezav/gitleaks:v8.30.1 -c \
    'git config --global --add safe.directory /repo && gitleaks git /repo --config /repo/.gitleaks.toml --redact'
  ```

- **stash는 `gitleaks git`으로 다 보이지 않는다.** 기본 log 옵션이 `git log -p --all`이라 `refs/stash`도 대상에
  들어가지만, stash의 작업 트리 커밋(W)은 병합 커밋이라 `git log -p`가 diff를 내지 않는다 — 작업 트리에서 고친
  내용(대개 비밀값이 들어가는 곳)은 스캔되지 않는다(8절 실측). CI는 브랜치·태그만 받아 와 stash를 아예 보지 않는다.
  stash는 따로 본다:

  ```bash
  for i in $(git stash list --format=%gd); do
    git diff "$i^1" "$i" | gitleaks stdin --config .gitleaks.toml --redact      # 작업 트리 변경
    git diff "$i^1" "$i^2" | gitleaks stdin --config .gitleaks.toml --redact    # 인덱스 변경
  done
  ```

### 찾았을 때

1. **먼저 해당 키를 교체·폐기한다**(3절). 히스토리를 고쳐도 이미 복제·포크·CI 캐시에 남은 사본은 회수되지 않는다.
2. 오탐이면 해당 줄 끝에 `# gitleaks:allow`를 달거나, 과거 커밋에 있어 줄을 고칠 수 없으면 리포트의
   `Fingerprint`(`커밋:파일:규칙:줄`)를 저장소 루트 `.gitleaksignore`에 한 줄씩 넣는다(이유는 커밋 메시지에).
3. 필요하면 `git filter-repo`로 히스토리에서 지우고 강제 푸시한다(협업자 전원 재복제 필요).
   GitHub에 남은 캐시는 GitHub 지원에 삭제를 요청한다.

## 6. GitHub secret scanning·push protection 켜기(저장소 관리자 작업)

push protection은 알려진 형식의 키(OpenAI, Google 서비스 계정 등)가 들어간 푸시를 서버에서 거부한다.
gitleaks와 겹치지만, 로컬 훅을 설치하지 않은 사람의 푸시도 막는다.

- 웹: 저장소 **Settings → Advanced Security(또는 Code security)** → **Secret Protection** 활성화 →
  **Push protection** 활성화. 공개 저장소는 무료, 비공개 저장소는 GitHub Secret Protection 라이선스가 필요하다.
- 조직 단위로 켜려면 조직 Settings → Advanced Security → Configurations에서 보안 구성을 만들어 저장소에 적용한다.
- CLI(관리자 권한 토큰):

  ```bash
  gh api -X PATCH repos/<owner>/<repo> \
    -f 'security_and_analysis[secret_scanning][status]=enabled' \
    -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'
  ```

- 알림은 **Security → Secret scanning**에서 본다. 푸시 차단을 우회(bypass)한 기록도 여기 남으므로 정기적으로 확인한다.

## 7. 개발 PC 위험: 저장소가 OneDrive 동기화 폴더 안에 있다

현재 작업 사본이 `C:\Users\<사용자>\OneDrive\Desktop\...` 아래에 있다. `.gitignore`는 git만 막을 뿐이라
`.env`와 `secrets/`의 실제 키가 **Microsoft 클라우드로 동기화**되고 있다.

위험:
- 같은 Microsoft 계정에 로그인한 모든 기기, 그리고 계정이 탈취되면 공격자에게 키가 그대로 노출된다.
- OneDrive **버전 기록**과 휴지통에 옛 값이 남는다. 파일을 지우거나 값을 바꿔도 이전 버전에서 복원할 수 있다.
- 폴더 공유 링크를 만들면 `.env`·`secrets/`도 함께 공유된다. 회사·학교 계정이면 관리자 eDiscovery·보존 정책 대상이 된다.

대응(순서대로):
1. 저장소를 동기화되지 않는 경로로 옮긴다(예: `C:\dev\FireWall`). OneDrive는 특정 하위 폴더만 제외하는
   기능이 제한적이므로 이동이 가장 확실하다. 옮긴 뒤 OneDrive 쪽 사본을 지운다.
2. **동기화된 적이 있는 키는 유출된 것으로 보고 모두 교체한다**: OpenAI API 키, `JOBCARD_SECRET`
   (개발 데이터라면 접속 코드 재발급만 하면 된다), Google 서비스 계정 키(가능하면 4절 방식으로 전환하고 키 삭제).
3. OneDrive 웹에서 해당 파일의 버전 기록과 휴지통(2단계 휴지통 포함)을 비운다.
4. OpenAI Usage, GCP 결제·감사 로그에서 교체 전 이상 사용이 없었는지 확인한다.
5. 앞으로 비밀값은 동기화 폴더 밖(또는 OS 자격증명 저장소·비밀번호 관리자)에 두고, 필요할 때 `secrets/`로 복사한다.

## 8. 점검 상태

### Phase 0.5 커밋 시점

gitleaks를 실행하지 못해 `git grep`(모든 ref, 대표 패턴)으로 대신 훑었다. 그때 사람 확인이 필요하다고 남긴 두 건은
아래 0.5 보완 실측으로 정리됐다.

### Phase 0.5 보완(2026-11-07, gitleaks v8.30.1 Docker 이미지로 로컬 실행, 값은 `--redact`로 가림)

- `gitleaks git`(기본 = `--all`, refs/stash·도구 체크포인트 ref 포함) 히스토리 전체: **104개 커밋, 발견 0건**.
  브랜치·원격·태그만(`--log-opts="--full-history --branches --remotes --tags"`, CI와 같은 범위): **102개 커밋, 발견 0건**(기본 스캔이 2개 더 많은 것은 브랜치 밖 ref — refs/stash의 인덱스·미추적 커밋, 도구 체크포인트 ref — 때문).
- `secrets/google-tts.json.example`: 개인 키 규칙에 **걸리지 않는다**(private_key 본문 10자 자리표시자라 규칙의
  최소 길이에 못 미친다). 그래도 예시 파일 형식이 바뀌면 걸릴 수 있어 5절의 경로 예외 + 자리표시자 테스트로 고정했다.
- stash: 이 저장소에는 `stash@{0}`(90e77ab, "refactor/mina WIP") 하나가 있다. `--all` 스캔은 refs/stash를
  대상에 넣지만 작업 트리 커밋의 diff를 보지 않아 **발견 0건으로 나온다**. 5절의 stash 전용 스캔
  (`git diff stash^1 stash | gitleaks stdin`)으로 보면 **`openai-api-key` 규칙 1건**(`.env.example`)이 나온다.
  Phase 0.5 커밋 때 git grep으로 찾은 것과 같은 항목이다. 어느 브랜치에도 없고 푸시되지 않지만 저장소가
  OneDrive에 있으므로 7절에 따라 유출로 보고 **그 키를 교체한 뒤 stash를 지운다**(`git stash drop`, 저장소 주인이 판단).
  인덱스·미추적 파일 쪽 stash 커밋은 발견 0건.
- 오탐 allowlist 추가: 없음(위 예시 파일 경로 예외 외).
