"""
Map task-step keywords to project-owned local AAC assets.
"""
from __future__ import annotations

from local_aac import search_for_step_detailed
from schemas import AacMatch, MapSymbolsResult, Symbol

# 사람에게 보여줄 후보 개수. recall@3이 0.988이라 3개면 거의 항상 정답이 들어 있다
# (eval/run_match_eval.py 참고). 더 늘리면 고르는 부담만 커진다.
_SHORTLIST = 3


def map_symbols(keywords: list[str], context: dict) -> MapSymbolsResult:
    decision = search_for_step_detailed(keywords, context)
    match = decision["match"]

    query_label = (
        " / ".join(keywords)
        if keywords
        else str(context.get("sentence") or "")
    )

    if match:
        return MapSymbolsResult(
            symbols=[
                Symbol(
                    keyword=query_label,
                    image_url=match["image_url"],
                    source="LOCAL_AAC",
                    confidence=match["score"],
                    needs_fallback=False,
                    external_id=match["asset_id"],
                    resolved_keyword=match["label"],
                    reason="accepted",
                )
            ]
        )

    # 자동 채택하지 못했다. 후보가 있으면 함께 넘겨 검토 화면에서 고를 수 있게 한다.
    return MapSymbolsResult(
        symbols=[
            Symbol(
                keyword=query_label,
                image_url=None,
                source="fallback",
                confidence=0.0,
                needs_fallback=True,
                # frame_mismatch(대상이 다른 그림)는 '후보를 보여 주고 사람이 고른다'는 화면
                # 동작이 low_margin과 같다. backend·frontend 계약의 reason 값을 늘리지 않으려고
                # 바깥으로는 low_margin으로 내보낸다.
                reason=("low_margin" if decision["reason"] == "frame_mismatch"
                        else decision["reason"]),
                candidates=[
                    AacMatch(**c) for c in decision["candidates"][:_SHORTLIST]
                ],
            )
        ]
    )
