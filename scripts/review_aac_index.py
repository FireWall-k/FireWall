"""aac_index.json 을 점검하고 기계적으로 고칠 수 있는 것은 고친다.

401건을 사람이 눈으로 훑는 대신:
  1) 자동 점검으로 형태 오류를 잡아낸다(verb가 사전형이 아님, 라벨 오염 등)
  2) 확실한 것은 자동 수정하고 reviewed 플래그를 남긴다
  3) 판단이 필요한 것은 목록으로 뽑아 사람에게 넘긴다

현재 매칭이 쓰는 프레임 필드는 verb / verb_class / is_object_card / keywords_ko 뿐이다.
object / object_detail / instrument / location 은 아직 안 쓴다 — 그래서 점검 우선순위도
앞 네 개에 둔다.

실행:
    python scripts/review_aac_index.py                # 점검만(수정 안 함)
    python scripts/review_aac_index.py --fix          # 기계적 수정 적용
    python scripts/review_aac_index.py --list needs-human   # 사람 판단 목록만
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "data" / "aac" / "aac_index.json"
ASSETS_PATH = ROOT / "data" / "aac" / "aac_assets.json"

_HANGUL = re.compile(r"[가-힣]+")

# 활용형이 원형 자리에 들어온 경우의 교정. 왼쪽이 잘못된 값, 오른쪽이 사전형.
_VERB_FIXES = {
    "센다": "세다",
    "셀다": "세다",
    "여는 손동작": "열다",
    "저어 섞다": "섞다",
}

# 라벨 앞에 붙는 출처 데이터의 분류 접두사. 실제 수식어가 아니다.
_SOURCE_PREFIXES = ("도구",)

_VALID_VERB_CLASSES = {
    "observe", "move", "stack", "sort", "pack", "clean", "wear", "operate", "other",
}


def _label_tokens(label: str) -> set[str]:
    return set(_HANGUL.findall(label))


def check_entry(entry: dict, asset: dict) -> list[tuple[str, str]]:
    """한 항목의 문제를 (심각도, 설명)으로 돌려준다. 심각도: fix | human | note."""
    problems: list[tuple[str, str]] = []
    frame = entry.get("frame") or {}
    verb = frame.get("verb")
    verb_class = frame.get("verb_class")
    is_object = bool(frame.get("is_object_card"))
    label = entry.get("label", "")

    # --- verb 형태 ---
    if verb is not None:
        if verb in _VERB_FIXES:
            problems.append(("fix", f"verb {verb!r} → {_VERB_FIXES[verb]!r} (활용형)"))
        elif " " in verb or not verb.endswith("다"):
            problems.append(("human", f"verb {verb!r} 가 사전형이 아님"))

    # --- 사물/동작 카드 일관성 ---
    if is_object and verb:
        problems.append(("fix", "사물 카드인데 verb가 있음 → verb/verb_class 비우기"))
    if not is_object and not verb:
        # 라벨이 명사구뿐이면 사물 카드여야 한다.
        if not any(label.endswith(e) for e in ("다", "동작", "모습", "상황", "상태")):
            problems.append(("human", f"동작 카드인데 verb 없음, 라벨={label!r}"))

    # --- verb_class ---
    if verb and not is_object:
        if verb_class not in _VALID_VERB_CLASSES:
            problems.append(("human", f"알 수 없는 verb_class {verb_class!r}"))
        elif verb_class == "other":
            # '확인/점검/살펴' 계열은 observe 여야 한다.
            if any(w in label for w in ("확인", "점검", "살펴", "비교")):
                problems.append(("fix", f"verb_class other → observe (라벨에 확인/점검/비교)"))

    # --- 출처 접두사 오염 ---
    obj = frame.get("object") or ""
    detail = frame.get("object_detail") or ""
    if detail in _SOURCE_PREFIXES:
        problems.append(("fix", f"object_detail {detail!r} 은 출처 접두사 → 비우기"))
    if any(obj.startswith(p + " ") for p in _SOURCE_PREFIXES):
        problems.append(("fix", f"object {obj!r} 앞의 출처 접두사 제거"))

    # --- keywords_ko 가 라벨을 되풀이 ---
    kw = [k for k in entry.get("keywords_ko", []) if isinstance(k, str)]
    if kw:
        lt = _label_tokens(label)
        echoed = sum(1 for k in kw if _label_tokens(k) & lt)
        if echoed >= max(2, len(kw) * 0.75):
            problems.append(("human", f"keywords_ko {echoed}/{len(kw)}가 라벨과 겹침"))
        elif not kw:
            problems.append(("human", "keywords_ko 비어 있음"))

    return problems


def apply_fixes(entry: dict) -> list[str]:
    """확실한 수정만 제자리에서 적용한다. 적용한 항목 설명을 돌려준다."""
    applied: list[str] = []
    frame = entry["frame"]
    verb = frame.get("verb")

    if verb in _VERB_FIXES:
        frame["verb"] = _VERB_FIXES[verb]
        applied.append(f"verb → {frame['verb']}")

    if frame.get("is_object_card") and frame.get("verb"):
        frame["verb"] = None
        frame["verb_class"] = None
        applied.append("사물 카드의 verb/verb_class 비움")

    label = entry.get("label", "")
    if (frame.get("verb") and not frame.get("is_object_card")
            and frame.get("verb_class") == "other"
            and any(w in label for w in ("확인", "점검", "살펴", "비교"))):
        frame["verb_class"] = "observe"
        applied.append("verb_class → observe")

    if frame.get("object_detail") in _SOURCE_PREFIXES:
        frame["object_detail"] = None
        applied.append("object_detail 접두사 비움")

    obj = frame.get("object") or ""
    for p in _SOURCE_PREFIXES:
        if obj.startswith(p + " "):
            frame["object"] = obj[len(p) + 1:]
            applied.append(f"object → {frame['object']}")
            break

    if applied:
        entry["reviewed"] = "auto"  # 사람이 아니라 규칙이 손댔다는 표시
    return applied


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="기계적 수정을 파일에 반영")
    ap.add_argument("--list", choices=["needs-human", "all"], help="문제 목록 출력")
    args = ap.parse_args()

    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    assets = {a["id"]: a for a in json.loads(ASSETS_PATH.read_text(encoding="utf-8"))["assets"]}
    entries = index["entries"]

    by_severity: dict[str, list[tuple[str, str]]] = {"fix": [], "human": [], "note": []}
    fixed_count = 0

    for entry in entries:
        asset = assets.get(entry["id"], {})
        problems = check_entry(entry, asset)
        for severity, desc in problems:
            by_severity[severity].append((entry["id"], desc))

        if args.fix:
            applied = apply_fixes(entry)
            if applied:
                fixed_count += 1
                if args.list:
                    print(f"  고침 {entry['id']}: {'; '.join(applied)}")

    print(f"\n점검 {len(entries)}건")
    print(f"  자동 수정 가능 : {len(by_severity['fix'])}건")
    print(f"  사람 판단 필요 : {len(by_severity['human'])}건")

    if args.list == "needs-human":
        print("\n--- 사람 판단 필요 ---")
        for entry_id, desc in by_severity["human"]:
            entry = next(e for e in entries if e["id"] == entry_id)
            print(f"  {entry_id:<18} {entry['label']}")
            print(f"    → {desc}")

    if args.fix:
        INDEX_PATH.write_text(
            json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"\n{fixed_count}건 수정, 저장: {INDEX_PATH}")


if __name__ == "__main__":
    main()
