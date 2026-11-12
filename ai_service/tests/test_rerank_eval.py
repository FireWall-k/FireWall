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
    user = aac_rerank.build_user_prompt(ctx["sentence"], ctx["business_type"], top, kw)
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
    assert row["llm"] == {"choice": 2, "confident": True, "policy": "top1", "applied": "top1", "query": True}


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


def _stats():
    return {"cache_hit": 0, "missing": 0, "live": 0, "usd": 0.0, "budget_stop": 0}


_BODY = {"model": "gpt-4o-mini", "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]}


def _never(*a, **kw):
    raise AssertionError("실제 호출이 일어나면 안 된다")


def test_live_requires_ledger_and_positive_cap(tmp_path):
    for ledger, cap in ((None, 0.85), (tmp_path / "u.jsonl", 0.0), (None, 0.0)):
        try:
            R.make_post(_never, tmp_path, True, ledger, cap, _stats())
        except ValueError:
            continue
        raise AssertionError(f"장부 {ledger}, 상한 {cap}이면 거절해야 한다")


def test_main_live_without_ledger_exits_before_any_call(tmp_path, monkeypatch):
    _isolate(monkeypatch)
    try:
        R.main(["--dataset", "dev", "--live", "--cap", "0.85", "--cache-dir", str(tmp_path)])
    except SystemExit as e:
        assert "--ledger" in str(e)
    else:
        raise AssertionError("SystemExit이 나야 한다")


def test_live_refuses_when_ledger_reaches_cap(tmp_path):
    ledger = tmp_path / "usage.jsonl"
    ledger.write_text(json.dumps({"usd": 0.5}) + "\n", encoding="utf-8")
    stats = _stats()
    post = R.make_post(_never, tmp_path, True, ledger, 0.5, stats)
    try:
        post("url", json=_BODY)
    except R.Budget:
        pass
    else:
        raise AssertionError("Budget 예외가 나야 한다")
    assert stats["budget_stop"] == 1


def test_unknown_model_is_refused_before_calling(tmp_path):
    stats = _stats()
    post = R.make_post(_never, tmp_path, True, tmp_path / "usage.jsonl", 0.85, stats)
    try:
        post("url", json={**_BODY, "model": "gpt-9-unknown"})
    except R.Budget:
        pass
    else:
        raise AssertionError("Budget 예외가 나야 한다")
    assert stats["budget_stop"] == 1 and not (tmp_path / "usage.jsonl").exists()


def test_live_call_is_always_recorded_in_ledger(tmp_path):
    """응답 모델 이름이 단가표에 없어도(이미 돈은 나갔다) 요청 모델 단가로 장부에 남긴다."""
    ledger = tmp_path / "usage.jsonl"

    class _Resp:
        status_code = 200

        def json(self):
            return {"model": "renamed-model", "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
                    "choices": [{"message": {"content": '{"choice": 1, "confident": true}'}}]}

        def raise_for_status(self):
            return None

    calls = []
    stats = _stats()
    post = R.make_post(lambda *a, **kw: calls.append(1) or _Resp(), tmp_path / "cache", True, ledger, 0.85, stats)
    post("url", json=_BODY)
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(calls) == 1 and len(rows) == 1
    assert abs(rows[0]["usd"] - (1000 * 0.15 + 100 * 0.60) / 1e6) < 1e-12
    # 두 번째는 디스크 캐시에서 — 다시 부르지 않는다
    post("url", json=_BODY)
    assert len(calls) == 1 and stats["cache_hit"] == 1


def test_rejects_dataset_without_answers(tmp_path, monkeypatch):
    """정답(accept)이 없는 다른 모양의 파일을 넣으면 0.000을 조용히 내지 않고 멈춘다."""
    import pytest
    _isolate(monkeypatch)
    data = tmp_path / "wrapped.json"
    data.write_text(json.dumps({"cases": [{"id": "x1", "sentence": "문장", "gap": False, "steps": []}]},
                               ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        R.main(["--dataset", str(data), "--cache-dir", str(tmp_path / "c")])
    assert "accept" in str(e.value)


def test_check_cases_accepts_answer_or_gap():
    assert R.check_cases([_CASE, {"id": "g", "sentence": "s", "gap": True}]) == []
    assert R.check_cases([]) == ["문항(cases)이 없음"]
    assert len(R.check_cases([{"id": "a", "sentence": "s"}, {"sentence": "s", "accept": ["A"]}])) == 2
