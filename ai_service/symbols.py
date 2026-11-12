"""
Map task-step keywords to project-owned local AAC assets.
"""
from __future__ import annotations

import aac_rerank
from local_aac import search_for_step_detailed
from schemas import AacMatch, MapSymbolsResult, Symbol

# 사람에게 보여줄 후보 개수. recall@3이 0.988이라 3개면 거의 항상 정답이 들어 있다
# (eval/run_match_eval.py 참고). 더 늘리면 고르는 부담만 커진다.
_SHORTLIST = 3


def map_symbols(keywords: list[str], context: dict) -> MapSymbolsResult:
    # (2b-1) 백엔드의 후보 조회(편집기 모든 단계 후보·symbol-candidates)는 context.rerank=false를 넘긴다 — 사업주가
    # 편집기를 열 때마다 단계마다 유료 GPT 재순위를 부르지 않게(contract §3.3). 이 값은 검색 맥락이 아니라 빼고 넘긴다.
    context = dict(context or {})
    rerank_allowed = context.pop("rerank", None) is not False
    # available()은 한 번만 본다 — 검색 limit을 고른 뒤 쉬는 시간이 끝나 기본 개수 후보로 GPT를 부르지 않게.
    rerank_on = rerank_allowed and aac_rerank.available()
    if rerank_on:
        # GPT에 규칙 상위 10장을 보여 준다. limit은 후보 길이만 바꾸고 판정은 그대로다(1,006건 대조에서
        # limit 5/10/20 판정이 모두 같았다). 꺼져 있으면 예전과 똑같이 기본 limit으로 부른다.
        decision = search_for_step_detailed(keywords, context, limit=aac_rerank.TOP_N)
    else:
        decision = search_for_step_detailed(keywords, context)
    decision = aac_rerank.rerank(decision, keywords=keywords, context=context, enabled=rerank_on)
    match = decision["match"]
    decided_by = decision.get("decided_by", "rule")

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
                    decided_by=decided_by,
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
                # llm_disagree(규칙은 골랐지만 GPT가 확인해 주지 않음)도 같은 이유로 low_margin이다.
                reason=("low_margin" if decision["reason"] in ("frame_mismatch", "llm_disagree")
                        else decision["reason"]),
                decided_by=decided_by,
                candidates=[
                    AacMatch(**c) for c in decision["candidates"][:_SHORTLIST]
                ],
            )
        ]
    )
