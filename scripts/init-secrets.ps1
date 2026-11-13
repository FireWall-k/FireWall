# Docker secrets 원본 파일을 (없을 때만) 만든다 — Windows용. scripts/init-secrets.sh와 같은 동작.
#
# 왜 필요한가: docker-compose.yml의 top-level `secrets:`는 원본 파일이 없으면 `docker compose up`이
# 기동을 거부한다. 빈 파일이면 앱은 예전 동작(환경변수/기본값, ADC·규칙 기반 폴백)을 한다.
# 이미 값이 있는 파일은 절대 덮어쓰지 않는다(운영 키를 실수로 지우지 않게).
#
# .env 옮기기: compose는 이제 OPENAI_API_KEY를 환경변수로 넘기지 않는다(파일로만). .env에 OPENAI_API_KEY나
# JOBCARD_SECRET 값이 있고 대응하는 secrets\ 파일이 없거나 비어 있으면 그 값을 그대로 파일로 옮긴다.
# 값은 화면에 출력하지 않는다. JOBCARD_SECRET는 새로 만들지 않고 옮긴다(바꾸면 접속 코드·토큰·서명 URL 무효).
# 옮긴 뒤 .env의 해당 줄 값은 사람이 지운다.
#
# 값을 직접 넣을 때 주의: PowerShell 5의 `Out-File`/`>`는 UTF-16으로 저장한다. 아래처럼 쓴다.
#   python -c "import secrets; print(secrets.token_urlsafe(48))" | Set-Content -NoNewline -Encoding ascii secrets\jobcard_secret.txt
# (앱이 끝 개행과 UTF-8 BOM은 지워 주지만 UTF-16은 읽지 못한다.)
#
# 사용: powershell -ExecutionPolicy Bypass -File scripts\init-secrets.ps1 [-SecretsDir <경로>] [-EnvFile <경로>]
param(
    [string]$SecretsDir = (Join-Path (Split-Path -Parent $PSScriptRoot) 'secrets'),
    [string]$EnvFile = (Join-Path (Split-Path -Parent $PSScriptRoot) '.env')
)
$ErrorActionPreference = 'Stop'

New-Item -ItemType Directory -Force -Path $SecretsDir | Out-Null

# .env에서 키의 마지막 값(export 접두어·따옴표 제거). 없으면 빈 문자열. 값은 출력하지 않는다.
function Get-EnvValue([string]$Key) {
    if (-not (Test-Path -LiteralPath $EnvFile)) { return '' }
    $value = ''
    foreach ($line in [System.IO.File]::ReadAllLines($EnvFile)) {
        if ($line -match "^\s*(export\s+)?$Key\s*=\s*(.*?)\s*$") {
            $value = $Matches[2]
            # compose의 dotenv와 같은 규칙: 따옴표 값은 따옴표 안만(안의 #은 값), 따옴표 없는 값은 ' #' 뒤를
            # 주석으로 버린다. 다르게 읽으면 파일 값(우선)이 backend가 쓰던 키와 달라진다(init-secrets.sh 참고).
            if ($value -match '^"(.*?)"\s*(#.*)?$' -or $value -match "^'(.*?)'\s*(#.*)?$") { $value = $Matches[1] }
            else { $value = ($value -replace '\s+#.*$', '') }
        }
    }
    return $value
}

# 공백·개행만 있는 파일도 빈 것으로 본다(앱의 secret_env.py, tts.py와 같은 기준).
function Test-Blank([string]$Path) {
    return ([System.IO.File]::ReadAllText($Path)).Trim().Length -eq 0
}

function Protect-File([string]$Path) {
    # 상속 권한을 끊고 현재 사용자만 접근하게 한다(공유 PC의 다른 계정이 못 읽게).
    & icacls $Path /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
}

$keys = @{ 'openai_api_key.txt' = 'OPENAI_API_KEY'; 'jobcard_secret.txt' = 'JOBCARD_SECRET' }
# vapid_private.pem(3-0): 웹 푸시 개인 키 자리. .env에서 옮기지 않는다(키는 manage.py vapid-keys로 만든다).
foreach ($name in @('openai_api_key.txt', 'jobcard_secret.txt', 'google-tts.json', 'vapid_private.pem')) {
    $path = Join-Path $SecretsDir $name
    $key = $keys[$name]
    $value = if ($key) { Get-EnvValue $key } else { '' }
    $exists = Test-Path -LiteralPath $path
    if ($exists -and -not (Test-Blank $path)) {
        Write-Host "있음(그대로 둠): $path"
    } elseif ($value) {
        # BOM 없는 UTF-8, 끝 개행 없이 쓴다.
        [System.IO.File]::WriteAllText($path, $value, (New-Object System.Text.UTF8Encoding($false)))
        Protect-File $path
        Write-Host "옮김: .env의 $key -> $path (값은 표시하지 않음). 확인 후 .env의 $key 값을 지우세요."
    } elseif ($exists) {
        Write-Host "있음(비어 있음, 그대로 둠): $path"
    } else {
        # 0바이트 파일(BOM도 넣지 않는다).
        [System.IO.File]::WriteAllBytes($path, [byte[]]@())
        Protect-File $path
        Write-Host "빈 파일 생성: $path"
    }
    $value = $null
}

Write-Host "완료. 값 넣는 법과 교체 절차: docs/security/secrets.md"
