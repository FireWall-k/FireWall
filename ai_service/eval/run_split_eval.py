"""규칙 분해기 단계 나누기 평가 — 자동 분할의 정밀도, 나누기 제안의 범위, 나뉜 단계의 그림 정밀도.

LLM 없이 도는 규칙 분해 경로(decompose.plan_steps)를 잰다. GPT를 쓰지 않는 지금은 이 경로가 사용자가
실제로 받는 분해다. 설계는 step_split 모듈 설명 — 확실한 꼴만 자동으로 나누고 나머지는 제안한다.

실행:
    cd ai_service
    python -m eval.run_split_eval --gold <gold.json>              # 표 출력
    python -m eval.run_split_eval --gold <gold.json> --json out.json
    python -m eval.run_split_eval --gold <gold.json> --verbose    # 자동 분할 문장·제안·오답 그림 목록

정답 파일: [{uid, sentence, job, steps: [{text, gap, accept: [asset_id…]}]}]
    gap=false  그림이 있는 단계(accept에 정답 그림)
    gap=true   맞는 그림이 없는 단계(무엇을 자동 채택하든 오답)
    gap=null   그림 단계가 아닌 것(채점에서 뺀다)

보고 항목
(1) 자동 분할 — 새 분할기가 legacy(c64ffc3: 문장부호·순서 접속어·'-고,' 쉼표)보다 더 나눈 문장이 '자동 분할'이다.
    정밀도 = 자동 분할 문장 중 단계 수가 정답과 같은 비율. 재현율 = 정답이 여러 단계인 문장 중 자동 분할로 단계 수를
    맞춘 비율. 자동 분할로 만든 문장 전체를 함께 내 사람이 문법을 검토한다(--verbose).
(2) 위험 꼴 묶음(eval/split_probes.json, 사람 라벨) — 부정·사고/실수·남이 하는 일·꾸밈받는 대상·나열·조건·
    보조 용언·방법·사건 꼴 문장. 갈래별 자동 분할 수와 위반(나뉘면 안 되는데 나뉨 / 나뉜 문장이 기대와 다름 /
    초안이 있으면 안 되는데 있음). 부정 뒤집힘 = 사람이 'negation'으로 표시한 문장 중 자동으로 나뉜 수 — 분할기가
    쓰는 has_negation과 독립이다. 정답셋의 has_negation 기준 수는 참고로만 낸다(분할기와 같은 함수라 독립이 아니다).
(3) 제안 범위 — 정답이 여러 단계인데 자동으로 맞게 나누지 못한 문장 중 힌트(split_reason)가 붙은 비율, 초안 문장
    (split_suggestion)이 정답 단계 수와 같은 비율. 정답이 한 단계인 문장에 힌트가 붙은 수(헛힌트)도 센다.
(4) 그림 정밀도 — local_aac(문장만 질의 = 규칙 폴백 경로, 임베딩 off, 직무는 문항의 job, 원문은 raw_input).
    auto_split  자동 분할로 단계 수가 맞은 문항에서 단계마다 고른 그림을 그 단계 정답과 비교(단계 단위).
    unsplit     같은 문항의 원문을 한 번 검색해, 고른 그림이 어느 단계 정답에든 있으면 정답(문항 단위).
    pipeline    정답셋 전체에서 새 분할기 단계 vs legacy 단계의 오답 자동 채택 합계(단계 수가 다르면 정답 단계
                전체의 정답 그림 합집합으로 판정 — 관대하다). "오답 채택 총수가 늘지 않는다"를 본다.
    정밀도 = correct_auto / (correct_auto + wrong_auto).

네트워크·LLM을 쓰지 않는다. 같은 커밋·같은 정답 파일이면 결과가 같다(결정적).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["AAC_EMBEDDINGS"] = "off"  # 임베딩 off 고정(키가 있어도 API를 부르지 않는다)

import decompose  # noqa: E402
import step_split  # noqa: E402
from eval.run_match_eval import _expand_accept, _group_index  # noqa: E402
from local_aac import search_for_step_detailed  # noqa: E402

# 위험 꼴 묶음(사람 라벨 — eval/split_probes.json). 정답셋 문장이 아니고, 라벨은 분할기 코드를 쓰지 않고 붙였다.
PROBES_PATH = Path(__file__).with_name("split_probes.json")


def load_probes(path: Path = PROBES_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["probes"]


def evaluate_probes(probes: list[dict]) -> dict:
    """위험 꼴 묶음 채점. 갈래(label)별 자동 분할 수와 위반 목록.

    위반: auto=never인데 자동으로 나뉨 / 자동으로 나뉘었는데 expect와 다름 / draft=none인데 제안 초안이 있음.
    부정 뒤집힘은 사람 라벨 'negation' 문장 중 자동으로 나뉜 수다(분할기의 has_negation과 독립).
    """
    by_label: dict[str, dict] = {}
    violations = []
    for pr in probes:
        sent = pr["sentence"]
        plans = decompose.plan_steps(sent)
        steps = _new_steps(plans)
        auto = any(p.auto for p in plans)
        drafts = [p.suggestion for p in plans if p.suggestion]
        row = by_label.setdefault(pr["label"], {"n": 0, "auto": 0, "hinted": 0, "drafted": 0, "violations": 0})
        row["n"] += 1
        row["auto"] += int(auto)
        row["hinted"] += int(any(p.reason for p in plans))
        row["drafted"] += int(bool(drafts))
        why = []
        if auto and pr.get("auto") == "never":
            why.append("auto")
        if auto and pr.get("expect") is not None:
            got = [x if x.endswith(".") else x + "." for x in steps]
            if got != pr["expect"]:
                why.append("expect")
        if drafts and pr.get("draft") == "none":
            why.append("draft")
        if why:
            row["violations"] += 1
            violations.append({"label": pr["label"], "sentence": sent, "why": why, "steps": steps,
                               "drafts": drafts})
    return {
        "n": len(probes), "by_label": by_label, "violations": violations,
        "negation_auto": by_label.get("negation", {}).get("auto", 0),
        "auto_sentences": [{"label": pr["label"], "sentence": pr["sentence"],
                            "steps": _new_steps(decompose.plan_steps(pr["sentence"]))}
                           for pr in probes if any(p.auto for p in decompose.plan_steps(pr["sentence"]))],
    }


# --- c64ffc3의 분할기(비교 기준선). 운영 코드에는 남기지 않는다. -------------------------
def _split_steps_legacy(text: str) -> list[str]:
    """문장부호 → 순서 접속어 → '~고,'·'~뒤,' 쉼표 분할. c64ffc3 decompose._split_steps와 같다."""
    sentences = re.split(r"[.!?\n]+", text)
    conn_pattern = r"\s*(?:%s)[\s,]+" % "|".join(re.escape(c) for c in decompose._SEQ_CONNECTIVES)
    chunks: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        for part in re.split(conn_pattern, sentence):
            part = part.strip()
            if part:
                chunks.extend(decompose._split_sequential(part))
    return chunks


def _new_steps(plans: list[step_split.SplitOutcome]) -> list[str]:
    """운영 단계 문장(decompose._rule_steps와 같은 모양)."""
    return [decompose._plain(piece) if p.auto else piece for p in plans for piece in p.steps]


# --- 매칭 ---------------------------------------------------------------------------
_MATCH_CACHE: dict[tuple[str, str, str], dict] = {}


def match(text: str, job: str, raw: str = "") -> dict:
    """규칙 폴백 경로와 같은 질의(문장만, action_type 'other')로 그림을 고른다. raw는 운영처럼 맥락의 raw_input."""
    key = (text, job, raw)
    if key not in _MATCH_CACHE:
        ctx = {"sentence": text, "action_type": "other"}
        if job:
            ctx["job"] = job
        if raw:
            ctx["raw_input"] = raw
        d = search_for_step_detailed([], ctx)
        chosen = d["match"]["asset_id"] if d["match"] else None
        _MATCH_CACHE[key] = {"chosen": chosen, "reason": d["reason"],
                             "score": d["match"]["score"] if d["match"] else None}
    return _MATCH_CACHE[key]


def _judge(chosen: str | None, accept: set[str]) -> str:
    if chosen is None:
        return "handoff"
    return "correct_auto" if chosen in accept else "wrong_auto"


def _tally(outcomes: list[str]) -> dict:
    c = Counter(outcomes)
    acc = c["correct_auto"] + c["wrong_auto"]
    return {
        "n": len(outcomes),
        "correct_auto": c["correct_auto"],
        "wrong_auto": c["wrong_auto"],
        "handoff": c["handoff"],
        "precision": round(c["correct_auto"] / acc, 3) if acc else None,
    }


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def _score_steps(texts: list[str], gold_steps: list[dict], job: str, raw: str, expand) -> list[dict]:
    """단계 문장마다 그림을 고르고 판정한다. 단계 수가 같으면 순서대로 맞추고, 다르면 정답 그림 합집합으로 본다."""
    scored = [s for s in gold_steps if s.get("gap") is not None]
    union = expand(a for s in scored for a in (s.get("accept") or []))
    any_gap = any(s.get("gap") for s in scored)
    out = []
    aligned = len(texts) == len(gold_steps)
    for k, text in enumerate(texts):
        if aligned:
            g = gold_steps[k]
            if g.get("gap") is None:
                continue
            acc = set() if g.get("gap") else expand(g.get("accept") or [])
            gold_text = g["text"]
        else:
            if not scored:
                continue
            acc = union
            gold_text = None
            if any_gap and not union:
                acc = set()
        m = match(text, job, raw)
        out.append({"text": text, "gold": gold_text, "chosen": m["chosen"], "reason": m["reason"],
                    "outcome": _judge(m["chosen"], acc)})
    return out


def evaluate(gold: list[dict], probes: list[dict] | None = None) -> dict:
    id_to_group, group_to_ids = _group_index()

    def expand(ids):
        return _expand_accept(list(ids), id_to_group, group_to_ids)

    items = []
    for item in gold:
        sent = item["sentence"]
        steps = item["steps"]
        job = item.get("job", "")
        clauses = decompose.clauses_of(sent)
        plans = [c.plan for c in clauses]
        new = _new_steps(plans)
        legacy = _split_steps_legacy(sent)
        row = {
            "uid": item["uid"], "job": job, "sentence": sent, "gold_n": len(steps),
            "gold_steps": [s["text"] for s in steps],
            "legacy": legacy, "new": new,
            "auto": len(new) > len(legacy),
            # 부정이 든 조각을 자동으로 나눴으면 뒤집힘 위험(0이어야 한다)
            "negation_auto": any(c.plan.auto and step_split.has_negation(c.text) for c in clauses),
            "hints": [{"reason": p.reason, "suggestion": p.suggestion, "why_not": p.why_not}
                      for p in plans if p.reason],
        }
        scored = [s for s in steps if s.get("gap") is not None]
        if scored:
            union = expand(a for s in scored for a in (s.get("accept") or []))
            m = match(sent, job, sent)
            row["unsplit"] = {"chosen": m["chosen"], "outcome": _judge(m["chosen"], union)}
            row["new_match"] = _score_steps(new, steps, job, sent, expand)
            row["legacy_match"] = _score_steps(legacy, steps, job, sent, expand)
        items.append(row)

    report: dict = {"n_items": len(items)}

    # (a) 단계 수
    counts = {}
    for name in ("legacy", "new"):
        conf = Counter((r["gold_n"], min(len(r[name]), 4)) for r in items)
        correct = sum(1 for r in items if len(r[name]) == r["gold_n"])
        counts[name] = {
            "accuracy": _ratio(correct, len(items)), "correct": correct,
            "single_kept": sum(1 for r in items if r["gold_n"] == 1 and len(r[name]) == 1),
            "single_total": sum(1 for r in items if r["gold_n"] == 1),
            "multi_exact": sum(1 for r in items if r["gold_n"] > 1 and len(r[name]) == r["gold_n"]),
            "multi_total": sum(1 for r in items if r["gold_n"] > 1),
            "confusion": {f"{g}->{p}": n for (g, p), n in sorted(conf.items())},
        }
    report["counts"] = counts

    # (1) 자동 분할
    auto = [r for r in items if r["auto"]]
    auto_ok = [r for r in auto if len(r["new"]) == r["gold_n"]]
    multi = [r for r in items if r["gold_n"] > 1]
    multi_by_auto = [r for r in multi if r["auto"] and len(r["new"]) == r["gold_n"]]
    report["auto_split"] = {
        "sentences": len(auto), "gold_count_match": len(auto_ok),
        "precision": _ratio(len(auto_ok), len(auto)),
        "recall": _ratio(len(multi_by_auto), len(multi)), "recall_hits": len(multi_by_auto),
        "multi_total": len(multi),
        "wrong": [{"uid": r["uid"], "sentence": r["sentence"], "gold_n": r["gold_n"], "new": r["new"]}
                  for r in auto if len(r["new"]) != r["gold_n"]],
        "generated": [{"uid": r["uid"], "sentence": r["sentence"], "steps": r["new"]} for r in auto],
    }

    # (2) 위험 꼴 묶음(사람 라벨)
    report["probes"] = evaluate_probes(probes if probes is not None else load_probes())
    report["probes"]["gold_negation_auto_regex"] = sum(1 for r in items if r["negation_auto"])

    # (3) 제안 범위
    # 정답이 여러 단계인데 새 분할기 단계 수가 틀린 문장(예전 쉼표 규칙으로 이미 맞게 나뉜 문장은 뺀다)
    not_auto = [r for r in multi if len(r["new"]) != r["gold_n"]]
    hinted = [r for r in not_auto if r["hints"]]
    drafted = [r for r in hinted
               if len(r["hints"]) == 1 and r["hints"][0]["suggestion"]
               and len(r["new"]) - 1 + len(r["hints"][0]["suggestion"]) == r["gold_n"]]
    single = [r for r in items if r["gold_n"] == 1]
    false_hints = [r for r in single if r["hints"]]
    why = Counter(w for r in not_auto for h in r["hints"] for w in h["why_not"])
    report["suggestions"] = {
        "multi_not_auto": len(not_auto), "hinted": len(hinted), "coverage": _ratio(len(hinted), len(not_auto)),
        "draft_count_match": len(drafted), "draft_coverage": _ratio(len(drafted), len(not_auto)),
        "uncovered": [r["sentence"] for r in not_auto if not r["hints"]],
        "single_total": len(single), "false_hints": len(false_hints),
        "false_hint_sentences": [r["sentence"] for r in false_hints],
        "why_not_auto": dict(why.most_common()),
        "with_reason": dict(Counter(h["reason"] for r in items for h in r["hints"])),
    }

    # (4) 그림 정밀도
    aligned = [r for r in auto_ok if "new_match" in r]
    report["matching"] = {
        "auto_split_items": len(aligned),
        "auto_split_steps": _tally([s["outcome"] for r in aligned for s in r["new_match"]]),
        "unsplit_same_items": _tally([r["unsplit"]["outcome"] for r in aligned]),
        "auto_split_all_steps": _tally([s["outcome"] for r in auto if "new_match" in r for s in r["new_match"]]),
        "unsplit_all_auto_items": _tally([r["unsplit"]["outcome"] for r in auto if "unsplit" in r]),
        "pipeline_new": _tally([s["outcome"] for r in items if "new_match" in r for s in r["new_match"]]),
        "pipeline_legacy": _tally([s["outcome"] for r in items if "legacy_match" in r for s in r["legacy_match"]]),
        "wrong_steps": [{"uid": r["uid"], "text": s["text"], "chosen": s["chosen"], "gold": s["gold"]}
                        for r in auto if "new_match" in r for s in r["new_match"]
                        if s["outcome"] == "wrong_auto"],
    }
    # 부분별(held = golden·blind1 — 나뉜 단계 기준값을 고를 때 쓰지 않은 부분이 주 지표, dev는 기준값을 고른 부분)
    report["matching"]["by_part"] = {
        name: {
            "items": sum(1 for r in aligned if _part_of(r["uid"], name)),
            "auto_split_steps": _tally([s["outcome"] for r in aligned if _part_of(r["uid"], name)
                                        for s in r["new_match"]]),
            "unsplit_same_items": _tally([r["unsplit"]["outcome"] for r in aligned if _part_of(r["uid"], name)]),
        }
        for name in ("held", "dev")
    }
    report["items"] = items
    return report


def _fmt(t: dict) -> str:
    p = "-" if t["precision"] is None else f"{t['precision']:.3f}"
    return f"{t['n']:>4} {t['correct_auto']:>5} {t['wrong_auto']:>5} {t['handoff']:>5}  {p:>6}"


def print_report(report: dict, verbose: bool = False) -> None:
    print(f"\n문항 {report['n_items']}개")
    print("\n(a) 단계 수")
    print(f"{'분할기':<10}{'정확도':>8}{'맞음':>6}{'1단계 유지':>12}{'여러 단계 정확':>14}")
    for name, c in report["counts"].items():
        print(f"{name:<10}{c['accuracy']:>8.3f}{c['correct']:>6}{c['single_kept']:>7}/{c['single_total']:<4}"
              f"{c['multi_exact']:>9}/{c['multi_total']:<4}")
    for name, c in report["counts"].items():
        print(f"  혼동표 {name:<8}" + "  ".join(f"{k}:{v}" for k, v in c["confusion"].items()))

    a = report["auto_split"]
    print(f"\n(1) 자동 분할: {a['sentences']}문장, 단계 수 정답 {a['gold_count_match']} → 정밀도 {a['precision']}"
          f" / 재현율 {a['recall']} ({a['recall_hits']}/{a['multi_total']})")
    for w in a["wrong"]:
        print(f"    단계 수 틀림 {w['gold_n']}->{len(w['new'])}: {w['sentence']}  =>  {' | '.join(w['new'])}")

    pr = report["probes"]
    print(f"\n(2) 위험 꼴 묶음 {pr['n']}문장 — 부정 뒤집힘(사람 라벨) {pr['negation_auto']}"
          f" / 위반 {len(pr['violations'])} (참고: 정답셋 has_negation 기준 {pr['gold_negation_auto_regex']})")
    print(f"    {'갈래':<18}{'n':>4}{'자동':>6}{'힌트':>6}{'초안':>6}{'위반':>6}")
    for label, row in pr["by_label"].items():
        print(f"    {label:<18}{row['n']:>4}{row['auto']:>6}{row['hinted']:>6}{row['drafted']:>6}{row['violations']:>6}")
    for v in pr["violations"]:
        print(f"    !! [{v['label']}] {v['sentence']} ({','.join(v['why'])}) => {' | '.join(v['steps'])}"
              f"  초안={v['drafts']}")

    s = report["suggestions"]
    print(f"\n(3) 제안: 단계 수를 못 맞춘 여러 단계 문장 {s['multi_not_auto']} 중 힌트 {s['hinted']} → 범위 {s['coverage']}"
          f", 초안 단계 수 정답 {s['draft_count_match']} ({s['draft_coverage']})")
    print(f"    한 단계 문장 {s['single_total']} 중 헛힌트 {s['false_hints']}")
    print(f"    자동 분할을 막은 이유: {s['why_not_auto']}")
    for u in s["uncovered"]:
        print(f"    힌트 없음: {u}")

    m = report["matching"]
    print(f"\n(4) 그림 매칭{'':<26}{'n':>4} {'정답':>5} {'오답':>5} {'넘김':>5}  {'정밀도':>6}")
    for name, label in (("held", "held(주 지표 — 기준값을 고를 때 안 본 부분)"), ("dev", "dev(기준값을 고른 부분)")):
        part = m["by_part"][name]
        print(f"  {label} {part['items']}문항")
        print(f"    {'단계별':<34}{_fmt(part['auto_split_steps'])}")
        print(f"    {'같은 문항 원문 한 번':<34}{_fmt(part['unsplit_same_items'])}")
    print(f"  자동 분할(단계 수 맞음) 전체 {m['auto_split_items']}문항")
    print(f"    {'단계별':<34}{_fmt(m['auto_split_steps'])}")
    print(f"    {'같은 문항 원문 한 번':<34}{_fmt(m['unsplit_same_items'])}")
    print("  자동 분할 문항 전체(단계 수 틀린 문항은 합집합 판정)")
    print(f"    {'단계별':<34}{_fmt(m['auto_split_all_steps'])}")
    print(f"    {'같은 문항 원문 한 번':<34}{_fmt(m['unsplit_all_auto_items'])}")
    print("  정답셋 전체 파이프라인(오답 채택 총수)")
    print(f"    {'new':<34}{_fmt(m['pipeline_new'])}")
    print(f"    {'legacy':<34}{_fmt(m['pipeline_legacy'])}")

    if verbose:
        print("\n위험 꼴 묶음에서 자동으로 나뉜 문장(문법 검토용)")
        for g in pr["auto_sentences"]:
            print(f"  [{g['label']}] {g['sentence']}\n      => {' | '.join(g['steps'])}")
        print("\n자동 분할로 만든 문장(문법 검토용)")
        for g in a["generated"]:
            print(f"  {g['sentence']}\n      => {' | '.join(g['steps'])}")
        print("\n제안 초안")
        for r in report["items"]:
            for h in r["hints"]:
                draft = " | ".join(h["suggestion"]) if h["suggestion"] else "(초안 없음)"
                print(f"  [{h['reason']}] {r['sentence']}  =>  {draft}   ({','.join(h['why_not'])})")
        print("\n오답 자동 채택(자동 분할 단계)")
        for w in m["wrong_steps"]:
            print(f"  {w['text']}  → {w['chosen']}   (정답 단계: {w['gold']})")


# --- 나뉜 단계 기준값 고르기 -----------------------------------------------------------
SWEEP_THRESHOLDS = (0.215, 0.23, 0.24, 0.26, 0.28, 0.30)
SWEEP_VERB_FREE = (0.30, 0.35, 0.40, 0.45, 9.0)   # 9.0 = 동사가 다르면 점수와 상관없이 넘김
PARTS = {"all": None, "dev": ("dev",), "held": ("golden", "blind1")}
_GATE_KEYS = ("AAC_SPLIT_GATE", "AAC_SPLIT_MATCH_THRESHOLD", "AAC_SPLIT_VERB_FREE_SCORE", "AAC_SPLIT_SIBLING_CHECK")


def _auto_items(gold: list[dict]) -> list[tuple[dict, list[str]]]:
    """자동 분할로 단계 수가 정답과 같아진 문항과 그 단계 문장."""
    out = []
    for item in gold:
        new = _new_steps(decompose.plan_steps(item["sentence"]))
        legacy = _split_steps_legacy(item["sentence"])
        if len(new) > len(legacy) and len(new) == len(item["steps"]):
            if any(s.get("gap") is not None for s in item["steps"]):
                out.append((item, new))
    return out


def _part_of(uid: str, part: str) -> bool:
    prefixes = PARTS[part]
    return prefixes is None or uid.split(":")[0] in prefixes


def sweep(gold: list[dict], part: str = "dev") -> dict:
    """나뉜 단계 기준(점수 하한 T, 동사 예외 점수 H, 형제 중복 검사)을 자동 분할 문항에서 훑는다.

    고르는 규칙(값을 보기 전에 정했다, 2차 시도와 같다): part 부분에서 원문 한 번보다 오답이 많거나 정밀도가 낮은
    설정은 뺀다. 남은 것 중 (1) 오답 채택이 가장 적고 (2) 정답 채택이 가장 많고 (3) T가 낮고(점수 기준을 덜 바꾸고)
    (4) H가 높고(동사 예외가 좁고) (5) 형제 중복 검사를 켠 설정. 오답 그림이 넘김보다 해롭다는 서비스 원칙의 순서다.
    다른 부분(held)의 값은 고른 뒤에 보고만 한다.
    """
    id_to_group, group_to_ids = _group_index()

    def expand(ids):
        return _expand_accept(list(ids), id_to_group, group_to_ids)

    items = _auto_items(gold)
    saved = {k: os.environ.get(k) for k in _GATE_KEYS}

    def run(env: dict) -> dict:
        os.environ.update(env)
        _MATCH_CACHE.clear()
        res = {}
        for name in PARTS:
            outs, base = [], []
            for item, new in items:
                if not _part_of(item["uid"], name):
                    continue
                scored = [g for g in item["steps"] if g.get("gap") is not None]
                union = expand(a for g in scored for a in (g.get("accept") or []))
                base.append(_judge(match(item["sentence"], item.get("job", ""), item["sentence"])["chosen"], union))
                outs += [s["outcome"] for s in _score_steps(new, item["steps"], item.get("job", ""),
                                                            item["sentence"], expand)]
            res[name] = {"split": _tally(outs), "unsplit": _tally(base)}
        return res

    rows = []
    try:
        rows.append({"gate": "off", **run({"AAC_SPLIT_GATE": "off"})})
        for sib in ("on", "off"):
            for t in SWEEP_THRESHOLDS:
                for h in SWEEP_VERB_FREE:
                    rows.append({"gate": "on", "threshold": t, "verb_free": h, "sibling_check": sib,
                                 **run({"AAC_SPLIT_GATE": "on", "AAC_SPLIT_MATCH_THRESHOLD": str(t),
                                        "AAC_SPLIT_VERB_FREE_SCORE": str(h), "AAC_SPLIT_SIBLING_CHECK": sib})})
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _MATCH_CACHE.clear()
    base = rows[0][part]["unsplit"]
    ok = [r for r in rows[1:] if r[part]["split"]["wrong_auto"] <= base["wrong_auto"]
          and (r[part]["split"]["precision"] or 0) >= (base["precision"] or 0)]
    chosen = min(ok, key=lambda r: (r[part]["split"]["wrong_auto"], -r[part]["split"]["correct_auto"],
                                    r["threshold"], -r["verb_free"], r["sibling_check"] != "on")) if ok else None
    return {"part": part, "items": {k: sum(1 for it, _ in items if _part_of(it["uid"], k)) for k in PARTS},
            "rows": rows, "chosen": chosen}


def print_sweep(res: dict) -> None:
    part = res["part"]
    print(f"\n나뉜 단계 기준 훑기 — 고르는 부분 {part}, 자동 분할 문항 {res['items']}")
    b = res["rows"][0]
    for name in PARTS:
        u = b[name]["unsplit"]
        print(f"  원문 한 번 [{name}]: 정답 {u['correct_auto']} / 오답 {u['wrong_auto']} / 정밀도 {u['precision']}")
    print(f"  {'설정':<22}" + "".join(f"{'[' + n + '] 정답/오답/넘김/정밀도':>32}" for n in PARTS))
    for r in res["rows"]:
        label = "기준 없음" if r["gate"] == "off" else f"T{r['threshold']} H{r['verb_free']} 형제{r['sibling_check']}"
        cells = ""
        for n in PARTS:
            t = r[n]["split"]
            p = "-" if t["precision"] is None else f"{t['precision']:.3f}"
            cells += f"{t['correct_auto']:>14}/{t['wrong_auto']}/{t['handoff']}/{p}"
        mark = "  <= 고름" if r is res["chosen"] else ""
        print(f"  {label:<22}{cells}{mark}")


def main() -> None:
    ap = argparse.ArgumentParser(description="규칙 분해기 단계 나누기 평가")
    ap.add_argument("--gold", required=True, help="정답 파일(JSON 목록)")
    ap.add_argument("--json", help="결과 저장 경로")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--sweep", action="store_true", help="나뉜 단계 기준값을 dev 부분에서 훑고 고른다")
    ap.add_argument("--probes", help="위험 꼴 묶음 파일(기본 eval/split_probes.json)")
    args = ap.parse_args()
    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    if args.sweep:
        res = sweep(gold)
        print_sweep(res)
        if args.json:
            Path(args.json).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    report = evaluate(gold, load_probes(Path(args.probes)) if args.probes else None)
    print_report(report, args.verbose)
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n결과 저장: {args.json}")


if __name__ == "__main__":
    main()
