"""Google Cloud Text-to-Speech 연동 모듈.

잡카드의 TTS는 Google Cloud Text-to-Speech를 기본 provider로 사용한다.
서비스 계정 JSON이 없거나 API 호출에 실패하면 전체 직무 생성이 중단되지 않도록
None을 반환하고, 프론트엔드는 브라우저 SpeechSynthesis를 fallback으로 사용한다.

운영 의도:
- 인증: GOOGLE_APPLICATION_CREDENTIALS(compose는 Docker secret /run/secrets/google_tts_credentials) 또는
  ADC(Workload Identity 등 — docs/security/secrets.md). 자격증명 파일이 비어 있으면 ADC로 넘어간다.
- 음성 캐시: 같은 문장/음성 옵션은 mp3를 재생성하지 않고 캐시 재사용
- (Phase 0.3) 캐시는 사업장(scope)별로 나눈다. 단계 문장에는 근로자 이름이 들어갈 수 있다. 예전처럼 문장 해시만으로
  전역 공유하면 ① 공개 URL(/api/tts/<hash>.mp3)을 아는 누구나 음성을 받을 수 있었고 ② 다른 사업장이 같은 문장을
  만들어 보면 즉시 캐시가 맞는지(= 그 문장을 누가 이미 썼는지)를 알 수 있었다. 사업장마다 따로 합성하면 비용이
  조금 늘지만 테넌트 사이에 아무것도 공유하지 않는다. 이 모듈은 파일만 만들고, 소유 레코드와 서명 URL은
  media.py/main.py가 맡는다.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger("jobcard.tts")

# 합성이 실패하면(결제 미설정 403, 인증 파일 없음, 네트워크 장애) 이 시간 동안은 시도하지 않는다.
# 실패가 설정 문제면 매 단계 호출이 똑같이 실패하면서 단계마다 0.4~1초씩 직무 생성을 늦춘다.
_FAILURE_COOLDOWN_SEC = float(os.getenv("TTS_FAILURE_COOLDOWN", "300"))
_state_lock = threading.Lock()
_cooldown_until = 0.0
_client_cache: tuple[object, object] | None = None  # (texttospeech 모듈, 클라이언트)


def _reset_state() -> None:
    """테스트용: 쿨다운과 클라이언트 캐시를 비운다."""
    global _cooldown_until, _client_cache
    with _state_lock:
        _cooldown_until = 0.0
        _client_cache = None


def _get_client(texttospeech):
    """클라이언트를 재사용한다. 호출마다 만들면 인증 파일을 읽고 연결을 새로 맺는다."""
    global _client_cache
    with _state_lock:
        if _client_cache is None or _client_cache[0] is not texttospeech:
            _drop_empty_credentials_path()
            _client_cache = (texttospeech, texttospeech.TextToSpeechClient())
        return _client_cache[1]


def _drop_empty_credentials_path() -> None:
    """GOOGLE_APPLICATION_CREDENTIALS가 빈 파일을 가리키면 변수를 지워 ADC로 넘어가게 한다(Phase 0.5).

    compose는 Docker secret(/run/secrets/google_tts_credentials)을 항상 이 변수로 넘기고, 키 파일이 없는
    설치에서는 scripts/init-secrets가 빈 자리표시자 파일을 만든다. 빈 파일을 그대로 두면 google-auth가 JSON
    파싱 오류로 멈춰 Workload Identity·메타데이터 서버 같은 ADC(서비스 계정 키 없는 인증)를 쓸 수 없다.
    """
    path = _env("GOOGLE_APPLICATION_CREDENTIALS")
    try:
        empty = bool(path) and os.path.getsize(path) == 0
    except OSError:
        return  # 파일이 없으면 google-auth가 경로를 담은 분명한 오류를 낸다(쿨다운 경고로 남는다).
    if empty:
        os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
        logger.info("Google TTS credentials file is empty; using Application Default Credentials.")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def get_tts_cache_dir() -> Path:
    cache_dir = Path(_env("TTS_CACHE_DIR", "./data/tts"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _google_voice_key(text: str, scope: str) -> str:
    voice_key = "|".join([
        "google",
        # 사업장 id. 캐시 키에 넣어 사업장끼리 같은 파일을 쓰지 않게 한다(모듈 docstring 참고).
        scope,
        _env("GOOGLE_TTS_LANGUAGE", "ko-KR"),
        _env("GOOGLE_TTS_VOICE", "ko-KR-Standard-A"),
        _env("GOOGLE_TTS_SPEAKING_RATE", "0.9"),
        _env("GOOGLE_TTS_PITCH", "0"),
        text,
    ])
    return hashlib.sha256(voice_key.encode("utf-8")).hexdigest()[:32]


def synthesize_tts(text: str, scope: str) -> str | None:
    """Google Cloud TTS로 문장을 mp3로 합성하고 캐시 디렉터리 안의 파일명(상대 키)을 반환한다.

    scope는 사업장 id다(비우면 ValueError — 사업장 구분 없는 공유 캐시로 되돌아가지 않게 막는다).
    실패 시 None을 반환한다. 프론트엔드에서는 음성 URL이 없으면 브라우저 TTS fallback을 사용한다.
    이렇게 해야 Google 인증 파일이 없는 개발 환경에서도 직무 생성 흐름이 깨지지 않는다.
    """
    if not scope:
        raise ValueError("TTS 캐시는 사업장(scope)별로 나눠야 합니다.")
    text = text.strip()
    if not text:
        return None

    filename = f"{_google_voice_key(text, scope)}.mp3"
    out_path = get_tts_cache_dir() / filename
    if out_path.exists() and out_path.stat().st_size > 0:
        # 캐시를 다시 쓸 때 수정 시각을 지금으로 당긴다. gc(media.gc, purge가 부른다)는 "어느 레코드도
        # 가리키지 않고 유예시간보다 오래된" 파일을 지우는데, 하루 넘게 안 쓰이던 파일을 새 단계가 막 다시
        # 쓰는 순간 지우면 커밋된 단계가 없는 mp3를 가리키게 된다. 갱신된 시각이 유예시간 동안 지켜 준다.
        try:
            os.utime(out_path)
        except OSError:
            pass  # 읽기 전용 볼륨 등. 시각을 못 바꿔도 gc가 지우기 직전에 참조를 다시 확인한다.
        return filename

    global _cooldown_until
    if time.monotonic() < _cooldown_until:
        return None
    try:
        _synthesize_google(text, out_path)
    except Exception as exc:  # noqa: BLE001 - TTS 장애가 전체 MVP 흐름을 막지 않도록 fallback
        with _state_lock:
            _cooldown_until = time.monotonic() + _FAILURE_COOLDOWN_SEC
        logger.warning(
            "Google TTS synthesis failed; skipping TTS for %.0fs (browser TTS fallback). error=%s",
            _FAILURE_COOLDOWN_SEC, str(exc).splitlines()[0][:300],
        )
        return None

    if out_path.exists() and out_path.stat().st_size > 0:
        return filename
    return None


def _synthesize_google(text: str, out_path: Path) -> None:
    """Google Cloud Text-to-Speech 합성.

    인증은 GOOGLE_APPLICATION_CREDENTIALS 환경변수 또는 Google ADC 방식을 따른다.
    Docker에서는 Docker secret(/run/secrets/google_tts_credentials)을 사용한다.
    """
    try:
        from google.cloud import texttospeech  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "google-cloud-texttospeech 패키지가 필요합니다. backend/requirements.txt를 설치하세요."
        ) from exc

    language_code = _env("GOOGLE_TTS_LANGUAGE", "ko-KR")
    voice_name = _env("GOOGLE_TTS_VOICE", "ko-KR-Standard-A")
    speaking_rate = float(_env("GOOGLE_TTS_SPEAKING_RATE", "0.9"))
    pitch = float(_env("GOOGLE_TTS_PITCH", "0"))

    client = _get_client(texttospeech)
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code=language_code,
        name=voice_name,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=speaking_rate,
        pitch=pitch,
    )
    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )
    out_path.write_bytes(response.audio_content)
