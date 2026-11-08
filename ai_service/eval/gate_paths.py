"""대상 게이트·직무 규칙의 각 경로가 실제 데이터에서 몇 건에 쓰이고 판정을 몇 건 바꾸는지 잰다.

2026-11-08 수정(README "오답 채택 원인 4가지 수정")의 규칙 가운데 일부는 개발 데이터에서 바꾼
케이스가 없거나 적다. 새 데이터(블라인드2)를 채점할 때 이 스크립트로 경로마다
  - fires:   그 경로가 쓰인 케이스 수(문장에서 그 경로로 대상을 잡았거나, 1순위 그림에 그 면제가 걸렸다)
  - changed: 그 경로를 끈 것과 비교해 판정(채택 여부·1순위)이 달라진 케이스 수
  - ΔWA/ΔCA: 그 경로가 있을 때 − 끈 때의 오답 채택·정답 자동 채택 건수
를 보고, 근거 없이 복잡도만 더하는 경로를 걸러낸다.

실행(임베딩 off, 네트워크 없음):
    cd ai_service
    python -m eval.gate_paths --dataset dev --query-mode sentence
    python -m eval.gate_paths --dataset <경로> --query-mode full --json out.json

경로:
    topic          C2 은/는 주제어를 대상으로(을/를 목적어가 없을 때)
    position_head  C1 위치 명사('위를') 앞 어절을 대상으로. 끄면 예전처럼 '위'를 대상으로 본다
    vocab_head     C1 중 분석기가 동사로 읽는 앞 어절('매대')을 그림 frame 명사로 인정하는 부분
    generic_scope  C3 일반 명사 면제를 같은 물건 묶음 직무(가게·만드는 일)까지 넓힌 부분
    generic_job    C3 일반 명사 면제를 직무로 제한한 것 전체. 끄면 예전처럼 늘 면제
    antonym_own    C5a 문장에 그림 동사가 있으면 반대말 벌점을 걸지 않는 부분(fires: 문장에 반대말 쌍이 함께 있다)
    c7_aliases     C7 업종명 별칭 9개(객실·고깃집·분식·국밥·슈퍼·할인점·드럭스토어·옷가게·의류매장)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import local_aac as L  # noqa: E402
import taxonomy  # noqa: E402
from eval.run_match_eval import (  # noqa: E402
    _case_inputs, _embedding_mode, _expand_accept, _group_index, resolve_dataset,
)

C7_ALIASES = {
    "cleaning": ("객실",), "retail": ("슈퍼", "할인점", "드럭스토어"),
    "serving": ("고깃집", "분식", "국밥"), "display": ("옷가게", "의류매장"),
}


@contextmanager
def _patched(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


@contextmanager
def _without_c7():
    saved = {job: taxonomy.JOB_ALIASES[job] for job in C7_ALIASES}
    try:
        for job, drop in C7_ALIASES.items():
            taxonomy.JOB_ALIASES[job] = tuple(a for a in saved[job] if a not in drop)
        yield
    finally:
        taxonomy.JOB_ALIASES.update(saved)


def _raw_query_objects(sentence: str) -> set[str]:
    return {m.group(1) for m in L._QUERY_OBJECT_RE.finditer(sentence or "")}


def _position_heads(sentence: str) -> set[str]:
    """위치 명사 경로로 잡힌 대상(을/를이 직접 붙은 대상은 뺀다)."""
    return L._query_objects(sentence) - _raw_query_objects(sentence)


def _old_antonym_penalty(asset: dict, query_lemmas: set[str]) -> float:
    verb = (asset.get("_frame") or {}).get("verb")
    if not verb or not query_lemmas:
        return 1.0
    for group in L._VERB_ANTONYMS:
        if verb in group and (query_lemmas & group) - {verb}:
            return L._VERB_ANTONYM_PENALTY
    return 1.0


def _vocab_without_verb_reads():
    full = L._asset_noun_vocab()
    reduced = frozenset(w for w in full if not L._is_verb_word(w))
    return lambda: reduced


def _ablation(path: str):
    if path == "topic":
        return _patched(L, "_query_topics", lambda sentence: set())
    if path == "position_head":
        return _patched(L, "_query_objects", _raw_query_objects)
    if path == "vocab_head":
        return _patched(L, "_asset_noun_vocab", _vocab_without_verb_reads())
    if path == "generic_scope":
        return _patched(L, "_GENERIC_OBJECT_SCOPE", {})
    if path == "generic_job":
        return _patched(L, "_generic_covers", lambda word, asset_job, job: True)
    if path == "antonym_own":
        return _patched(L, "_verb_antonym_penalty", _old_antonym_penalty)
    if path == "c7_aliases":
        return _without_c7()
    raise ValueError(path)


PATHS = ("topic", "position_head", "vocab_head", "generic_scope", "generic_job",
         "antonym_own", "c7_aliases")


def _fires(path: str, case: dict, keywords: list[str], ctx: dict, decision: dict) -> bool:
    sentence = case["sentence"]
    if path == "topic":
        return not L._query_objects(sentence) and bool(L._query_topics(sentence))
    if path == "position_head":
        return bool(_position_heads(sentence))
    if path == "vocab_head":
        return any(L._is_verb_word(h) for h in _position_heads(sentence))
    if path in ("generic_scope", "generic_job"):
        cands = decision["candidates"]
        if not cands:
            return False
        asset = L._assets_by_id().get(cands[0]["asset_id"]) or {}
        obj = L._normalize((asset.get("_frame") or {}).get("object") or "").replace(" ", "")
        if obj not in L._GENERIC_OBJECTS:
            return False
        if path == "generic_job":
            return True
        job = L._explicit_job(ctx) or L.infer_job(ctx) or L.infer_job(ctx, L.step_query(keywords, ctx))
        return bool(job) and asset.get("job") != job and L._generic_covers(obj, asset.get("job"), job)
    if path == "antonym_own":
        # 문장에 반대말 쌍의 두 동사가 함께 있을 때만 이 경로가 벌점을 거른다.
        lemmas = L._QueryFeatures(L.step_query(keywords, ctx)).lemmas
        return any(len(lemmas & group) >= 2 for group in L._VERB_ANTONYMS)
    if path == "c7_aliases":
        hay = " ".join(str(ctx.get(k, "")) for k in ("business_type", "work_environment", "raw_input"))
        return any(taxonomy.alias_in(a, hay.lower()) for aliases in C7_ALIASES.values() for a in aliases)
    raise ValueError(path)


def _decide_all(cases, query_mode, accepts):
    out = {}
    for case in cases:
        keywords, ctx = _case_inputs(case, query_mode)
        d = L.search_for_step_detailed(keywords, ctx, limit=20)
        chosen = d["match"]["asset_id"] if d["match"] else None
        top = d["candidates"][0]["asset_id"] if d["candidates"] else None
        acc = accepts[case["id"]]
        out[case["id"]] = {
            "decision": d, "keywords": keywords, "ctx": ctx, "chosen": chosen, "top": top,
            "wa": chosen is not None and (case.get("gap") or chosen not in acc),
            "ca": chosen is not None and not case.get("gap") and chosen in acc,
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="대상 게이트·직무 규칙 경로별 사용·영향 집계")
    ap.add_argument("--dataset", default="dev")
    ap.add_argument("--query-mode", choices=["full", "sentence"], default="full")
    ap.add_argument("--paths", default=",".join(PATHS))
    ap.add_argument("--json")
    args = ap.parse_args()

    data = json.loads(resolve_dataset(args.dataset).read_text(encoding="utf-8"))
    cases = data["cases"]
    id_to_group, group_to_ids = _group_index()
    accepts = {c["id"]: _expand_accept(c.get("accept", []), id_to_group, group_to_ids) for c in cases}

    report = {"dataset": str(args.dataset), "query_mode": args.query_mode, "paths": {}}
    with _embedding_mode("off", None):
        full = _decide_all(cases, args.query_mode, accepts)
        for path in args.paths.split(","):
            with _ablation(path):
                off = _decide_all(cases, args.query_mode, accepts)
            fires = [c["id"] for c in cases
                     if _fires(path, c, full[c["id"]]["keywords"], full[c["id"]]["ctx"],
                               full[c["id"]]["decision"])]
            changed = [cid for cid in full
                       if (full[cid]["chosen"], full[cid]["top"]) != (off[cid]["chosen"], off[cid]["top"])]
            report["paths"][path] = {
                "fires": len(fires),
                "changed": changed,
                "delta_wrong_accept": sum(full[c]["wa"] for c in full) - sum(off[c]["wa"] for c in off),
                "delta_correct_auto": sum(full[c]["ca"] for c in full) - sum(off[c]["ca"] for c in off),
            }
    for path, r in report["paths"].items():
        print(f"{path:14s} fires={r['fires']:3d} changed={len(r['changed']):2d} "
              f"ΔWA={r['delta_wrong_accept']:+d} ΔCA={r['delta_correct_auto']:+d} {' '.join(r['changed'])}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
