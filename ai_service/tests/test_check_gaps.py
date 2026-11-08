"""갭 재점검 스크립트(eval/check_gaps.py) 테스트 (외부 네트워크/API 없음).

갭 케이스("정답 그림이 없다")는 그림이 추가되면 조용히 낡는다. 낡은 갭은 맞는 그림을 붙여도
오답 채택으로 세어 지표를 왜곡한다 — 실제로 골든셋의 갭 3건이 그랬다(에어컨 필터 세척·박스
쌓기 그림이 나중에 추가됨). 스크립트가 그런 갭을 '의심'으로 드러내는지 확인한다.
"""
import json

from eval.check_gaps import check_gaps, format_report


def _dataset(tmp_path, cases):
    path = tmp_path / "gaps.json"
    path.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")
    return path


def _gap(case_id, sentence, job, action_type, symbol_query=()):
    return {
        "id": case_id, "job": job, "gap": True, "sentence": sentence,
        "context": {"business_type": job}, "symbol_query": list(symbol_query),
        "action_type": action_type, "accept": [], "note": "테스트",
    }


def test_stale_gap_is_flagged_when_an_asset_has_the_same_verb_and_object(tmp_path):
    """동사(또는 동작 분류)와 대상이 모두 같은 그림이 있으면 그 갭은 낡았을 수 있다."""
    path = _dataset(tmp_path, [_gap("ac", "에어컨 필터를 청소하세요.", "cleaning", "clean")])
    [row] = check_gaps(path)
    assert row["id"] == "ac"
    assert "CLEANING_139" in {s["id"] for s in row["suspects"]}
    # 상위 후보는 라벨과 함께 보여 줘야 사람이 그림을 열어 판정할 수 있다.
    assert row["candidates"] and all(c["label"] for c in row["candidates"])


def test_verb_only_overlap_is_not_a_suspect(tmp_path):
    """동사만 같고 대상이 다른 그림은 의심이 아니다 — 그걸 다 띄우면 목록이 잡음이 된다."""
    path = _dataset(tmp_path, [_gap("x", "우주선 엔진을 청소하세요.", "cleaning", "clean")])
    [row] = check_gaps(path)
    assert row["suspects"] == []


def test_normal_cases_are_skipped(tmp_path):
    normal = _gap("n", "에어컨 필터를 청소하세요.", "cleaning", "clean")
    normal.update(gap=False, accept=["CLEANING_139"])
    path = _dataset(tmp_path, [normal])
    assert check_gaps(path) == []


def test_breach_is_reported_when_the_system_auto_accepts_a_gap(tmp_path):
    """갭인데 자동 채택되면(오답 채택으로 세임) 그 사실을 따로 표시한다."""
    path = _dataset(tmp_path, [_gap("ac", "에어컨 필터를 청소하세요.", "cleaning", "clean",
                                    ["필터", "filter"])])
    [row] = check_gaps(path)
    assert row["accepted"] is True
    text = format_report([row])
    assert "ac" in text and "CLEANING_139" in text and "에어컨 필터를 세척한다" in text


def test_golden_gap_notes_review_every_suspect():
    """골든셋 갭 케이스의 의심 자산은 note에 id와 함께 '왜 정답이 아닌지'가 적혀 있어야 한다.

    왜: 의심(동작과 대상이 둘 다 겹치는 그림)은 갭이 낡았다는 신호다. 사람이 그림을 열어 보고
    갭으로 남기기로 했다면 그 판단을 note에 남겨야, 다음에 그림이 늘었을 때 '새 의심'과 '이미
    본 의심'이 구분된다. 2026-11-07에 골든 갭 4건이 이렇게 조용히 낡아 있었다(그림 추가 뒤
    노트의 '자산 0건'이 거짓이 됨). 새 그림이 의심으로 잡히면 이 테스트가 깨져 재점검을 강제한다.
    개발셋은 note를 요구하지 않으므로(test_match_eval 참고) 골든셋만 본다.
    """
    from eval.run_match_eval import resolve_dataset

    data = json.loads(resolve_dataset("golden").read_text(encoding="utf-8"))
    notes = {c["id"]: c.get("note", "") for c in data["cases"]}
    unreviewed = {
        row["id"]: [s["id"] for s in row["suspects"] if s["id"] not in notes[row["id"]]]
        for row in check_gaps("golden")
    }
    unreviewed = {k: v for k, v in unreviewed.items() if v}
    assert not unreviewed, (
        f"갭 note에 검토 기록이 없는 의심 자산: {unreviewed} — python -m eval.check_gaps "
        "--suspects-only로 그림을 열어 보고, 정답이면 갭을 풀고 아니면 note에 id와 사유를 적는다")
