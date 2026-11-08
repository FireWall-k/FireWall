"""eval/run_rerank_eval.py — 디스크 캐시로 채점하고, 캐시에 없으면 실제로 부르지 않는다."""
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aac_rerank  # noqa: E402
import llm  # noqa: E402
from eval import run_rerank_eval as R  # noqa: E402
from eval.gate_paths import _case_inputs  # noqa: E402
from local_aac import search_for_step_detailed  # noqa: E402

_CASE = {"id": "t1", "sentence": "상품을 선반에 놓으세요", "symbol_query": ["상품", "선반", "놓기"],
         "action_type": "move", "accept": ["RETAIL_029"], "gap": False, "context": {"business_type": "대형마트"}}


def _isolate(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("실제 HTTP 호출이 일어나면 안 된다")

    monkeypatch.setattr(llm, "_http", types.SimpleNamespace(post=boom))
    monkeypatch.setattr(llm, "OPENAI_API_KEY", "")
    for name in ("AAC_LLM_RERANK", "AAC_LLM_RERANK_COOLDOWN", "AAC_LLM_RERANK_CACHE", "AAC_LLM_RERANK_POLICY"):
        monkeypatch.setenv(name, os.environ.get(name, ""))
    aac_rerank.reset_state()


def _seed(cache_dir, case, choice, confident):
    kw, ctx = _case_inputs(case, "full")
    top = search_for_step_detailed(kw, ctx, limit=aac_rerank.TOP_N)["candidates"][:aac_rerank.TOP_N]
    user = aac_rerank.build_user_prompt(ctx["sentence"], ctx["business_type"], top)
    key = R.cache_key(llm.OPENAI_MODEL, aac_rerank.RERANK_SYSTEM, user)
    body = {"choices": [{"message": {"content": json.dumps({"choice": choice, "confident": confident})}}]}
    (cache_dir / f"{key}.json").write_text(json.dumps(body), encoding="utf-8")


def test_scores_from_cache(tmp_path, monkeypatch, capsys):
    _isolate(monkeypatch)
    cache = tmp_path / "cache"
    cache.mkdir()
    _seed(cache, _CASE, 2, True)  # GPT가 규칙 1순위가 아닌 카드를 고름 → 규칙 채택이 취소된다
    data = tmp_path / "set.json"
    data.write_text(json.dumps({"cases": [_CASE]}, ensure_ascii=False), encoding="utf-8")
    out_json = tmp_path / "rows.json"
    R.main(["--dataset", str(data), "--cache-dir", str(cache), "--policy", "top1", "--json", str(out_json)])
    text = capsys.readouterr().out
    assert "GPT 응답: 캐시 1, 응답 없음(규칙으로 셈) 0, 실제 호출 0" in text
    row = json.loads(out_json.read_text(encoding="utf-8"))[0]
    assert row["rule"]["accepted"] and row["rule"]["correct"]
    assert not row["top1"]["accepted"]
    assert row["top1"]["top3"]  # 정답(규칙 1순위)은 후보 3장 안에 남는다
    assert row["llm"] == {"choice": 2, "confident": True, "policy": "top1"}


def test_missing_cache_counts_as_rule_without_calling(tmp_path, monkeypatch, capsys):
    _isolate(monkeypatch)
    data = tmp_path / "set.json"
    data.write_text(json.dumps({"cases": [_CASE]}, ensure_ascii=False), encoding="utf-8")
    R.main(["--dataset", str(data), "--cache-dir", str(tmp_path / "empty"), "--policy", "top1"])
    text = capsys.readouterr().out
    assert "응답 없음(규칙으로 셈) 1" in text
    lines = [line for line in text.splitlines() if line.startswith(("규칙만", "규칙+GPT"))]
    rule, gpt = (line.split() for line in lines)
    assert rule[-4:] == gpt[-4:]  # 채택·맞음·틀림·정밀도가 규칙만과 같다


def test_live_refuses_without_cap(tmp_path):
    stats = {"cache_hit": 0, "missing": 0, "live": 0, "usd": 0.0, "budget_stop": 0}

    def real(*a, **kw):
        raise AssertionError("상한 0이면 부르지 않는다")

    post = R.make_post(real, tmp_path, True, None, 0.0, stats)
    body = {"model": "gpt-4o-mini", "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]}
    try:
        post("url", json=body)
    except R.Budget:
        pass
    else:
        raise AssertionError("Budget 예외가 나야 한다")
    assert stats["budget_stop"] == 1
