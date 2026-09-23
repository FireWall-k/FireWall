"""CLEANING_WORK/CLEANING/의 원본 파일명(라벨 포함)에서 CLEANING_051~190을
aac_assets.json에 등록한다. 이미지는 이미 data/aac/images/cleaning/에 변환돼 있다
(이 스크립트는 이미지를 건드리지 않고 메타데이터만 만든다).

    python scripts/register_cleaning_140.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "CLEANING_WORK" / "CLEANING"
ASSETS_PATH = ROOT / "data" / "aac" / "aac_assets.json"
IMAGES_DIR = ROOT / "data" / "aac" / "images" / "cleaning"

_NAME_RE = re.compile(r"^CLEANING_(\d+)_(.+)$")


def main() -> None:
    payload = json.loads(ASSETS_PATH.read_text(encoding="utf-8"))
    assets = payload["assets"]
    existing_ids = {a["id"] for a in assets}

    added = 0
    for path in sorted(STAGING.iterdir()):
        if path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        m = _NAME_RE.match(path.stem)
        if not m:
            print(f"  건너뜀(이름 규칙 안 맞음): {path.name}")
            continue
        num, label = int(m[1]), m[2].strip()
        asset_id = f"CLEANING_{num:03d}"
        if asset_id in existing_ids:
            print(f"  건너뜀(이미 등록됨): {asset_id}")
            continue
        webp = IMAGES_DIR / f"{asset_id}.webp"
        if not webp.exists():
            print(f"  건너뜀(변환된 이미지 없음): {asset_id}")
            continue
        assets.append({
            "id": asset_id, "group_id": asset_id, "job": "cleaning",
            "asset_type": "action", "variant": None,
            "label": label, "keywords": [], "aliases": [],
            "search_text": f"cleaning {label}",
            "image": f"cleaning/{asset_id}.webp", "source_file": path.name,
            "action": "other", "objects": [],
        })
        existing_ids.add(asset_id)
        added += 1

    counts: dict[str, int] = {}
    for a in assets:
        counts[a["job"].upper()] = counts.get(a["job"].upper(), 0) + 1
    payload["jobs"] = counts
    payload["asset_count"] = len(assets)
    ASSETS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\r\n",
    )
    print(f"등록 {added}건, 전체 자산 {len(assets)}개")


if __name__ == "__main__":
    main()
