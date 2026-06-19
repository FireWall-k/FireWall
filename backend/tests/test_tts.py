"""TTS 실제 합성 경로 테스트.

Google 네트워크 호출만 가짜 클라이언트로 대체하고, tts.py의 실제 로직
(요청 구성 → mp3 파일 기록 → 해시 캐시 → URL 반환, 그리고 캐시 재사용)을
끝까지 실행한다. 이전에는 패키지 미설치(None 폴백) 경로만 확인했었다.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tts  # noqa: E402


def _install_fake_google(monkeypatch, audio=b"FAKEMP3BYTES", counter=None):
    """from google.cloud import texttospeech 를 가짜 모듈로 주입."""
    m = types.ModuleType("google.cloud.texttospeech")

    class _Enc:
        MP3 = "MP3"

    class _Client:
        def synthesize_speech(self, *, input, voice, audio_config):
            if counter is not None:
                counter["calls"] += 1
            assert input.text  # 요청 구성이 제대로 전달됐는지 확인
            return types.SimpleNamespace(audio_content=audio)

    m.SynthesisInput = lambda text: types.SimpleNamespace(text=text)
    m.VoiceSelectionParams = lambda language_code, name: types.SimpleNamespace(
        language_code=language_code, name=name)
    m.AudioConfig = lambda audio_encoding, speaking_rate, pitch: types.SimpleNamespace(
        audio_encoding=audio_encoding, speaking_rate=speaking_rate, pitch=pitch)
    m.AudioEncoding = _Enc
    m.TextToSpeechClient = _Client

    google = types.ModuleType("google")
    google_cloud = types.ModuleType("google.cloud")
    google_cloud.texttospeech = m
    google.cloud = google_cloud
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.cloud", google_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.texttospeech", m)


def test_real_path_writes_mp3_and_returns_url(monkeypatch, tmp_path):
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_BACKEND_URL", "http://localhost:8000")
    counter = {"calls": 0}
    _install_fake_google(monkeypatch, audio=b"ID3FAKEAUDIO", counter=counter)

    url = tts.synthesize_tts_url("상자를 옮기세요")
    assert url is not None
    assert url.startswith("http://localhost:8000/api/tts/")
    assert url.endswith(".mp3")

    # 실제로 mp3 파일이 캐시 디렉터리에 기록됐는지
    files = list(tmp_path.glob("*.mp3"))
    assert len(files) == 1
    assert files[0].read_bytes() == b"ID3FAKEAUDIO"
    assert counter["calls"] == 1


def test_cache_is_reused_no_second_call(monkeypatch, tmp_path):
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path))
    counter = {"calls": 0}
    _install_fake_google(monkeypatch, counter=counter)

    first = tts.synthesize_tts_url("같은 문장")
    second = tts.synthesize_tts_url("같은 문장")
    assert first == second
    # 같은 문장/음성 옵션 → 두 번째는 캐시 히트, 클라이언트 호출 1회뿐
    assert counter["calls"] == 1


def test_empty_text_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path))
    _install_fake_google(monkeypatch)
    assert tts.synthesize_tts_url("   ") is None


def test_client_failure_falls_back_to_none(monkeypatch, tmp_path):
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path))

    # synthesize_speech가 예외를 던지면 None 폴백(흐름 비중단)이어야 한다.
    m = types.ModuleType("google.cloud.texttospeech")

    class _Boom:
        def synthesize_speech(self, **kw):
            raise RuntimeError("quota exceeded")

    m.SynthesisInput = lambda text: types.SimpleNamespace(text=text)
    m.VoiceSelectionParams = lambda **kw: types.SimpleNamespace(**kw)
    m.AudioConfig = lambda **kw: types.SimpleNamespace(**kw)
    m.AudioEncoding = types.SimpleNamespace(MP3="MP3")
    m.TextToSpeechClient = _Boom
    google = types.ModuleType("google")
    google_cloud = types.ModuleType("google.cloud")
    google_cloud.texttospeech = m
    google.cloud = google_cloud
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.cloud", google_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.texttospeech", m)

    assert tts.synthesize_tts_url("문장") is None
    assert list(tmp_path.glob("*.mp3")) == []
