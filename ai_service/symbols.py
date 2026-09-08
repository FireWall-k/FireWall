"""
Map task-step keywords to project-owned local AAC assets.
"""
from __future__ import annotations

from local_aac import search_for_step
from schemas import MapSymbolsResult, Symbol


def map_symbols(keywords: list[str], context: dict) -> MapSymbolsResult:
    match = search_for_step(keywords, context)

    query_label = (
        " / ".join(keywords)
        if keywords
        else str(context.get("sentence") or "")
    )

    if not match:
        return MapSymbolsResult(
            symbols=[
                Symbol(
                    keyword=query_label,
                    image_url=None,
                    source="fallback",
                    confidence=0.0,
                    needs_fallback=True,
                )
            ]
        )

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
            )
        ]
    )