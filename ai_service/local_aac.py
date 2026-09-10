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


# 맥락 가중치(job/asset_type)는 '동점을 깨는' 크기여야 한다.
# 과거에는 job 일치 +0.16 / 불일치 -0.08 이었는데, 이 크기면 다른 직무에 있는 정답을
# 묻어버린다(예: 청소 맥락에서 cafe 소속인 "바닥을 빗자루로 쓸어낸다"가 순위 밖으로 밀림).
#
# 크기는 eval/run_match_eval.py로 실측해 정했다. 직무가 갈리는 경계 사례의 관련도 격차는
# 0.02 내외다("박스 뚜껑을 덮으세요"에서 CAFE_033 0.158 vs PACKAGING_047 0.137).
# 일치 보너스만으로는 이 격차를 못 넘으므로 불일치에 절반 크기의 벌점을 함께 둔다.
# 벌점을 일치 보너스보다 작게 유지하는 게 핵심 — 업종 맥락은 약한 양의 증거이고,
# 불일치는 그보다 더 약한 음의 증거다. 크게 잡으면 타 직무의 정답을 다시 묻는다.
_JOB_TIEBREAK = 0.02
_JOB_MISMATCH_PENALTY = 0.01
_ASSET_TYPE_TIEBREAK = 0.015


def _containment(q_norm: str, label_norm: str, q_tokens: set[str], a_tokens: set[str]) -> float:
    """한쪽이 다른 쪽을 포함할 때의 보정. 길이로 정규화한다.

    예전에는 포함이면 무조건 1.0을 줬는데, 그러면 한 단어짜리 도구 라벨이 문장 안에
    언급되기만 해도 만점을 받았다("행주"가 "테이블을 행주로 닦아주세요"에 포함).
    실측 결과 이 항(가중치 0.08)이 도구 카드가 동작 카드를 이기는 격차(~0.08)를
    거의 그대로 설명했다 — 즉 "테이블을 닦으세요"에 행주 사진이 붙던 원인이다.

    포함은 '언급됨'이 아니라 '거의 같은 말'일 때만 강한 증거다. 짧은 쪽이 긴 쪽을
    얼마나 덮는지의 비율로 준다.
    """
    if not q_norm or not label_norm:
        return 0.0

    q_compact = q_norm.replace(" ", "")
    label_compact = label_norm.replace(" ", "")

    if label_compact in q_compact or q_compact in label_compact:
        shorter, longer = sorted((len(label_compact), len(q_compact)))
        return shorter / longer if longer else 0.0

    # 토큰 단위 포함도 같은 이유로 비율을 따른다.
    if q_tokens and a_tokens and q_tokens <= a_tokens:
        return 0.8 * len(q_tokens) / len(a_tokens)

    return 0.0


def _relevance(asset: dict, query: str) -> float:
    """질의와 자산 텍스트의 순수 유사도. 맥락 가중치가 섞이지 않는다."""
    q_norm = _normalize(query)
    if not q_norm:
        return 0.0
    q_tokens = _tokens(query)
    q_bigrams = _bigrams(query)
    label_norm = asset["_norm"]

    token_score = _jaccard(q_tokens, asset["_tokens"])
    bigram_score = _jaccard(q_bigrams, asset["_bigrams"])
    seq_score = SequenceMatcher(None, q_norm.replace(" ", ""), label_norm.replace(" ", "")).ratio()

    containment = _containment(q_norm, label_norm, q_tokens, asset["_tokens"])

    return 0.38 * token_score + 0.34 * bigram_score + 0.20 * seq_score + 0.08 * containment


def _tiebreak(asset: dict, preferred_job: str | None, action_type: str | None) -> float:
    """관련도가 비슷한 후보들의 순서만 바꾸는 작은 보정값."""
    bonus = 0.0

    # 업종 맥락이 있으면 같은 직무를 선호하고, 다른 직무에는 그 절반의 벌점을 준다.
    if preferred_job:
        if asset.get("job") == preferred_job:
            bonus += _JOB_TIEBREAK
        else:
            bonus -= _JOB_MISMATCH_PENALTY

    # 작업 단계는 보통 도구/보조 카드보다 동작 카드가 맞다.
    if action_type and action_type != "other":
        if asset.get("asset_type") == "action":
            bonus += _ASSET_TYPE_TIEBREAK
        else:
            bonus -= _ASSET_TYPE_TIEBREAK

    return bonus


def _score_asset(asset: dict, query: str, preferred_job: str | None, action_type: str | None) -> float:
    score = _relevance(asset, query) + _tiebreak(asset, preferred_job, action_type)
    return max(0.0, min(score, 1.0))


def _dedupe(ranked: list[tuple[float, dict]]) -> list[tuple[float, dict]]:
    """같은 그림을 결과에 두 번 넣지 않는다(점수 높은 쪽만 남긴다).

    두 종류의 중복을 걷어낸다:
    - 같은 `group_id`의 시각 변형(ASSEMBLY_031_01~04). 어느 것이 나와도 같은 행동이다.
    - 같은 직무에서 라벨이 완전히 같은 자산(CAFE_009/CAFE_026 "얼음을 컵에 담는다").
      데이터셋 쪽 중복이지만, 사용자에게 같은 카드가 두 번 보이는 건 막아야 한다.

    입력은 점수 내림차순으로 정렬돼 있어야 한다.
    """
    seen_groups: set[str] = set()
    seen_labels: set[tuple[str, str]] = set()
    out: list[tuple[float, dict]] = []
    for score, asset in ranked:
        group = asset.get("group_id") or asset["id"]
        label_key = (asset.get("job", ""), asset.get("label", ""))
        if group in seen_groups or label_key in seen_labels:
            continue
        seen_groups.add(group)
        seen_labels.add(label_key)
        out.append((score, asset))
    return out


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
    for score, asset in _dedupe(ranked)[: max(1, limit)]:
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


def decide(results: list[dict]) -> dict:
    """검색 결과를 자동 채택할지 판정한다.

    절대 임계값 하나로는 정답과 오답이 갈리지 않는다. 임계값 스윕 곡선에 오답채택과
    사람확인이 동시에 낮은 구간이 없었고, 1순위 오답의 대부분은 2순위와의 점수 차
    (margin)가 0.01 이하였다 — "확신 있는 정답"이 아니라 사실상 동전 던지기였다.
    그래서 두 조건을 함께 본다:

      1) 1순위 점수가 임계값 이상인가   → 무관한 카드를 거른다
      2) 1순위와 2순위의 차가 충분한가   → 비슷한 후보 중 아무거나 고르지 않는다

    거절 사유를 구분해 돌려준다. 후보가 아예 없는 것과, 후보는 여럿인데 못 고르는 것은
    검토 화면에서 다르게 다뤄야 한다(전자는 폴백, 후자는 후보를 보여주고 사람이 선택).

    두 기본값 모두 eval/run_match_eval.py 의 스윕으로 교정했다. 스코어러를 고치면
    점수 척도가 바뀌므로 반드시 다시 교정해야 한다.

    반환: {"match": dict|None, "reason": str, "candidates": list, "margin": float}
      reason — "accepted" | "no_candidate" | "low_score" | "low_margin"
    """
    threshold = float(os.getenv("AAC_MATCH_THRESHOLD", "0.14"))
    min_margin = float(os.getenv("AAC_MATCH_MIN_MARGIN", "0.02"))

    if not results:
        return {"match": None, "reason": "no_candidate", "candidates": [], "margin": 0.0}

    best = results[0]
    # 후보가 하나뿐이면 비교 대상이 없다. 경쟁자가 없으므로 여유는 최대로 본다.
    margin = best["score"] - results[1]["score"] if len(results) > 1 else best["score"]

    if best["score"] < threshold:
        return {"match": None, "reason": "low_score", "candidates": results, "margin": margin}
    if margin < min_margin:
        return {"match": None, "reason": "low_margin", "candidates": results, "margin": margin}
    return {"match": best, "reason": "accepted", "candidates": results, "margin": margin}


def search_for_step(keywords: list[str], context: dict | None = None) -> dict | None:
    """단계에 붙일 AAC 자산을 고른다. 확신이 없으면 None(폴백)."""
    return search_for_step_detailed(keywords, context)["match"]


def search_for_step_detailed(keywords: list[str], context: dict | None = None) -> dict:
    """search_for_step에 판정 근거를 더한 형태. decide()의 반환을 그대로 준다."""
    ctx = dict(context or {})
    sentence = str(ctx.get("sentence") or "").strip()
    query_parts = [sentence] + [str(k).strip() for k in keywords if str(k).strip()]
    query = " ".join(part for part in query_parts if part)
    return decide(search_assets(query, ctx, limit=5))
