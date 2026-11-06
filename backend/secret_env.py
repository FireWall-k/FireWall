"""비밀값 로더 — <이름>_FILE(Docker secrets) 우선, 환경변수 직접 값은 개발용 하위호환 (Phase 0.5).

왜 파일인가: 환경변수로 넘긴 키는 `docker inspect`, /proc/<pid>/environ, 오류 리포트·디버그 덤프,
자식 프로세스에 그대로 보인다. compose `secrets:`는 /run/secrets/<이름> 파일로만 넘기므로 그 경로를
아는 컨테이너 안에서만 읽힌다. 앱은 <이름>_FILE에 그 경로를 받는다(공식 이미지들의 관례와 같다).

우선순위(위가 이긴다)와 이유:
1. <이름>_FILE이 가리키는 파일의 내용 — 운영 경로. 둘 다 있을 때 파일이 이겨야 .env에 남은 옛 값이
   새로 교체한 키를 덮어쓰지 않는다.
2. <이름> 환경변수 직접 값 — 로컬 개발(uvicorn 직접 실행)·기존 설치본 하위호환. 1의 파일이 비어 있을
   때도 여기로 온다: scripts/init-secrets가 compose가 깨지지 않게 빈 파일을 만들어 두기 때문이다.
3. default — 예전과 같은 기본값.

<이름>_FILE을 줬는데 파일이 없으면 예외로 멈춘다(fail-closed). 경로 오타·마운트 누락을 조용히
개발용 기본 키로 덮으면 운영에서 위조 가능한 키로 뜰 수 있다.

backend/secret_env.py와 ai_service/secret_env.py는 같은 내용이다. 두 서비스의 Docker 빌드 컨텍스트가
따로라(./backend, ./ai_service) 공용 패키지로 묶지 못해 복사본을 둔다 — 한쪽을 고치면 다른 쪽도 고친다.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("jobcard.secrets")

# 같은 경고를 요청마다 남기지 않게 이름별로 한 번만(auth._secret()은 토큰 검증마다 불린다).
_warned: set[str] = set()


def read_secret(name: str, default: str = "") -> str:
    """비밀값 <name>을 읽는다. 값 자체는 절대 로그에 남기지 않는다."""
    file_var = f"{name}_FILE"
    path = (os.getenv(file_var) or "").strip()
    if path:
        try:
            # utf-8-sig: Windows 메모장·PowerShell 5가 붙이는 BOM을 떼어 낸다(키 앞에 보이지 않는 문자가 붙지 않게).
            with open(path, encoding="utf-8-sig") as fh:
                value = fh.read()
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"{file_var}={path} 파일이 없습니다. scripts/init-secrets.sh(또는 .ps1)로 만들거나 "
                f"{file_var} 설정을 지우세요."
            ) from exc
        # 끝 개행만 지운다: `echo 키 > 파일`이 붙이는 \n(Windows는 \r\n)이 HMAC 키·Bearer 헤더에 섞이면
        # 조용히 다른 키가 된다. 앞뒤 다른 공백은 값의 일부일 수 있어 건드리지 않는다.
        value = value.rstrip("\r\n")
        if value.strip():
            return value
        # 빈 파일 = 아직 비밀값 파일로 옮기지 않음. 아래 환경변수/기본값으로 넘어간다.
        if os.getenv(name) and name not in _warned:
            _warned.add(name)
            logger.warning(
                "%s 파일이 비어 있어 환경변수 %s 값을 씁니다. 값을 %s 파일로 옮기고 .env에서 지우세요"
                "(docs/security/secrets.md).",
                file_var, name, file_var,
            )
    direct = os.getenv(name)
    if direct:
        return direct
    return default
