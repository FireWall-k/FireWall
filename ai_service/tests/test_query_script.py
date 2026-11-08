"""P7 질의의 영문 토큰 — 라벨 채널은 한글 부분으로만 비교하고, 영문 비율만큼 확신을 낮춘다.

여기 질의들은 시험지 문장이 아니라 현상의 대표 예다.

- 그림 라벨은 모두 한국어라 질의의 영문 낱말은 라벨과 겹칠 수 없다. 그런데 Jaccard 분모에는
  들어가서, 짧은 라벨일수록 더 크게 깎는다 — 영문이 '어느 그림이 이기는가'를 흔든다.
- 검색어(keywords_en)에는 영문이 있으므로 검색어 채널은 질의 전체로 그대로 잰다.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from local_aac import (  # noqa: E402
    _QueryFeatures, _bigrams, _normalize, _relevance, _text_similarity, _tokens,
)


def _label_only_asset(label: str) -> dict:
    """검색어·동사 원형이 없는 자산 — 라벨 채널만 따로 보려고."""
    return {
        "_norm": _normalize(label), "_tokens": _tokens(label), "_bigrams": _bigrams(label),
        "_kw_norm": "", "_kw_tokens": set(), "_kw_bigrams": set(), "_lemmas": set(),
    }


def test_korean_part_strips_latin_tokens():
    qf = _QueryFeatures("포장 봉투를 펼치세요 봉투 plastic bag")
    assert qf.ko_tokens and all(any("가" <= ch <= "힣" for ch in t) for t in qf.ko_tokens)
    assert "plastic" not in qf.ko_norm and "bag" not in qf.ko_norm
    assert 0 < qf.ko_share < 1


def test_all_korean_query_is_unchanged():
    qf = _QueryFeatures("포장 봉투를 펼치세요 봉투")
    assert qf.ko_share == 1
    assert (qf.ko_norm, qf.ko_tokens, qf.ko_bigrams) == (qf.norm, qf.tokens, qf.bigrams)


def test_latin_only_query_falls_back_to_whole_query():
    # 한글이 하나도 없으면 비울 수 없다 — 전체 질의로 잰다.
    qf = _QueryFeatures("apron")
    assert qf.ko_share == 1
    assert qf.ko_norm == qf.norm and qf.ko_tokens == qf.tokens


@pytest.mark.parametrize("label", ["보안경을 착용한다", "작업대 위 남은 부품을 한곳에 모은다"])
def test_label_channel_is_korean_similarity_times_share(label):
    ko = "보안경을 쓰세요 보안경"
    qf = _QueryFeatures(ko + " safety goggles")
    asset = _label_only_asset(label)
    expected = qf.ko_share * _text_similarity(
        qf.ko_norm, qf.ko_tokens, qf.ko_bigrams, asset["_norm"], asset["_tokens"], asset["_bigrams"])
    assert _relevance(asset, qf) == pytest.approx(expected)


def test_latin_tokens_do_not_reorder_label_matches():
    # 영문 낱말은 모든 라벨에 똑같이(같은 비율로) 작용해야 한다. 분모에만 들어가면 짧은 라벨이
    # 긴 라벨보다 더 깎여 순서가 바뀔 수 있다.
    short = _label_only_asset("장갑을 낀다")
    long_ = _label_only_asset("작업 전에 위생 장갑을 양손에 끼고 손목까지 당긴다")
    ko = "위생 장갑을 끼세요 장갑"
    plain, mixed = _QueryFeatures(ko), _QueryFeatures(ko + " disposable hygiene gloves wear")
    ratio_short = _relevance(short, mixed) / _relevance(short, plain)
    ratio_long = _relevance(long_, mixed) / _relevance(long_, plain)
    assert ratio_short == pytest.approx(ratio_long)
    assert (_relevance(short, plain) > _relevance(long_, plain)) == (
        _relevance(short, mixed) > _relevance(long_, mixed))
