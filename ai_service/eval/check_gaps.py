"""갭 케이스 재점검 — 그림을 추가한 뒤 '정답 그림 없음'이 아직 사실인지 확인한다.

왜 필요한가: 갭 케이스(gap=true)는 "이 문장에 맞는 그림이 데이터에 없다"는 주장이다. 그림이
늘면 이 주장은 조용히 낡는다. 낡은 갭은 맞는 그림을 붙여도 오답 채택으로 세어, 지표가 실제보다
나쁘게 나오고 스코어러를 엉뚱한 방향(맞는 그림을 거절하도록)으로 튜닝하게 만든다. 골든셋에서
실제로 3건이 그랬다 — 에어컨 필터 세척·박스 쌓기 그림이 갭 노트를 쓴 뒤에 추가됐다.

무엇을 보여 주는가(갭 케이스마다):
    - 시스템 판정(자동 채택이면 '갭 뚫림' — 오답 채택으로 세이는 중)
    - 상위 후보와 라벨·점수 — 사람이 그림을 열어 판정할 출발점
    - 의심 자산: 문장의 동작과 대상을 '모두' 가진 그림. 동작은 동사 원형이 같거나 동작 분류
      (action_type ↔ frame.verb_class)가 같으면, 대상은 문장 명사가 frame.object에
      있으면 같다고 본다. 둘 중 하나만 같은 그림은 띄우지 않는다 — 동사만 같은 그림
      ("닦는다")은 수십 장이라 목록이 잡음이 된다.

의심은 '판정'이 아니라 '사람이 그림을 열어 볼 목록'이다. 갭을 풀지는 이미지를 직접 보고 정한다.

실행:
    cd ai_service
    python -m eval.check_gaps                     # 골든셋 갭 전체
    python -m eval.check_gaps --dataset dev       # 개발셋
    python -m eval.check_gaps --suspects-only     # 의심 자산이 있는 갭만
    python -m eval.check_gaps --fail-on-suspect   # 의심이 있으면 종료 코드 1(자산 추가 후 점검용)

네트워크를 쓰지 않는다(임베딩 off — 채점 하네스와 같은 규칙 경로).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from local_aac import (  # noqa: E402
    _TOKEN_RE, _tokens, _verb_lemmas, load_assets, search_for_step_detailed,
)
from eval.run_match_eval import (  # noqa: E402
    EMBED_CACHE_DIR, _case_inputs, _embedding_mode, resolve_dataset,
)

# 의심 자산의 순위를 붙이려고 넉넉히 받는다. 판정(decide)은 1·2위만 보므로 결과는 같다.
_SEARCH_DEPTH = 50


@lru_cache(maxsize=1)
def _verbal_nouns() -> frozenset[str]:
    """'정리하다'·'확인하다'의 '정리'·'확인' — 자산 동사 원형에서 '하다'를 뗀 것.

    "정리해주세요"는 동사 원형 추출에 안 걸리고 어미만 떨어져 '정리'가 남는다. 이걸 대상으로
    치면 같은 동사를 가진 그림 수십 장이 전부 '대상 일치'로 잡힌다(실측: '재고를 확인해주세요'
    에 89건). 동작은 _shares_action이 따로 보므로 대상 쪽에서는 뺀다.
    """
    return frozenset(
        lemma[:-2] for asset in load_assets() for lemma in asset.get("_lemmas", set())
        if lemma.endswith("하다") and len(lemma) > 3
    )


def _content_nouns(texts: list[str]) -> set[str]:
    """문장·symbol_query에서 동사 활용형을 뺀 내용어 토큰. 한글이 없는 토큰(영어)은 뺀다 —
    자산 라벨이 한국어라 겹칠 수 없고, 비교 대상만 늘린다."""
    nouns: set[str] = set()
    for text in texts:
        for word in _TOKEN_RE.findall(text):
            if _verb_lemmas(word):
                continue  # "청소하세요"·"쌓으세요" 같은 동사는 대상이 아니다.
            nouns |= {t for t in _tokens(word) if any("가" <= ch <= "힣" for ch in t)}
    return nouns - _verbal_nouns()


def _asset_objects(asset: dict) -> set[str]:
    """그림의 대상 명사. 라벨 전체가 아니라 frame.object만 본다 — 라벨 토큰에는 '위에'·'물로'·
    '따로' 같은 부사어가 섞여(조사 제거가 두 글자 단어에는 안 걸린다) 엉뚱한 그림이 '대상
    일치'로 잡힌다. frame이 없는 자산은 대상을 모르므로 의심에서 빠진다."""
    frame = asset.get("_frame") or {}
    return _tokens(str(frame.get("object") or ""))


def _shares_action(asset: dict, lemmas: set[str], action_type: str | None) -> bool:
    if lemmas & asset.get("_lemmas", set()):
        return True
    # 동사 표면형이 달라도("청소하다" vs "세척하다") 동작 분류가 같으면 같은 동작으로 본다.
    return bool(action_type) and action_type != "other" and asset.get("_verb_class") == action_type


def _gap_row(case: dict, top: int) -> dict:
    keywords, ctx = _case_inputs(case, "full")
    decision = search_for_step_detailed(keywords, ctx, limit=_SEARCH_DEPTH)
    ranked = decision["candidates"]
    rank_of = {r["asset_id"]: i + 1 for i, r in enumerate(ranked)}
    score_of = {r["asset_id"]: r["score"] for r in ranked}

    lemmas = _verb_lemmas(case["sentence"])
    nouns = _content_nouns([case["sentence"], *keywords])
    action_type = case.get("action_type")

    suspects = []
    for asset in load_assets():
        shared = nouns & _asset_objects(asset)
        if shared and _shares_action(asset, lemmas, action_type):
            suspects.append({
                "id": asset["id"], "label": asset.get("label", ""),
                "rank": rank_of.get(asset["id"]), "score": score_of.get(asset["id"]),
                "shared_objects": sorted(shared),
            })
    # 검색 순위가 있는 것(실제로 붙을 가능성이 큰 것)을 먼저, 나머지는 id 순으로 — 결정적.
    suspects.sort(key=lambda s: (s["rank"] is None, s["rank"] or 0, s["id"]))

    match = decision["match"]
    return {
        "id": case["id"],
        "job": case.get("job", ""),
        "sentence": case["sentence"],
        "note": case.get("note", ""),
        "reason": decision["reason"],
        "accepted": match is not None,
        "accepted_id": match["asset_id"] if match else None,
        "candidates": [
            {"id": r["asset_id"], "label": r["label"], "score": round(r["score"], 4)}
            for r in ranked[:top]
        ],
        "suspects": suspects,
    }


def check_gaps(dataset: str | os.PathLike = "golden", top: int = 5,
               only_job: str | None = None) -> list[dict]:
    """데이터셋의 갭 케이스마다 상위 후보·판정·의심 자산을 낸다(임베딩 off)."""
    path = resolve_dataset(dataset)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = [c for c in data["cases"] if c.get("gap")]
    if only_job:
        cases = [c for c in cases if c.get("job") == only_job]
    with _embedding_mode("off", EMBED_CACHE_DIR):
        return [_gap_row(c, top) for c in cases]


def format_report(rows: list[dict]) -> str:
    lines = []
    for row in rows:
        verdict = f"갭 뚫림(자동 채택 {row['accepted_id']})" if row["accepted"] else f"거절({row['reason']})"
        flag = f"  의심 {len(row['suspects'])}건" if row["suspects"] else ""
        lines.append(f"[{row['id']}] {row['sentence']}  — {verdict}{flag}")
        if row.get("note"):
            lines.append(f"    note: {row['note']}")
        for i, c in enumerate(row["candidates"], 1):
            mark = " *" if any(s["id"] == c["id"] for s in row["suspects"]) else ""
            lines.append(f"    {i}. {c['id']:<22} {c['score']:.3f}  {c['label']}{mark}")
        for s in row["suspects"]:
            where = f"{s['rank']}위" if s["rank"] else "순위 밖"
            lines.append(f"    의심: {s['id']:<22} {where:>5}  {s['label']}  "
                         f"(겹친 대상: {', '.join(s['shared_objects'])})")
        lines.append("")
    n_sus = sum(1 for r in rows if r["suspects"])
    n_breach = sum(1 for r in rows if r["accepted"])
    lines.append(f"갭 {len(rows)}건 — 의심 자산 있음 {n_sus}건, 자동 채택(갭 뚫림) {n_breach}건. "
                 "의심은 그림을 직접 열어 판정한다(* = 상위 후보 중 의심 자산).")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="갭 케이스 재점검(그림 추가 후)")
    ap.add_argument("--dataset", default="golden", help="golden | dev | 파일 경로")
    ap.add_argument("--job", help="특정 직무만")
    ap.add_argument("--top", type=int, default=5, help="보여 줄 상위 후보 수")
    ap.add_argument("--suspects-only", action="store_true", help="의심 자산이 있는 갭만 출력")
    ap.add_argument("--json", help="결과를 JSON으로 저장")
    ap.add_argument("--fail-on-suspect", action="store_true",
                    help="의심 자산이 있는 갭이 하나라도 있으면 종료 코드 1")
    args = ap.parse_args()

    rows = check_gaps(args.dataset, top=args.top, only_job=args.job)
    shown = [r for r in rows if r["suspects"]] if args.suspects_only else rows
    print(format_report(shown))
    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.fail_on_suspect and any(r["suspects"] for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
