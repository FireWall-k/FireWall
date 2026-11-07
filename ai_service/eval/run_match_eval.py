"""AAC 이미지 매칭 평가 하네스 (점수판).

`run_eval.py`가 '문장을 잘 나눴는가'를 재는 것과 짝을 이뤄, 이 스크립트는
'그 문장에 맞는 그림을 골랐는가'를 잰다. 매칭 스코어러(`local_aac.py`)를 고칠 때마다
돌려서 개선/회귀를 숫자로 확인한다.

실행:
    cd ai_service
    python -m eval.run_match_eval                  # 골든셋 전체 채점(LLM 경로, 임베딩 off)
    python -m eval.run_match_eval --dataset dev    # 개발셋(eval/dev_set.json). 경로를 줘도 된다
    python -m eval.run_match_eval --query-mode sentence  # 규칙 폴백 경로
    python -m eval.run_match_eval --case cafe_sweep    # 특정 케이스만
    python -m eval.run_match_eval --job cleaning       # 특정 직무만
    python -m eval.run_match_eval --verbose            # 케이스별 상위 후보까지 출력
    python -m eval.run_match_eval --json before.json   # 스코어러 수정 전/후 비교용
    python -m eval.run_match_eval --embedding local    # 로컬 모델로 질의 임베딩(무료, 네트워크 없음)
    python -m eval.run_match_eval --embedding cached   # 질의 임베딩 디스크 캐시로 채점(모델 호출 없음)
    python -m eval.run_match_eval --fill-embed-cache   # 캐시 채우기(지금 제공자; openai면 키 필요)
    python -m eval.run_match_eval --write-baseline     # eval/baselines/ 네 벌 갱신

네트워크·LLM을 쓰지 않는다(--fill-embed-cache 제외). 임베딩 모드는 off|local|cached 셋뿐이고
'키가 있으면 저절로 켜지는' auto는 받지 않는다 — 개발자 셸에 키가 있느냐에 따라 수치가
달라지면 전후 비교가 무의미해지기 때문이다. 같은 커밋이면 항상 같은 결과가 나온다(결정적).

두 가지 질의 모드 — 둘 다 프로덕션에 실제로 존재하는 경로다:
    full      문장 + symbol_query (LLM 분해가 성공한 경우). 기본값.
    sentence  문장만 (LLM 키가 없거나 실패해 규칙 폴백으로 떨어진 경우).
              symbol_query가 없으므로 점수 하한선을 보여준다.

지표(metrics, 모두 0~1 비율):
    top1_accuracy   1순위가 정답 집합에 있는 비율 (일반 케이스)
    recall@3        상위 3개 안에 정답이 있는 비율 → 사람에게 후보를 보여줄 때의 상한
    recall@N        상위 N개 안에 정답이 있는 비율 → 리랭커를 붙였을 때의 상한
    wrong_accept    정답이 아닌데 자동 채택한 비율 ← 가장 중요. 현장에 오답 카드가 나가는 비율
    gap_declined    정답 자산이 없는 케이스를 올바르게 거절한 비율
    handoff         자동 채택하지 않고 넘긴 비율(사람 확인 필요) — 너무 높으면 실용성 저하
    accept_precision         자동 채택 중 정답 비율 — 봉인 시험지 수치와 직접 비교되는 지표
    correct_auto_rate        정답을 자동 채택한 비율(전체 케이스 기준)
    normal_correct_auto_rate 같은 값의 일반 케이스 기준

건수(counts): wrong_accept(_normal/_gap), correct_auto, accepted, top1_hit. 기준선 비교는
비율이 아니라 건수로 한다 — 정답셋 크기가 작아 비율 0.005 차이가 1건인지 0건인지 헷갈린다.

정답 집합은 `group_id`로 자동 확장된다. 같은 행동의 변형 이미지(ASSEMBLY_031_01~04)는
어느 것이 나와도 정답으로 친다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

# tests/ 와 동일한 경로 주입(ai_service를 import 루트로).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

import embeddings  # noqa: E402
from local_aac import (  # noqa: E402
    _margin_settings, get_data_dir, load_assets, search_for_step_detailed, step_query,
)

EVAL_DIR = Path(__file__).resolve().parent
DATASET_PATH = EVAL_DIR / "match_dataset.json"
DEV_DATASET_PATH = EVAL_DIR / "dev_set.json"
# 이름 → 파일. 골든셋·개발셋 모두 튜닝용이다(봉인 시험지 final_90/은 여기 넣지 않는다 — 튜닝 금지).
DATASETS = {"golden": DATASET_PATH, "dev": DEV_DATASET_PATH}
BASELINE_DIR = EVAL_DIR / "baselines"
EMBED_CACHE_DIR = EVAL_DIR / ".embed_cache"
EMBEDDING_MODES = ("off", "local", "cached")


class EmbeddingCacheMiss(RuntimeError):
    """cached 모드에서 질의 벡터가 디스크 캐시에 없다 — API로 메우지 않고 멈춘다."""


class MixedEmbeddingError(RuntimeError):
    """일부 케이스만 임베딩을 썼다 — 임계값 두 벌(0.35/0.215)이 섞여 수치가 무의미하다."""


def resolve_dataset(value: str | os.PathLike) -> Path:
    """'golden'/'dev' 별칭 또는 파일 경로."""
    if str(value) in DATASETS:
        return DATASETS[str(value)]
    path = Path(value)
    if not path.exists():
        raise SystemExit(f"데이터셋 파일이 없습니다: {path}")
    return path.resolve()


def dataset_name(path: Path) -> str:
    """리포트·기준선에 적을 이름. 알려진 셋이면 별칭, 아니면 파일 이름."""
    for name, known in DATASETS.items():
        if Path(path).resolve() == known.resolve():
            return name
    return Path(path).name


# --- 데이터 지문 ---------------------------------------------------------------

def _json_digest(path: Path) -> str:
    """JSON 내용의 해시. 바이트가 아니라 파싱한 값을 정규화해 해시한다 — Windows 체크아웃의
    CRLF 변환이나 들여쓰기만 바뀐 경우까지 '데이터가 바뀌었다'고 오판하지 않게."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    canon = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def data_fingerprint(dataset: Path) -> dict:
    """기준선이 어떤 데이터로 만들어졌는지. 정답셋이나 자산 라벨·인덱스가 바뀌면 건수 비교가
    의미 없어지므로 기준선 테스트가 이것부터 확인한다."""
    data_dir = get_data_dir()
    return {
        "dataset": _json_digest(dataset),
        "aac_assets": _json_digest(data_dir / "aac_assets.json"),
        "aac_index": _json_digest(data_dir / "aac_index.json"),
    }


# --- 정답 집합 확장 -----------------------------------------------------------

def _group_index() -> tuple[dict[str, str], dict[str, list[str]]]:
    """asset_id -> group_id, group_id -> [asset_id] 인덱스."""
    id_to_group: dict[str, str] = {}
    group_to_ids: dict[str, list[str]] = {}
    for asset in load_assets():
        gid = asset.get("group_id") or asset["id"]
        id_to_group[asset["id"]] = gid
        group_to_ids.setdefault(gid, []).append(asset["id"])
    return id_to_group, group_to_ids


def _expand_accept(accept: list[str], id_to_group: dict, group_to_ids: dict) -> set[str]:
    """정답 id를 같은 group_id의 모든 변형으로 확장한다."""
    expanded: set[str] = set()
    for asset_id in accept:
        gid = id_to_group.get(asset_id)
        if gid is None:
            raise SystemExit(f"정답셋에 없는 asset_id: {asset_id}")
        expanded.update(group_to_ids[gid])
    return expanded


# --- 케이스 실행 --------------------------------------------------------------

def _case_inputs(case: dict, query_mode: str) -> tuple[list[str], dict]:
    """프로덕션 경로와 동일하게 문장을 context['sentence']에, action_type을
    context['action_type']에 넣고 symbol_query를 키워드로 넘긴다
    (backend/main.py의 _pick_symbol과 같은 형태).
    query_mode='sentence'면 symbol_query를 비워 규칙 폴백 경로를 재현한다."""
    ctx = dict(case.get("context") or {})
    ctx["sentence"] = case["sentence"]
    ctx["action_type"] = case.get("action_type", "other")
    keywords = list(case.get("symbol_query") or []) if query_mode == "full" else []
    return keywords, ctx


def case_query(case: dict, query_mode: str) -> str:
    """이 케이스가 검색(과 질의 임베딩)에 넘기는 문자열 — 캐시 키를 만들 때 쓴다."""
    keywords, ctx = _case_inputs(case, query_mode)
    return step_query(keywords, ctx).strip()


def eval_case(case: dict, accept: set[str], recall_depth: int, shortlist: int,
              query_mode: str = "full") -> dict:
    """한 케이스를 실행해 순위·판정 결과를 낸다.

    검색은 한 번만 한다. 예전에는 순위용(search_assets, limit=20)과 판정용
    (search_for_step_detailed, limit=5)을 따로 불러 두 배 느렸고, 질의 문자열을 만드는 방식이
    달라 순위와 판정이 서로 다른 질의에서 나올 여지가 있었다. 이제 프로덕션 판정 함수에
    limit만 늘려 넘기고, 판정이 돌려주는 후보 목록을 그대로 순위로 쓴다.
    """
    keywords, ctx = _case_inputs(case, query_mode)
    decision = search_for_step_detailed(keywords, ctx, limit=recall_depth)
    ranked = decision["candidates"]
    ranked_ids = [r["asset_id"] for r in ranked]
    chosen = decision["match"]

    is_gap = bool(case.get("gap"))
    top1_hit = bool(ranked_ids) and ranked_ids[0] in accept
    accepted = chosen is not None
    accepted_hit = accepted and chosen["asset_id"] in accept

    return {
        "id": case["id"],
        "job": case.get("job", ""),
        "gap": is_gap,
        "sentence": case["sentence"],
        "reason": decision["reason"],
        "embedding": decision.get("embedding", False),
        "top1_hit": top1_hit,
        "in_shortlist": any(i in accept for i in ranked_ids[:shortlist]),
        "in_recall": any(i in accept for i in ranked_ids[:recall_depth]),
        "accepted": accepted,
        # 오답 채택: 채택했는데 정답이 아님(갭 케이스는 무엇을 채택하든 오답).
        "wrong_accept": accepted and not accepted_hit,
        "correct_auto": accepted_hit,
        "top_score": round(ranked[0]["score"], 4) if ranked else 0.0,
        # 판정이 실제로 본 여유(같은 그림 묶음 밖 첫 경쟁자 기준). 단순 1·2위 차를 적으면
        # 쌍둥이 때문에 여유 0으로 보이는데 채택된 케이스가 생겨 리포트를 잘못 읽게 된다.
        "margin": round(decision["margin"], 4) if len(ranked) > 1 else 0.0,
        "top_label": ranked[0]["label"] if ranked else "",
        "top_id": ranked_ids[0] if ranked_ids else "",
        "candidates": [
            {"id": r["asset_id"], "label": r["label"], "score": round(r["score"], 4),
             "hit": r["asset_id"] in accept}
            for r in ranked[:shortlist]
        ],
    }


def _rate(num: int, den: int) -> float:
    return round(num / den, 3) if den else 0.0


# --- 임베딩 모드 ---------------------------------------------------------------

def query_cache_path(cache_dir: Path, query: str) -> Path:
    """질의 벡터 캐시 파일. 키 = (모델, 차원, 질의 sha256).

    모델·차원을 디렉터리로 나눈 이유: 설정을 바꾼 뒤 옛 벡터를 조용히 섞어 쓰면 점수 척도가
    어긋나는데, 파일 이름만 보고는 알 수 없다. 질의는 _search와 같이 앞뒤 공백만 정규화한다.
    """
    model, dims = embeddings.active_model()
    model = str(model).replace("/", "_")
    digest = hashlib.sha256(query.strip().encode("utf-8")).hexdigest()
    return Path(cache_dir) / f"{model}-{dims}" / f"{digest}.npy"


def _read_cached_vector(cache_dir: Path, query: str) -> np.ndarray | None:
    path = query_cache_path(cache_dir, query)
    if not path.exists():
        return None
    vec = np.load(path, allow_pickle=False).astype(np.float32)
    if vec.shape != (int(embeddings.active_model()[1]),):
        raise EmbeddingCacheMiss(f"캐시 벡터 차원이 설정과 다릅니다: {path} {vec.shape}")
    return vec


@contextmanager
def _embedding_mode(mode: str, cache_dir: Path):
    """채점 동안만 임베딩 경로를 고정한다.

    off    — AAC_EMBEDDINGS=off. 키가 있어도 API를 부르지 않는다.
    local  — 운영과 같은 경로(embeddings.query_similarities)를 로컬 제공자로 돌린다. 키·네트워크
             없이 결정적이다. AAC_EMBED_PROVIDER를 이 동안 local로 고정한다(셸에 openai가 있어도).
    cached — 질의 유사도를 디스크 캐시 벡터로 계산한다. 캐시에 없으면 API를 부르는 대신
             EmbeddingCacheMiss — CI·키 없는 환경에서도 임베딩 경로를 같은 수치로 재현하기 위해서다.
    프로덕션 코드는 건드리지 않고 embeddings.query_similarities만 잠시 바꿔 끼운다.
    """
    if mode not in EMBEDDING_MODES:
        raise SystemExit(f"임베딩 모드는 {EMBEDDING_MODES} 중 하나여야 합니다: {mode}")
    saved_env = os.environ.get("AAC_EMBEDDINGS")
    saved_provider = os.environ.get("AAC_EMBED_PROVIDER")
    original = embeddings.query_similarities
    if mode == "off":
        os.environ["AAC_EMBEDDINGS"] = "off"
    elif mode == "local":
        os.environ["AAC_EMBEDDINGS"] = "auto"
        os.environ["AAC_EMBED_PROVIDER"] = "local"
        embeddings._load_store.cache_clear()
        if embeddings._load_store() is None:
            _restore_env("AAC_EMBEDDINGS", saved_env)
            _restore_env("AAC_EMBED_PROVIDER", saved_provider)
            embeddings._load_store.cache_clear()
            raise SystemExit("로컬 모델로 만든 자산 임베딩 파일(aac_embeddings.npz)이 없거나 현재 "
                             "라벨과 어긋나 local 모드를 쓸 수 없습니다.")
    else:
        store = embeddings._load_store()
        if store is None:
            raise SystemExit("자산 임베딩 파일(aac_embeddings.npz)이 없거나 현재 라벨과 어긋나 "
                             "cached 모드를 쓸 수 없습니다.")

        def cached(query: str):
            if not query.strip():
                return None
            vec = _read_cached_vector(cache_dir, query)
            if vec is None:
                raise EmbeddingCacheMiss(
                    f"질의 임베딩 캐시 없음: {query!r} — 키가 있는 환경에서 "
                    "python -m eval.run_match_eval --fill-embed-cache 로 채우세요.")
            return embeddings.sims_for_vector(store, vec)

        embeddings.query_similarities = cached
    try:
        yield
    finally:
        embeddings.query_similarities = original
        _restore_env("AAC_EMBEDDINGS", saved_env)
        if mode == "local":
            _restore_env("AAC_EMBED_PROVIDER", saved_provider)
            embeddings._load_store.cache_clear()


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def check_embedding_consistency(rows: list[dict], mode: str) -> None:
    """모드와 실제 사용이 어긋나거나 케이스마다 다르면 멈춘다.

    임베딩을 쓴 검색과 못 쓴 검색은 서로 다른 임계값으로 판정된다(local_aac.decide). 호출 실패로
    일부만 빠지면 두 척도가 한 점수판에 섞여 전후 비교가 무의미해진다.
    """
    used = [r["id"] for r in rows if r["embedding"]]
    unused = [r["id"] for r in rows if not r["embedding"]]
    if mode == "off" and used:
        raise MixedEmbeddingError(f"임베딩 off인데 임베딩을 쓴 케이스가 있다: {used[:5]}")
    if mode != "off" and unused:
        raise MixedEmbeddingError(f"임베딩 {mode}인데 임베딩 없이 판정된 케이스가 있다: {unused[:5]}")


def fill_embed_cache(datasets: list[Path], query_modes: list[str],
                     cache_dir: Path = EMBED_CACHE_DIR) -> int:
    """데이터셋 질의의 임베딩을 지금 제공자로 받아 디스크 캐시에 채운다. 채운 개수를 돌려준다.

    openai 제공자는 키가 있을 때만 동작한다. 채점(--embedding cached)은 절대 모델을 부르지 않으므로,
    캐시를 바꾸는 길은 이것 하나다.
    """
    if not embeddings.provider_ready():
        raise SystemExit("OPENAI_API_KEY가 없어 질의 임베딩 캐시를 채울 수 없습니다.")
    queries: list[str] = []
    for path in datasets:
        for case in json.loads(Path(path).read_text(encoding="utf-8"))["cases"]:
            for qm in query_modes:
                q = case_query(case, qm)
                if q and q not in queries and _read_cached_vector(cache_dir, q) is None:
                    queries.append(q)
    for start in range(0, len(queries), 64):
        batch = queries[start:start + 64]
        for q, raw in zip(batch, embeddings.embed_texts(batch)):
            vec = embeddings.normalize(raw)
            if vec is None:
                raise SystemExit(f"영벡터를 받았습니다: {q!r}")
            path = query_cache_path(cache_dir, q)
            path.parent.mkdir(parents=True, exist_ok=True)
            np.save(path, vec)
    return len(queries)


# --- 채점 ----------------------------------------------------------------------

def run(only_case: str | None = None, only_job: str | None = None,
        query_mode: str = "full", dataset: str | os.PathLike = DATASET_PATH,
        embedding: str = "off", cache_dir: Path = EMBED_CACHE_DIR) -> dict:
    dataset_path = resolve_dataset(dataset)
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    decision = data.get("decision", {})
    recall_depth = int(decision.get("recall_depth", 20))
    shortlist = int(decision.get("shortlist_depth", 3))

    cases = data["cases"]
    if only_case:
        cases = [c for c in cases if c["id"] == only_case]
    if only_job:
        cases = [c for c in cases if c.get("job") == only_job]
    if not cases:
        raise SystemExit("조건에 맞는 케이스가 없습니다.")

    id_to_group, group_to_ids = _group_index()

    rows = []
    with _embedding_mode(embedding, cache_dir):
        for case in cases:
            accept = _expand_accept(case.get("accept", []), id_to_group, group_to_ids)
            rows.append(eval_case(case, accept, recall_depth, shortlist, query_mode))
    check_embedding_consistency(rows, embedding)

    normal = [r for r in rows if not r["gap"]]
    gaps = [r for r in rows if r["gap"]]

    counts = {
        "wrong_accept": sum(r["wrong_accept"] for r in rows),
        "wrong_accept_normal": sum(r["wrong_accept"] for r in normal),
        "wrong_accept_gap": sum(r["wrong_accept"] for r in gaps),
        "correct_auto": sum(r["correct_auto"] for r in rows),
        "accepted": sum(r["accepted"] for r in rows),
        "top1_hit": sum(r["top1_hit"] for r in normal),
    }
    metrics = {
        "top1_accuracy": _rate(counts["top1_hit"], len(normal)),
        f"recall@{shortlist}": _rate(sum(r["in_shortlist"] for r in normal), len(normal)),
        f"recall@{recall_depth}": _rate(sum(r["in_recall"] for r in normal), len(normal)),
        "wrong_accept_rate": _rate(counts["wrong_accept"], len(rows)),
        "gap_declined_rate": _rate(sum(not r["accepted"] for r in gaps), len(gaps)),
        "handoff_rate": _rate(sum(not r["accepted"] for r in rows), len(rows)),
        "accept_precision": _rate(counts["correct_auto"], counts["accepted"]),
        "correct_auto_rate": _rate(counts["correct_auto"], len(rows)),
        "normal_correct_auto_rate": _rate(counts["correct_auto"], len(normal)),
    }

    # 거절 사유 분포. low_score는 폴백으로, low_margin은 후보를 보여주고
    # 사람이 고르게 하는 경로다 — 검토 화면에서 다르게 다뤄야 하므로 따로 센다.
    reasons: dict[str, int] = {}
    for row in rows:
        reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1

    # check_embedding_consistency를 통과했으므로 모든 케이스가 같은 임계값 세트로 판정됐다.
    used_embedding = embedding != "off"
    settings = _margin_settings(used_embedding)
    return {
        "dataset": dataset_name(dataset_path),
        "query_mode": query_mode,
        "embedding_mode": embedding,
        "embedding": used_embedding,
        # 기본값을 여기 따로 적지 않고 판정 함수와 같은 곳에서 읽는다 — 기본값을 바꿀 때
        # 리포트·기준선의 임계값 표기가 실제 판정과 어긋나지 않게.
        "threshold": settings[0],
        "min_margin": settings[1],
        "margin_mode": settings[2],
        "min_rel_margin": settings[3],
        "n_cases": len(rows),
        "n_normal": len(normal),
        "n_gap": len(gaps),
        "metrics": metrics,
        "counts": counts,
        "reasons": reasons,
        "cases": rows,
    }


# --- 기준선 --------------------------------------------------------------------

def baseline_path(name: str, query_mode: str) -> Path:
    return BASELINE_DIR / f"{name}_{query_mode}.json"


def make_baseline(report: dict, dataset: Path) -> dict:
    """리포트에서 기준선에 남길 부분만 고른다(케이스별 결과는 빼서 diff를 읽기 쉽게)."""
    return {
        "dataset": report["dataset"],
        "query_mode": report["query_mode"],
        "embedding": report["embedding_mode"],
        "threshold": report["threshold"],
        "min_margin": report["min_margin"],
        "n_cases": report["n_cases"],
        "n_normal": report["n_normal"],
        "n_gap": report["n_gap"],
        "metrics": report["metrics"],
        "counts": report["counts"],
        "fingerprint": data_fingerprint(dataset),
    }


def write_baselines() -> list[Path]:
    """골든·개발 × full·sentence 네 벌을 임베딩 off로 다시 쓴다.

    off로만 만드는 이유: CI에는 키도 질의 캐시도 없다. 임베딩 경로 기준선은 캐시를 커밋한 뒤에 따로 둔다.
    """
    written = []
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    for name, path in DATASETS.items():
        for qm in ("full", "sentence"):
            report = run(query_mode=qm, dataset=path, embedding="off")
            out = baseline_path(name, qm)
            out.write_text(json.dumps(make_baseline(report, path), ensure_ascii=False, indent=2)
                           + "\n", encoding="utf-8")
            written.append(out)
    return written


def compare_to_baseline(report: dict, baseline: dict, wrong_accept_slack: int = 1,
                        correct_auto_slack: int = 1) -> list[str]:
    """기준선보다 허용치를 넘게 나빠진 항목을 사람이 읽을 문장으로 돌려준다(없으면 빈 목록).

    두 건수만 본다. 오답 채택은 현장에 틀린 카드가 나가는 것이라 가장 비싸고, 정답 자동 채택이
    줄면 오답을 '모두 거절'로 줄이는 꼼수가 통과하기 때문이다.
    """
    now, base = report["counts"], baseline["counts"]
    problems = []
    if now["wrong_accept"] > base["wrong_accept"] + wrong_accept_slack:
        problems.append(f"오답 채택 {base['wrong_accept']}→{now['wrong_accept']}건 "
                        f"(허용 +{wrong_accept_slack})")
    if now["correct_auto"] < base["correct_auto"] - correct_auto_slack:
        problems.append(f"정답 자동 채택 {base['correct_auto']}→{now['correct_auto']}건 "
                        f"(허용 −{correct_auto_slack})")
    return problems


# --- 출력 --------------------------------------------------------------------

def _print_report(report: dict, verbose: bool) -> None:
    m = report["metrics"]
    mode_label = {"full": "문장+symbol_query (LLM 경로)",
                  "sentence": "문장만 (규칙 폴백 경로)"}[report["query_mode"]]
    print(f"\n매칭 평가 — 케이스 {report['n_cases']}개"
          f"(일반 {report['n_normal']} / 커버리지갭 {report['n_gap']}), "
          f"채택 기준 점수≥{report['threshold']} 및 여유≥{report['min_margin']}")
    print(f"데이터셋: {report['dataset']}   질의 모드: {mode_label}")
    print("임베딩: " + ({"cached": "cached (디스크 캐시 질의 벡터, 임베딩용 임계값)",
                        "local": "local (로컬 모델 질의 벡터, 임베딩용 임계값)"}
                       .get(report["embedding_mode"], "off (기존 규칙 점수, 기존 임계값)")))
    print("=" * 78)
    for key, value in m.items():
        bar = "#" * int(value * 30)
        flag = ""
        if key == "wrong_accept_rate":
            flag = "  <-- 낮을수록 좋음(현장 오답 카드 비율)"
        print(f"  {key:<24} {value:>6.3f}  {bar}{flag}")
    c = report["counts"]
    print(f"  건수: 자동 채택 {c['accepted']} = 정답 {c['correct_auto']} + 오답 {c['wrong_accept']}"
          f" (일반 {c['wrong_accept_normal']} / 갭 {c['wrong_accept_gap']})")
    print("-" * 78)
    desc = {"accepted": "자동 채택", "no_candidate": "후보 없음 → 폴백",
            "low_score": "점수 미달 → 폴백", "low_margin": "후보 경합 → 사람이 선택",
            "frame_mismatch": "대상 불일치 → 사람이 선택"}
    for reason, count in sorted(report["reasons"].items(), key=lambda kv: -kv[1]):
        print(f"  {desc.get(reason, reason):<24} {count:>3}건")
    print("=" * 78)

    fails = [r for r in report["cases"] if not r["gap"] and not r["top1_hit"]]
    if fails:
        print(f"\n[1순위 오답 {len(fails)}건]")
        print(f"  {'케이스':<22}{'점수':>6}{'여유':>7}  {'채택':<5} 1순위 결과")
        print("  " + "-" * 74)
        for r in sorted(fails, key=lambda x: -x["top_score"]):
            mark = "채택!" if r["accepted"] else "거절"
            hint = " (상위3위내 정답있음)" if r["in_shortlist"] else ""
            print(f"  {r['id']:<22}{r['top_score']:>6.3f}{r['margin']:>7.3f}  {mark:<5} "
                  f"{r['top_label']}{hint}")

    bad_gaps = [r for r in report["cases"] if r["gap"] and r["accepted"]]
    if bad_gaps:
        print(f"\n[커버리지 갭인데 오답 채택 {len(bad_gaps)}건]")
        for r in bad_gaps:
            print(f"  {r['id']:<22}{r['top_score']:>6.3f}        -> {r['top_label']}")

    if verbose:
        print("\n[전체 케이스 상위 후보]")
        for r in report["cases"]:
            status = "GAP" if r["gap"] else ("OK " if r["top1_hit"] else "MISS")
            print(f"\n  {status} {r['id']} — {r['sentence']}")
            for c in r["candidates"]:
                mark = "*" if c["hit"] else " "
                print(f"      {mark} {c['score']:.3f}  {c['label']}")
    print()


def _memoize_retrieval():
    """스윕 동안 검색 결과를 재사용한다.

    검색 순위는 임계값과 무관한데(임계값은 '채택할지'만 정한다) 임계값마다 401개 자산을
    다시 채점하면 스윕이 16배 느려진다. 프로덕션 코드는 건드리지 않고 모듈 속성만
    잠시 감싼다. 복원 함수를 돌려준다.
    """
    import local_aac

    # 하네스의 검색은 search_for_step_detailed → _search 한 경로뿐이라 그것만 감싸면 된다.
    original = local_aac._search
    cache: dict[tuple, tuple[list[dict], bool]] = {}

    def cached(query: str, context: dict | None = None, limit: int = 5):
        key = (query, json.dumps(context or {}, sort_keys=True, ensure_ascii=False), limit)
        if key not in cache:
            cache[key] = original(query, context, limit)
        return cache[key]

    local_aac._search = cached

    def restore() -> None:
        local_aac._search = original

    return restore


def sweep(query_mode: str, thresholds: list[float],
          margins: list[float] | None = None, dataset: str | os.PathLike = DATASET_PATH,
          embedding: str = "off", margin_mode: str = "absolute") -> list[dict]:
    """채택 기준을 바꿔가며 오답채택 / 사람확인 절충 곡선을 낸다.

    margins를 주면 (임계값 × 여유) 2차원으로 돌린다. 스코어러를 고치면 점수 척도가
    바뀌므로 두 값 모두 재교정해야 한다. 눈대중으로 숫자를 찍지 말고 곡선을 보고
    운영점을 고른다.
    """
    # margin_mode="relative"면 margins를 상대 여유 (s1−s2)/s1 값으로 쓴다(local_aac._margin_settings).
    suffix = "MIN_REL_MARGIN" if margin_mode == "relative" else "MIN_MARGIN"
    pairs = (("AAC_MATCH_THRESHOLD", f"AAC_MATCH_{suffix}"),
             ("AAC_EMBED_MATCH_THRESHOLD", f"AAC_EMBED_MATCH_{suffix}"))
    mode_keys = ("AAC_MATCH_MARGIN_MODE", "AAC_EMBED_MATCH_MARGIN_MODE")
    saved = {k: os.environ.get(k) for pair in pairs for k in pair}
    saved.update({k: os.environ.get(k) for k in mode_keys})
    for key in mode_keys:
        os.environ[key] = margin_mode
    restore = _memoize_retrieval()
    rows = []
    try:
        for t in thresholds:
            for mg in (margins if margins is not None else [None]):
                for thr_key, margin_key in pairs:  # 임베딩 유무에 맞는 쪽이 쓰인다
                    os.environ[thr_key] = str(t)
                    if mg is not None:
                        os.environ[margin_key] = str(mg)
                report = run(query_mode=query_mode, dataset=dataset, embedding=embedding)
                row = {"threshold": t, **report["metrics"]}
                if mg is not None:
                    row = {"threshold": t, "margin": mg, **report["metrics"]}
                rows.append(row)
    finally:
        restore()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return rows


def _print_sweep(rows: list[dict], query_mode: str) -> None:
    has_margin = "margin" in rows[0]
    label = "임계값 × 여유" if has_margin else "임계값"
    width = 80 if has_margin else 72
    print(f"\n{label} 스윕 — 질의 모드 {query_mode}")
    print("=" * width)
    head = f"{'임계값':>7}"
    if has_margin:
        head += f"{'여유':>7}"
    print(head + f"{'오답채택':>10}{'사람확인':>10}{'갭거절':>9}{'top1':>8}   판정")
    print("-" * width)
    for r in rows:
        # 오답을 현장에 내보내지 않으면서 사람 확인이 과하지 않은 구간을 표시한다.
        note = ""
        if r["wrong_accept_rate"] <= 0.02 and r["handoff_rate"] <= 0.25:
            note = "<- 권장 구간"
        line = f"{r['threshold']:>7.2f}"
        if has_margin:
            line += f"{r['margin']:>7.3f}"
        print(line + f"{r['wrong_accept_rate']:>10.3f}"
              f"{r['handoff_rate']:>10.3f}{r['gap_declined_rate']:>9.3f}"
              f"{r['top1_accuracy']:>8.3f}   {note}")
    print("=" * width)
    print("오답채택↓ 사람확인↓ 갭거절↑ 가 동시에 좋을 수는 없다. 오답채택을 먼저 누르고,")
    print("그 다음 사람확인이 견딜 만한 가장 낮은 기준을 고른다.\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="AAC 이미지 매칭 평가 하네스")
    ap.add_argument("--dataset", default="golden",
                    help="golden(eval/match_dataset.json) | dev(eval/dev_set.json) | 파일 경로")
    ap.add_argument("--case", help="특정 케이스 id만 채점")
    ap.add_argument("--job", help="특정 직무만 채점 (cafe/cleaning/packaging/retail/assembly)")
    ap.add_argument("--query-mode", choices=["full", "sentence"], default="full",
                    help="full=문장+symbol_query(LLM 경로), sentence=문장만(규칙 폴백 경로)")
    ap.add_argument("--embedding", choices=EMBEDDING_MODES, default="off",
                    help="off=규칙 점수만(기본), local=로컬 모델로 질의 임베딩(무료), "
                         "cached=eval/.embed_cache/ 질의 벡터 사용(모델 호출 없음)")
    ap.add_argument("--no-embedding", action="store_true",
                    help="--embedding off 와 같다(예전 옵션 호환)")
    ap.add_argument("--verbose", action="store_true", help="케이스별 상위 후보 출력")
    ap.add_argument("--sweep", action="store_true",
                    help="채택 임계값을 바꿔가며 오답채택/사람확인 절충 곡선 출력")
    ap.add_argument("--sweep-margin", action="store_true",
                    help="임계값 × 여유(margin) 2차원 스윕")
    ap.add_argument("--margin-mode", choices=["absolute", "relative"], default="absolute",
                    help="--sweep-margin 의 여유 방식: absolute=s1−s2, relative=(s1−s2)/s1")
    ap.add_argument("--json", help="결과를 JSON 파일로 저장(수정 전/후 비교용)")
    ap.add_argument("--write-baseline", action="store_true",
                    help="eval/baselines/{golden,dev}_{full,sentence}.json 을 임베딩 off로 갱신")
    ap.add_argument("--fill-embed-cache", action="store_true",
                    help="--dataset 의 full·sentence 질의 임베딩을 지금 제공자로 받아 캐시에 채운다")
    args = ap.parse_args()
    embedding = "off" if args.no_embedding else args.embedding

    if args.write_baseline:
        for path in write_baselines():
            base = json.loads(path.read_text(encoding="utf-8"))
            c = base["counts"]
            print(f"{path.name:<22} top1 {base['metrics']['top1_accuracy']:.3f}  "
                  f"정밀도 {base['metrics']['accept_precision']:.3f}  "
                  f"오답 채택 {c['wrong_accept']}  정답 자동 채택 {c['correct_auto']}")
        return

    dataset = resolve_dataset(args.dataset)
    if args.fill_embed_cache:
        n = fill_embed_cache([dataset], ["full", "sentence"], EMBED_CACHE_DIR)
        print(f"질의 임베딩 {n}개를 캐시에 채웠습니다: {EMBED_CACHE_DIR}")
        return

    if args.sweep or args.sweep_margin:
        if args.sweep_margin:
            # P5 재보정 범위(0.16~0.24). 여유는 운영점(0.018) 근처를 촘촘히 본다.
            thresholds = [round(0.16 + 0.01 * i, 2) for i in range(9)]
            if args.margin_mode == "relative":
                margins = [0.0, 0.02, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12]
            else:
                margins = [0.0, 0.01, 0.015, 0.018, 0.02, 0.025, 0.03]
        else:
            thresholds = [round(0.10 + 0.02 * i, 2) for i in range(16)]
            margins = None
        rows = sweep(args.query_mode, thresholds, margins, dataset=dataset, embedding=embedding,
                     margin_mode=args.margin_mode)
        _print_sweep(rows, args.query_mode)
        if args.json:
            Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"결과 저장: {args.json}")
        return

    report = run(args.case, args.job, args.query_mode, dataset=dataset, embedding=embedding)
    _print_report(report, args.verbose)
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"결과 저장: {args.json}")


if __name__ == "__main__":
    main()
