"""Google Cloud Text-to-Speech 연동 모듈.

잡카드의 TTS는 Google Cloud Text-to-Speech를 기본 provider로 사용한다.
서비스 계정 JSON이 없거나 API 호출에 실패하면 전체 직무 생성이 중단되지 않도록
None을 반환하고, 프론트엔드는 브라우저 SpeechSynthesis를 fallback으로 사용한다.

운영 의도:
- MVP/PoC: GOOGLE_APPLICATION_CREDENTIALS=/app/secrets/google-tts.json 설정
- 음성 캐시: 같은 문장/음성 옵션은 mp3를 재생성하지 않고 캐시 재사용
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
            _client_cache = (texttospeech, texttospeech.TextToSpeechClient())
        return _client_cache[1]


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def get_tts_cache_dir() -> Path:
    cache_dir = Path(_env("TTS_CACHE_DIR", "./data/tts"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _public_url(filename: str) -> str:
    base = _env("PUBLIC_BACKEND_URL", "http://localhost:8000").rstrip("/")
    return f"{base}/api/tts/{filename}"


def _google_voice_key(text: str) -> str:
    voice_key = "|".join([
        "google",
        _env("GOOGLE_TTS_LANGUAGE", "ko-KR"),
        _env("GOOGLE_TTS_VOICE", "ko-KR-Standard-A"),
        _env("GOOGLE_TTS_SPEAKING_RATE", "0.9"),
        _env("GOOGLE_TTS_PITCH", "0"),
        text,
    ])
    return hashlib.sha256(voice_key.encode("utf-8")).hexdigest()[:32]


def synthesize_tts_url(text: str) -> str | None:
    """Google Cloud TTS로 문장을 mp3로 합성하고 접근 URL을 반환한다.

    실패 시 None을 반환한다. 프론트엔드에서는 None이면 브라우저 TTS fallback을 사용한다.
    이렇게 해야 Google 인증 파일이 없는 개발 환경에서도 직무 생성 흐름이 깨지지 않는다.
    """
    text = text.strip()
    if not text:
        return None

    filename = f"{_google_voice_key(text)}.mp3"
    out_path = get_tts_cache_dir() / filename
    if out_path.exists() and out_path.stat().st_size > 0:
        return _public_url(filename)

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
        return _public_url(filename)
    return None


def _synthesize_google(text: str, out_path: Path) -> None:
    """Google Cloud Text-to-Speech 합성.

    인증은 GOOGLE_APPLICATION_CREDENTIALS 환경변수 또는 Google ADC 방식을 따른다.
    Docker에서는 기본적으로 /app/secrets/google-tts.json 경로를 사용한다.
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
