#!/usr/bin/env sh
# Docker secrets 원본 파일을 (없을 때만) 만든다 — Phase 0.5, docs/security/secrets.md.
#
# 왜 필요한가: docker-compose.yml의 top-level `secrets:`는 원본 파일이 없으면 `docker compose up`이
# 기동을 거부한다. 빈 파일이면 앱은 예전 동작을 한다(secret_env.py: 빈 파일 → 환경변수/기본값,
# tts.py: 빈 자격증명 → ADC/브라우저 TTS 폴백, llm.py: 키 없음 → 규칙 기반 폴백).
#
# .env 옮기기: compose는 이제 OPENAI_API_KEY를 환경변수로 넘기지 않는다(파일로만). 그래서 .env에 OPENAI_API_KEY나
# JOBCARD_SECRET 값이 있고 대응하는 secrets/ 파일이 없거나 비어 있으면, 그 값을 그대로 파일로 옮긴다.
# - 값은 화면·로그에 절대 출력하지 않는다("옮김"과 파일 경로만 알린다).
# - JOBCARD_SECRET는 새로 만들지 않고 기존 값을 옮긴다. 새 값이면 근로자 접속 코드 해시·토큰·서명 URL이 모두
#   무효가 된다(자동 생성하지 않는 이유).
# - 이미 값이 있는 파일은 절대 덮어쓰지 않는다(운영 키를 실수로 지우거나 옛 값으로 되돌리지 않게).
# 옮긴 뒤 .env의 해당 줄 값은 사람이 지운다(이 스크립트는 .env를 고치지 않는다).
#
# 사용: sh scripts/init-secrets.sh            (저장소 루트의 secrets/, .env)
#       SECRETS_DIR=/srv/jobcard/secrets ENV_FILE=/srv/jobcard/.env sh scripts/init-secrets.sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DIR=${SECRETS_DIR:-"$ROOT/secrets"}
ENV_FILE=${ENV_FILE:-"$ROOT/.env"}

# 새로 만드는 파일은 소유자만 읽고 쓰게 한다(같은 서버의 다른 계정이 못 읽게).
umask 077
mkdir -p "$DIR"

# .env에서 KEY의 마지막 값을 꺼낸다(export 접두어·따옴표·CR 제거). 없으면 빈 문자열. 값은 출력하지 않고 반환만.
env_value() {
  [ -f "$ENV_FILE" ] || { printf ''; return 0; }
  grep -E "^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=" "$ENV_FILE" 2>/dev/null | tail -n 1 \
    | sed -E "s/^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=[[:space:]]*//; s/\r$//; s/[[:space:]]+$//" \
    | sed -E "s/^\"(.*)\"$/\1/; s/^'(.*)'$/\1/"
}

# 파일이 비었는지(공백·개행만 있어도 빈 것). 앱(secret_env.py, tts.py)과 같은 기준.
is_blank() {
  [ ! -s "$1" ] || ! grep -q '[^[:space:]]' "$1"
}

for name in openai_api_key.txt jobcard_secret.txt google-tts.json; do
  path="$DIR/$name"
  case "$name" in
    openai_api_key.txt) key=OPENAI_API_KEY ;;
    jobcard_secret.txt) key=JOBCARD_SECRET ;;
    *) key= ;;
  esac
  value=
  if [ -n "$key" ]; then
    value=$(env_value "$key")
  fi
  if [ -e "$path" ] && ! is_blank "$path"; then
    echo "있음(그대로 둠): $path"
  elif [ -n "$value" ]; then
    printf '%s' "$value" > "$path"
    chmod 600 "$path" 2>/dev/null || true
    echo "옮김: .env의 $key → $path (값은 표시하지 않음). 확인 후 .env의 $key 값을 지우세요."
  elif [ -e "$path" ]; then
    echo "있음(비어 있음, 그대로 둠): $path"
  else
    : > "$path"
    chmod 600 "$path" 2>/dev/null || true
    echo "빈 파일 생성: $path"
  fi
  value=
done

echo "완료. 값 넣는 법과 교체 절차: docs/security/secrets.md"
