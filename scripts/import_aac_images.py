"""새 직무 이미지 폴더를 AAC 자산으로 등록한다.

입력: data/aac/images/<DELIVERY|DISPLAY|...>/  (파일명 `<PREFIX>_<번호>_<한국어 라벨>.png` 등)
동작: 768x768 WebP로 변환해 data/aac/images/<job>/<ID>.webp 로 저장하고 aac_assets.json에 등록한다.
      원본 PNG는 먼저 --originals-dir 로 옮기고 거기서 읽는다(저장소에 커밋하지 않기 위해).
이후 순서: enrich_aac_metadata.py --job <job> → build_aac_index.py --resume → build_aac_embeddings.py

    python scripts/import_aac_images.py DELIVERY DISPLAY GAS SERVING
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
AAC_DIR = ROOT / "data" / "aac"
ASSETS_PATH = AAC_DIR / "aac_assets.json"
SIZE = 768

# 파일명에 섞여 있던 오타를 바로잡는다.
_TYPOS = {"DISPALY": "DISPLAY"}
_NAME_RE = re.compile(r"^(?P<prefix>[A-Za-z]+)(?:_(?P<kind>ASSET|TOOL|AUX))?[_ ](?P<num>\d+)[_ ]*(?P<label>.*)$")


def parse(stem: str, folder_prefix: str) -> tuple[str, int, str, str]:
    for wrong, right in _TYPOS.items():
        stem = stem.replace(wrong, right)
    m = _NAME_RE.match(stem)
    if not m or m["prefix"].upper() != folder_prefix:
        raise ValueError(f"파일명 규칙에 맞지 않음: {stem}")
    kind = (m["kind"] or "").upper()
    return m["prefix"].upper(), int(m["num"]), kind, m["label"].strip()


def to_webp(src: Path, dst: Path) -> None:
    img = Image.open(src)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    if img.size != (SIZE, SIZE):
        img = img.resize((SIZE, SIZE), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "WEBP", quality=85, method=6)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+", help="data/aac/images 아래 대문자 폴더명")
    ap.add_argument("--originals-dir", type=Path, default=ROOT / "_aac_originals")
    args = ap.parse_args()

    payload = json.loads(ASSETS_PATH.read_text(encoding="utf-8"))
    assets = payload["assets"]
    used = {a["id"] for a in assets}

    for folder in args.folders:
        # Windows는 대소문자를 구분하지 않아 DISPLAY/ 와 display/ 가 같은 폴더가 된다.
        # 원본을 먼저 밖으로 옮기고 거기서 읽는다.
        src_dir = args.originals_dir / folder
        if not src_dir.exists():
            src_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(AAC_DIR / "images" / folder), str(src_dir))
        job = folder.lower()
        prefix = folder.upper()
        files = sorted(p for p in src_dir.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
        added = 0
        parsed = [parse(p.stem, prefix) for p in files]
        # 파일이 원래 가진 번호를 전부 예약해 두고, 충돌한 파일만 그 뒤 번호를 받는다(연쇄 밀림 방지).
        reserved = {f"{prefix}_{k + '_' if k else ''}{n:03d}" for _, n, k, _ in parsed}
        seen: set[str] = set()
        for path, (_, num, kind, label) in zip(files, parsed):
            is_tool = kind in ("ASSET", "TOOL")
            base = f"{prefix}_{kind + '_' if kind else ''}{num:03d}"
            asset_id = base
            if asset_id in seen or asset_id in used:
                # 같은 번호가 두 파일에 붙어 있으면 뒤에 온 한 장만 그 종류의 최대 번호 다음을 받는다.
                pat = re.compile(rf"^{prefix}_{kind + '_' if kind else ''}(\d+)$")
                top = max(int(m[1]) for i in used | reserved if (m := pat.match(i)))
                asset_id = f"{prefix}_{kind + '_' if kind else ''}{top + 1:03d}"
                print(f"  번호 충돌: {path.name} → {asset_id}")
            used.add(asset_id)
            seen.add(asset_id)
            rel = f"{job}/{asset_id}.webp"
            to_webp(path, AAC_DIR / "images" / rel)
            assets.append({
                "id": asset_id, "group_id": asset_id, "job": job,
                "asset_type": "tool" if is_tool else "action", "variant": None,
                "label": label, "keywords": [], "aliases": [], "search_text": f"{job} {label}",
                "image": rel, "source_file": path.name, "action": "other", "objects": [],
            })
            added += 1
        print(f"{folder}: {added}장 등록 → images/{job}/")

    counts: dict[str, int] = {}
    for a in assets:
        counts[a["job"].upper()] = counts.get(a["job"].upper(), 0) + 1
    payload["jobs"] = counts
    payload["asset_count"] = len(assets)
    ASSETS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\r\n")
    print(f"원본 이동: {args.originals_dir}")


if __name__ == "__main__":
    main()
