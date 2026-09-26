"""TTS 실제 합성 경로 테스트.

Google 네트워크 호출만 가짜 클라이언트로 대체하고, tts.py의 실제 로직
(요청 구성 → mp3 파일 기록 → 해시 캐시 → URL 반환, 그리고 캐시 재사용)을
끝까지 실행한다. 이전에는 패키지 미설치(None 폴백) 경로만 확인했었다.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import tts  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_tts_state():
    # 실패 쿨다운·클라이언트 캐시는 모듈 전역이다. 테스트끼리 영향을 주지 않게 비운다.
    tts._reset_state()
    yield
    tts._reset_state()


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


def test_failure_starts_cooldown_so_later_steps_skip_the_call(monkeypatch, tmp_path):
    """결제 미설정처럼 설정 문제로 실패하면 이후 단계는 호출하지 않고 바로 폴백한다."""
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path))
    calls = {"n": 0}

    def boom(text, out_path):
        calls["n"] += 1
        raise RuntimeError("403 billing disabled")

    monkeypatch.setattr(tts, "_synthesize_google", boom)
    assert tts.synthesize_tts_url("첫 문장") is None
    assert tts.synthesize_tts_url("둘째 문장") is None
    assert tts.synthesize_tts_url("셋째 문장") is None
    assert calls["n"] == 1

    # 쿨다운이 지나면 다시 시도한다.
    monkeypatch.setattr(tts, "_cooldown_until", 0.0)
    assert tts.synthesize_tts_url("넷째 문장") is None
    assert calls["n"] == 2


def test_client_is_reused_across_calls(monkeypatch, tmp_path):
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path))
    _install_fake_google(monkeypatch)
    made = {"n": 0}
    m = sys.modules["google.cloud.texttospeech"]
    original = m.TextToSpeechClient

    def counting_client():
        made["n"] += 1
        return original()

    monkeypatch.setattr(m, "TextToSpeechClient", counting_client)
    assert tts.synthesize_tts_url("하나") and tts.synthesize_tts_url("둘")
    assert made["n"] == 1
