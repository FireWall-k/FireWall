"""저장소에 커밋되는 비밀값 예시 파일이 자리표시자로 남아 있는지 (Phase 0.5 보완).

.gitleaks.toml은 secrets/google-tts.json.example을 경로째 예외로 둔다(예시 파일 형식이 개인 키 규칙에
걸릴 수 있어서). 그 대가로 누가 여기에 진짜 서비스 계정 키를 붙여 넣어도 gitleaks가 못 잡는다. 이 테스트가
대신 막는다: private_key 본문(BEGIN/END 줄과 공백·\\n을 뺀 부분)이 100자 미만이어야 한다. 진짜 RSA 2048 키의
본문은 약 1,600자다. 실패 메시지에 값은 절대 넣지 않는다(CI 로그로 새지 않게) — 길이만 알린다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "secrets" / "google-tts.json.example"
PLACEHOLDER_MAX_CHARS = 100


def _key_body(pem: str) -> str:
    body = re.sub(r"-----(BEGIN|END)[A-Z ]*-----", "", pem)
    return re.sub(r"(\\n|\s)", "", body)


def test_google_tts_example_private_key_is_placeholder():
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    body = _key_body(data.get("private_key", ""))
    assert len(body) < PLACEHOLDER_MAX_CHARS, (
        f"{EXAMPLE.name}의 private_key 본문이 {len(body)}자입니다 — 진짜 키로 보입니다. "
        "즉시 키를 폐기하고 예시 파일을 자리표시자로 되돌리세요(docs/security/secrets.md)."
    )


def test_key_body_measures_real_key_shape():
    """검사 자체가 진짜 키 모양을 잡는지(본문 길이 계산이 0으로 망가지면 위 테스트가 늘 통과한다)."""
    # PEM 머리줄을 조각내 만든다 — 그대로 적으면 이 테스트 파일 자체가 gitleaks private-key 규칙에 걸린다.
    begin, end = "-----BEGIN " + "PRIVATE KEY-----", "-----END " + "PRIVATE KEY-----"
    fake_real = begin + "\\n" + ("A" * 64 + "\\n") * 25 + end + "\\n"
    assert len(_key_body(fake_real)) == 1600
    assert len(_key_body(begin + "\\nREPLACE_ME\\n" + end + "\\n")) < 100


def test_gitleaks_example_allowlist_stays_narrow():
    """예외는 이 예시 파일 하나만이어야 한다. 디렉터리째(secrets/) 빼면 진짜 키 파일도 스캔에서 빠진다."""
    config = (ROOT / ".gitleaks.toml").read_text(encoding="utf-8")
    paths = re.findall(r"^paths\s*=\s*\[(.*?)\]", config, flags=re.M)
    assert paths == ["'''^secrets/google-tts\\.json\\.example$'''"]
