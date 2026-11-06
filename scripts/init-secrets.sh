#!/usr/bin/env sh
# Docker secrets 원본 파일을 (없을 때만) 빈 파일로 만든다 — Phase 0.5, docs/security/secrets.md.
#
# 왜 필요한가: docker-compose.yml의 top-level `secrets:`는 원본 파일이 없으면 `docker compose up`이
# 기동을 거부한다. 빈 파일이면 앱은 예전 동작을 한다(secret_env.py: 빈 파일 → 환경변수/기본값,
# tts.py: 빈 자격증명 → ADC/브라우저 TTS 폴백, llm.py: 키 없음 → 규칙 기반 폴백).
#
# 이미 있는 파일은 절대 덮어쓰지 않는다(운영 키를 실수로 지우지 않게). 값을 넣는 일은 사람이 한다:
#   python -c "import secrets; print(secrets.token_urlsafe(48))" > secrets/jobcard_secret.txt
# JOBCARD_SECRET를 새로 만들면 기존 근로자 접속 코드가 모두 맞지 않게 된다 — 이미 .env에 쓰던 값이 있으면
# 그 값을 그대로 옮긴다(자동 생성하지 않는 이유).
#
# 사용: sh scripts/init-secrets.sh            (저장소 루트의 secrets/)
#       SECRETS_DIR=/srv/jobcard/secrets sh scripts/init-secrets.sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DIR=${SECRETS_DIR:-"$ROOT/secrets"}

# 새로 만드는 파일은 소유자만 읽고 쓰게 한다(같은 서버의 다른 계정이 못 읽게).
umask 077
mkdir -p "$DIR"

for name in openai_api_key.txt jobcard_secret.txt google-tts.json; do
  path="$DIR/$name"
  if [ -e "$path" ]; then
    echo "있음(그대로 둠): $path"
  else
    : > "$path"
    chmod 600 "$path" 2>/dev/null || true
    echo "빈 파일 생성: $path"
  fi
done

echo "완료. 값 넣는 법과 교체 절차: docs/security/secrets.md"
