from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")

_JOB_ALIASES: dict[str, tuple[str, ...]] = {
    "assembly": ("assembly", "조립", "제조", "부품", "생산"),
    "cafe": ("cafe", "카페", "커피", "음료", "바리스타"),
    "cleaning": ("cleaning", "청소", "세탁", "세차", "환경미화"),
    "packaging": ("packaging", "포장", "패킹", "박스포장"),
    "retail": ("retail", "마트", "매장", "소매", "진열", "피킹", "계산", "배송"),
}

_PARTICLES = (
    "으로", "에서", "에게", "까지", "부터", "처럼", "보다", "하고", "이며", "이며",
    "을", "를", "이", "가", "은", "는", "에", "의", "와", "과", "도", "만", "로",
)


def _default_data_dir() -> Path:
    # ai_service/local_aac.py -> repository root/data/aac for local execution.
    return Path(__file__).resolve().parent.parent / "data" / "aac"


def get_data_dir() -> Path:
    return Path(os.getenv("AAC_DATA_DIR", str(_default_data_dir()))).resolve()


def _normalize(text: str) -> str:
    return " ".join(_TOKEN_RE.findall(text.lower()))


def _stem_token(token: str) -> str:
    value = token
    for p in _PARTICLES:
        if len(value) > len(p) + 1 and value.endswith(p):
            value = value[: -len(p)]
            break
    # Common polite/statement endings from task sentences.
    for ending in ("하세요", "해주세요", "합니다", "하십시오", "한다", "해요", "세요", "니다", "다"):
        if len(value) > len(ending) + 1 and value.endswith(ending):
            value = value[: -len(ending)]
            break
    return value


def _tokens(text: str) -> set[str]:
    return {_stem_token(t) for t in _TOKEN_RE.findall(text.lower()) if len(_stem_token(t)) >= 2}


def _bigrams(text: str) -> set[str]:
    compact = _normalize(text).replace(" ", "")
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def infer_job(context: dict | None = None, query: str = "") -> str | None:
    ctx = context or {}
    haystack = " ".join(
        str(ctx.get(key, "")) for key in ("business_type", "work_environment", "job")
    ) + " " + query
    norm = _normalize(haystack)
    scores: list[tuple[int, str]] = []
    for job, aliases in _JOB_ALIASES.items():
        count = sum(1 for alias in aliases if alias.lower() in norm)
        if count:
            scores.append((count, job))
    return max(scores)[1] if scores else None


@lru_cache(maxsize=1)
def load_assets() -> list[dict]:
    path = get_data_dir() / "aac_assets.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assets = payload.get("assets", [])
    for asset in assets:
        label = str(asset.get("label", ""))
        extra = " ".join(asset.get("keywords", []) + asset.get("aliases", []))
        searchable = f"{label} {extra}".strip()
        asset["_norm"] = _normalize(searchable)
        asset["_tokens"] = _tokens(searchable)
        asset["_bigrams"] = _bigrams(searchable)
    return assets


def _score_asset(asset: dict, query: str, preferred_job: str | None, action_type: str | None) -> float:
    q_norm = _normalize(query)
    if not q_norm:
        return 0.0
    q_tokens = _tokens(query)
    q_bigrams = _bigrams(query)
    label_norm = asset["_norm"]

    token_score = _jaccard(q_tokens, asset["_tokens"])
    bigram_score = _jaccard(q_bigrams, asset["_bigrams"])
    seq_score = SequenceMatcher(None, q_norm.replace(" ", ""), label_norm.replace(" ", "")).ratio()

    containment = 0.0
    if label_norm and (label_norm in q_norm or q_norm in label_norm):
        containment = 1.0
    elif q_tokens and q_tokens <= asset["_tokens"]:
        containment = 0.8

    score = 0.38 * token_score + 0.34 * bigram_score + 0.20 * seq_score + 0.08 * containment

    # If the employer provided an industry/context, prefer that job family strongly.
    if preferred_job:
        if asset.get("job") == preferred_job:
            score += 0.16
        else:
            score -= 0.08

    # Most generated task steps should prefer action cards over standalone tool/support cards.
    if action_type and action_type != "other":
        if asset.get("asset_type") == "action":
            score += 0.04
        else:
            score -= 0.04

    return max(0.0, min(score, 1.0))


def search_assets(query: str, context: dict | None = None, limit: int = 5) -> list[dict]:
    ctx = context or {}
    preferred_job = infer_job(ctx, query)
    action_type = str(ctx.get("action_type") or "") or None

    ranked: list[tuple[float, dict]] = []
    for asset in load_assets():
        score = _score_asset(asset, query, preferred_job, action_type)
        if score <= 0:
            continue
        ranked.append((score, asset))
    ranked.sort(key=lambda item: (-item[0], item[1].get("id", "")))

    results: list[dict] = []
    for score, asset in ranked[: max(1, limit)]:
        results.append({
            "asset_id": asset["id"],
            "group_id": asset.get("group_id") or asset["id"],
            "job": asset.get("job", ""),
            "asset_type": asset.get("asset_type", "action"),
            "label": asset.get("label", ""),
            "image_url": f"/api/aac/images/{asset['image']}",
            "score": round(score, 4),
        })
    return results


def search_for_step(keywords: list[str], context: dict | None = None) -> dict | None:
    ctx = dict(context or {})
    sentence = str(ctx.get("sentence") or "").strip()
    query_parts = [sentence] + [str(k).strip() for k in keywords if str(k).strip()]
    query = " ".join(part for part in query_parts if part)
    results = search_assets(query, ctx, limit=5)
    if not results:
        return None

    # Conservative threshold: under this, show fallback rather than an unrelated AAC card.
    best = results[0]
    threshold = float(os.getenv("AAC_MATCH_THRESHOLD", "0.28"))
    return best if best["score"] >= threshold else None
