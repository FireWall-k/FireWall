# Docker secrets 원본 파일을 (없을 때만) 빈 파일로 만든다 — Windows용. scripts/init-secrets.sh와 같은 동작.
#
# 왜 필요한가: docker-compose.yml의 top-level `secrets:`는 원본 파일이 없으면 `docker compose up`이
# 기동을 거부한다. 빈 파일이면 앱은 예전 동작(환경변수/기본값, ADC·규칙 기반 폴백)을 한다.
# 이미 있는 파일은 절대 덮어쓰지 않는다(운영 키를 실수로 지우지 않게).
#
# 값을 넣을 때 주의: PowerShell 5의 `Out-File`/`>`는 UTF-16으로 저장한다. 아래처럼 쓴다.
#   python -c "import secrets; print(secrets.token_urlsafe(48))" | Set-Content -NoNewline -Encoding ascii secrets\jobcard_secret.txt
# (앱이 끝 개행과 UTF-8 BOM은 지워 주지만 UTF-16은 읽지 못한다.)
#
# 사용: powershell -ExecutionPolicy Bypass -File scripts\init-secrets.ps1 [-SecretsDir <경로>]
param(
    [string]$SecretsDir = (Join-Path (Split-Path -Parent $PSScriptRoot) 'secrets')
)
$ErrorActionPreference = 'Stop'

New-Item -ItemType Directory -Force -Path $SecretsDir | Out-Null

foreach ($name in @('openai_api_key.txt', 'jobcard_secret.txt', 'google-tts.json')) {
    $path = Join-Path $SecretsDir $name
    if (Test-Path -LiteralPath $path) {
        Write-Host "있음(그대로 둠): $path"
    } else {
        # 0바이트 파일(BOM도 넣지 않는다).
        [System.IO.File]::WriteAllBytes($path, [byte[]]@())
        # 상속 권한을 끊고 현재 사용자만 접근하게 한다(공유 PC의 다른 계정이 못 읽게).
        & icacls $path /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
        Write-Host "빈 파일 생성: $path"
    }
}

Write-Host "완료. 값 넣는 법과 교체 절차: docs/security/secrets.md"
