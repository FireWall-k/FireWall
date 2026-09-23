from __future__ import annotations

import argparse
import json
import re
import shutil
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

IMAGE_SIZE = (768, 768)
ID_RE = re.compile(r"^(ASSEMBLY_(\d{3}))_(.+)\.png$", re.IGNORECASE)


def label_from_filename(name: str) -> tuple[str, int, str] | None:
    m = ID_RE.match(name)
    if not m:
        return None
    asset_id, number, raw_label = m.groups()
    return asset_id.upper(), int(number), raw_label.replace("_", " ").strip()


def normalize_to_webp(raw: bytes, output: Path) -> None:
    with Image.open(BytesIO(raw)) as src:
        img = src.convert("RGB")
        fitted = ImageOps.contain(img, IMAGE_SIZE, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", IMAGE_SIZE, "white")
        x = (IMAGE_SIZE[0] - fitted.width) // 2
        y = (IMAGE_SIZE[1] - fitted.height) // 2
        canvas.paste(fitted, (x, y))
        output.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output, "WEBP", quality=90, method=6)


def base_asset(asset_id: str, label: str, source_file: str) -> dict:
    return {
        "id": asset_id,
        "group_id": asset_id,
        "job": "assembly",
        "asset_type": "action",
        "variant": None,
        "label": label,
        "keywords": [],
        "aliases": [],
        "search_text": "",
        "image": f"assembly/{asset_id}.webp",
        "source_file": source_file,
        "action": "other",
        "objects": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ASSEMBLY_039~175 PNG를 JobCard AAC 데이터셋에 추가"
    )
    parser.add_argument("zip_path", type=Path, help="ASSEMBLY.zip 경로")
    parser.add_argument("--min-id", type=int, default=39)
    parser.add_argument("--max-id", type=int, default=175)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="FireWall 프로젝트 루트(기본: 이 스크립트의 상위 폴더)",
    )
    args = parser.parse_args()

    root = args.project_root.resolve()
    data_dir = root / "data" / "aac"
    assets_path = data_dir / "aac_assets.json"
    image_dir = data_dir / "images" / "assembly"

    if not args.zip_path.exists():
        raise SystemExit(f"ZIP을 찾을 수 없습니다: {args.zip_path}")
    if not assets_path.exists():
        raise SystemExit(f"aac_assets.json을 찾을 수 없습니다: {assets_path}")

    payload = json.loads(assets_path.read_text(encoding="utf-8"))
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise SystemExit("aac_assets.json에 assets 배열이 없습니다.")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = assets_path.with_name(f"aac_assets.before-assembly-expansion-{stamp}.json")
    shutil.copy2(assets_path, backup)

    positions = {a.get("id"): i for i, a in enumerate(assets)}
    found: list[tuple[int, str, str, str, bytes]] = []

    with zipfile.ZipFile(args.zip_path) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            base = Path(member.filename).name
            parsed = label_from_filename(base)
            if not parsed:
                continue
            asset_id, number, label = parsed
            if not (args.min_id <= number <= args.max_id):
                continue
            found.append((number, asset_id, label, base, zf.read(member)))

    found.sort(key=lambda x: x[0])
    if not found:
        raise SystemExit("지정 범위에 맞는 ASSEMBLY PNG를 ZIP에서 찾지 못했습니다.")

    expected = set(range(args.min_id, args.max_id + 1))
    actual = {n for n, *_ in found}
    missing = sorted(expected - actual)
    if missing:
        print(f"[주의] ZIP에 없는 번호: {missing}")

    added = 0
    updated = 0
    converted = 0

    for number, asset_id, label, source_file, raw in found:
        normalize_to_webp(raw, image_dir / f"{asset_id}.webp")
        converted += 1

        if asset_id in positions:
            # 이미 등록된 경우 이미지/라벨/소스 경로만 갱신하고 기존 보강 메타데이터는 보존한다.
            i = positions[asset_id]
            old = dict(assets[i])
            old.update({
                "group_id": old.get("group_id") or asset_id,
                "job": "assembly",
                "asset_type": old.get("asset_type") or "action",
                "label": label,
                "image": f"assembly/{asset_id}.webp",
                "source_file": source_file,
            })
            assets[i] = old
            updated += 1
        else:
            positions[asset_id] = len(assets)
            assets.append(base_asset(asset_id, label, source_file))
            added += 1

    payload["asset_count"] = len(assets)
    jobs = payload.setdefault("jobs", {})
    jobs["ASSEMBLY"] = sum(1 for a in assets if str(a.get("job", "")).lower() == "assembly")

    assets_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("=" * 64)
    print("ASSEMBLY expansion import complete")
    print("=" * 64)
    print(f"백업       : {backup}")
    print(f"PNG 발견   : {len(found)}")
    print(f"WebP 변환  : {converted}")
    print(f"신규 등록  : {added}")
    print(f"기존 갱신  : {updated}")
    print(f"전체 asset : {payload['asset_count']}")
    print(f"ASSEMBLY   : {jobs['ASSEMBLY']}")
    print()
    print("다음 단계: 신규 ASSEMBLY metadata 보강 후 aac_index.json --resume 생성")


if __name__ == "__main__":
    main()
