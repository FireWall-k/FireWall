"""규칙만 vs 규칙 + GPT 재순위(aac_rerank.py) 채점.

운영 경로를 그대로 쓴다: search_for_step_detailed(limit=10) → aac_rerank.rerank(). GPT 응답은 디스크
캐시(--cache-dir)에서 읽는다. 캐시 키는 sha256(model + NUL + system + NUL + user)이고 파일 하나가
Chat Completions 응답 하나다. 그래서 같은 프롬프트·후보로 다시 채점하면 돈이 들지 않는다.

  python -m eval.run_rerank_eval --dataset dev
  python -m eval.run_rerank_eval --dataset path/to/set.json --cache-dir D:/rerank_cache
  python -m eval.run_rerank_eval --dataset dev --live --ledger usage.jsonl --cap 0.85   # 캐시에 없는 것만 실제 호출

기본은 오프라인이다. 캐시에 없는 문항은 GPT 없이 규칙 판정으로 센다(운영의 '키 없음·실패'와 같다)
— 그런 문항 수를 'GPT 응답 없음'으로 따로 보여 준다. --live는 키(OPENAI_API_KEY_FILE)가 필요하고,
--ledger 장부와 --cap(0보다 큰 USD)이 반드시 함께 있어야 한다. 호출마다 비용(gpt-4o-mini 공개 단가, 캐시
할인 무시 = 보수적)을 장부에 남기고, 장부 합계가 --cap에 닿으면 더 부르지 않는다. 단가를 모르는 모델은
부르기 전에 거절한다(부른 뒤에 알면 이미 돈이 나갔다).

지표(정답 있는 문항 기준; gap 문항은 자동 채택하면 틀림으로만 센다):
  top1/top3   사업주에게 보여 주는 순서의 1번째/상위 3장 안에 정답이 있는 비율
  pick        GPT가 10장 중 고른 카드가 정답인 비율(GPT 경로만)
  accepted / correct / wrong / precision   자동 채택 수, 맞은 채택, 틀린 채택, 정밀도
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import aac_rerank  # noqa: E402
import llm  # noqa: E402
from eval.gate_paths import _case_inputs  # noqa: E402
from eval.run_match_eval import _expand_accept, _group_index  # noqa: E402
from local_aac import search_for_step_detailed  # noqa: E402

DATASETS = {"golden": HERE / "match_dataset.json", "dev": HERE / "dev_set.json"}
PRICES = {"gpt-4o-mini": (0.15, 0.60)}  # USD / 1M 토큰(입력, 출력)


class Budget(Exception):
    pass


def cache_key(model: str, system: str, user: str) -> str:
    return hashlib.sha256((model + "\x00" + system + "\x00" + user).encode("utf-8")).hexdigest()


def ledger_total(path: Path | None) -> float:
    if path is None or not path.exists():
        return 0.0
    return sum(json.loads(line)["usd"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


class _Cached:
    """캐시된 응답을 httpx.Response처럼 보이게 한다(chat_json이 쓰는 두 메서드만)."""

    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._data


def _price(model: str) -> tuple[float, float] | None:
    return next((v for k, v in PRICES.items() if model.startswith(k)), None)


def make_post(real_post, cache_dir: Path, live: bool, ledger: Path | None, cap: float, stats: dict):
    if live and (ledger is None or cap <= 0):
        raise ValueError("--live에는 --ledger 장부와 0보다 큰 --cap이 필요합니다")

    def post(url, *args, **kwargs):
        body = kwargs.get("json") or {}
        msgs = body.get("messages") or []
        system = next((m["content"] for m in msgs if m.get("role") == "system"), "")
        user = next((m["content"] for m in msgs if m.get("role") == "user"), "")
        f = cache_dir / f"{cache_key(str(body.get('model', '')), system, user)}.json"
        if f.exists():
            stats["cache_hit"] += 1
            return _Cached(json.loads(f.read_text(encoding="utf-8")))
        if not live:
            stats["missing"] += 1
            raise LookupError("캐시에 없음(오프라인)")
        req_model = str(body.get("model") or "")
        price = _price(req_model)
        if price is None:
            stats["budget_stop"] += 1
            raise Budget(f"단가를 모르는 모델이라 부르지 않음: {req_model}")
        if ledger_total(ledger) >= cap:
            stats["budget_stop"] += 1
            raise Budget(f"장부 합계가 상한 ${cap}에 닿음")
        resp = real_post(url, *args, **kwargs)
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        usage = data.get("usage") or {}
        model = str(data.get("model") or req_model)
        # 응답 모델 이름이 달라도(예: 날짜 붙은 이름) 요청 모델 단가로 반드시 장부에 남긴다.
        price = _price(model) or price
        usd = usage.get("prompt_tokens", 0) / 1e6 * price[0] + usage.get("completion_tokens", 0) / 1e6 * price[1]
        stats["live"] += 1
        stats["usd"] += usd
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": time.time(), "model": model, "in": usage.get("prompt_tokens", 0),
                                 "out": usage.get("completion_tokens", 0), "usd": usd,
                                 "status": resp.status_code, "src": "run_rerank_eval"}) + "\n")
        resp.raise_for_status()
        cache_dir.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return resp

    return post


def _score(shown: list[str], chosen: str | None, accept: set[str], gap: bool) -> dict:
    return {"top1": bool(shown) and shown[0] in accept, "top3": any(a in accept for a in shown[:3]),
            "accepted": chosen is not None, "wrong": chosen is not None and (gap or chosen not in accept),
            "correct": chosen is not None and not gap and chosen in accept}


def summarize(rows: list[dict], key: str) -> dict:
    normal = [r for r in rows if not r["gap"]]
    acc = sum(r[key]["accepted"] for r in rows)
    out = {"n": len(rows), "normal": len(normal),
           "top1": round(sum(r[key]["top1"] for r in normal) / max(1, len(normal)), 3),
           "top3": round(sum(r[key]["top3"] for r in normal) / max(1, len(normal)), 3),
           "accepted": acc, "correct": sum(r[key]["correct"] for r in rows),
           "wrong": sum(r[key]["wrong"] for r in rows)}
    out["precision"] = round(out["correct"] / max(1, acc), 3)
    if key != "rule":
        out["pick"] = round(sum(r["pick_ok"] for r in normal) / max(1, len(normal)), 3)
    return out


def run(cases: list[dict], query_mode: str, policies: list[str]) -> list[dict]:
    id2g, g2ids = _group_index()
    rows = []
    for case in cases:
        keywords, ctx = _case_inputs(case, query_mode)
        decision = search_for_step_detailed(keywords, ctx, limit=aac_rerank.TOP_N)
        gap = bool(case.get("gap"))
        accept = _expand_accept(case.get("accept", []), id2g, g2ids) if case.get("accept") else set()
        rule_shown = [c["asset_id"] for c in decision["candidates"]]
        row = {"id": case["id"], "gap": gap,
               "rule": _score(rule_shown, (decision["match"] or {}).get("asset_id"), accept, gap)}
        for pol in policies:
            os.environ["AAC_LLM_RERANK_POLICY"] = pol
            out = aac_rerank.rerank(decision, keywords=keywords, context=ctx)
            shown = [c["asset_id"] for c in out["candidates"]]
            row[pol] = _score(shown, (out["match"] or {}).get("asset_id"), accept, gap)
            row["llm"] = out.get("llm")
            top = decision["candidates"][:aac_rerank.TOP_N]
            choice = (out.get("llm") or {}).get("choice", 0)
            row["pick_ok"] = bool(choice) and top[choice - 1]["asset_id"] in accept
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", default="dev", help="golden | dev | JSON 파일 경로({'cases': [...]})")
    ap.add_argument("--mode", default="full", choices=["full", "sentence"], help="검색어 모드(run_match_eval과 같다)")
    ap.add_argument("--policy", default="both", choices=["top1", "top3", "both"])
    ap.add_argument("--cache-dir", default=os.getenv("AAC_RERANK_EVAL_CACHE", str(HERE / ".rerank_cache")))
    ap.add_argument("--live", action="store_true", help="캐시에 없는 문항을 실제로 부른다(비용 발생)")
    ap.add_argument("--ledger", default=None, help="--live 비용 장부(jsonl). 합계가 --cap에 닿으면 멈춘다")
    ap.add_argument("--cap", type=float, default=0.0, help="--live 장부 상한(USD). 0이면 부르지 않는다")
    ap.add_argument("--json", default=None, help="문항별 결과를 저장할 경로")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    path = DATASETS.get(args.dataset, Path(args.dataset))
    cases = json.loads(Path(path).read_text(encoding="utf-8"))["cases"]
    policies = ["top1", "top3"] if args.policy == "both" else [args.policy]

    if args.live and (not args.ledger or args.cap <= 0):
        raise SystemExit("--live에는 --ledger 장부와 0보다 큰 --cap이 함께 필요합니다(상한 없는 실제 호출 금지).")
    if args.live and not llm.llm_available():
        raise SystemExit("--live에는 키(OPENAI_API_KEY_FILE)가 필요합니다.")
    if not llm.llm_available():
        llm.OPENAI_API_KEY = "offline-cache-only"  # 오프라인 채점: 캐시에 없으면 실제 호출 없이 실패한다
    os.environ["AAC_LLM_RERANK"] = "auto"
    os.environ["AAC_LLM_RERANK_COOLDOWN"] = "0"  # 한 문항 실패가 다음 문항을 건너뛰게 하지 않는다
    os.environ["AAC_LLM_RERANK_CACHE"] = "0"  # 정책마다 같은 응답을 디스크 캐시에서 다시 읽는다
    stats = {"cache_hit": 0, "missing": 0, "live": 0, "usd": 0.0, "budget_stop": 0}
    ledger = Path(args.ledger) if args.ledger else None
    llm._http.post = make_post(llm._http.post, Path(args.cache_dir), args.live, ledger, args.cap, stats)
    aac_rerank.reset_state()

    rows = run(cases, args.mode, policies)
    print(f"데이터셋 {path} ({len(cases)}문항, 검색어 {args.mode}), 모델 {llm.OPENAI_MODEL}")
    header = f"{'경로':<14}{'top1':>7}{'top3':>7}{'pick':>7}{'채택':>6}{'맞음':>6}{'틀림':>6}{'정밀도':>8}"
    print(header)
    for key, name in [("rule", "규칙만"), *[(p, f"규칙+GPT {p}") for p in policies]]:
        s = summarize(rows, key)
        pick = f"{s['pick']:.3f}" if "pick" in s else "-"
        print(f"{name:<14}{s['top1']:>7.3f}{s['top3']:>7.3f}{pick:>7}{s['accepted']:>6}{s['correct']:>6}"
              f"{s['wrong']:>6}{s['precision']:>8.3f}")
    per_policy = max(1, len(policies))
    print(f"GPT 응답: 캐시 {stats['cache_hit'] // per_policy}, 응답 없음(규칙으로 셈) {stats['missing'] // per_policy}, "
          f"실제 호출 {stats['live']} (${stats['usd']:.4f})" + (", 상한으로 멈춤" if stats["budget_stop"] else ""))
    if ledger is not None:
        print(f"장부 합계 ${ledger_total(ledger):.4f}")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
