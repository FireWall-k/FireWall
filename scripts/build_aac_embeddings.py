"""자산 임베딩(data/aac/aac_embeddings.npz)을 만든다 — 매칭의 임베딩 가산 항에 쓰인다.

라벨과 라벨+검색어(인덱스의 keywords_ko/en) 두 텍스트를 임베딩해 저장한다. 텍스트를 만드는 규칙과
digest는 ai_service/embeddings.py와 같은 코드를 쓴다 — 인덱스의 라벨·검색어를 고치고 이 스크립트를
다시 돌리지 않으면 로더가 digest 불일치를 알아채고 임베딩을 쓰지 않는다(안전하게 기존 방식으로 동작).

    cd ai_service
    export OPENAI_API_KEY=...            # 또는 저장소 루트 .env
    python ../scripts/build_aac_embeddings.py            # 만들기(401개 ≈ 요청 2번, 1센트 미만)
    python ../scripts/build_aac_embeddings.py --check    # 낡았는지만 확인(API 호출 없음, 낡으면 종료코드 1)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ai_service"))


def _load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))
    # .env의 AAC_DATA_DIR는 도커 전용 경로(/app/aac)라 로컬 실행에서는 쓸 수 없다.
    os.environ.pop("AAC_DATA_DIR", None)


_load_dotenv()

import embeddings  # noqa: E402
import llm  # noqa: E402
import local_aac  # noqa: E402


def _embed_all(texts: list[str]) -> np.ndarray:
    out: list[list[float]] = []
    for i in range(0, len(texts), 256):
        out.extend(llm.embed_texts(texts[i:i + 256], timeout=60))
    vecs = np.asarray(out, dtype=np.float32)
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="자산 임베딩 생성/검사")
    ap.add_argument("--check", action="store_true", help="API 호출 없이 최신인지만 확인")
    args = ap.parse_args()

    path = local_aac.get_data_dir() / embeddings.STORE_FILENAME
    digest = embeddings.current_digest()

    if args.check:
        if not path.exists():
            raise SystemExit(f"없음: {path}")
        stored = str(np.load(path, allow_pickle=False)["digest"])
        if stored != digest:
            raise SystemExit("낡음: 라벨·검색어가 임베딩을 만든 뒤 바뀌었습니다. 다시 만드세요.")
        print("최신입니다.")
        return

    if not llm.llm_available():
        raise SystemExit("OPENAI_API_KEY가 없습니다(.env 또는 환경변수).")

    ids, labels, fulls = embeddings._current_texts()
    print(f"자산 {len(ids)}개 · 모델 {llm.EMBED_MODEL} · {llm.EMBED_DIMS}차원")
    np.savez_compressed(
        path,
        ids=np.array(ids),
        label_vecs=_embed_all(labels),
        full_vecs=_embed_all(fulls),
        digest=np.array(digest),
        model=np.array(llm.EMBED_MODEL),
        dims=np.array(llm.EMBED_DIMS),
    )
    print(f"저장: {path} ({path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
