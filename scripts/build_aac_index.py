"""AAC 자산 라벨을 구조화해 data/aac/aac_index.json 을 만든다 (오프라인 1회 작업).

왜 필요한가
-----------
현재 매칭은 질의 문장과 자산 라벨의 '문자열 유사도'다. 그래서 명사만 겹치면 동작이
달라도 상위로 올라온다("원두를 갈아주세요" → "원두를 준비한다"), 문장에 언급된
도구 이름이 그대로 도구 카드를 끌어온다("얼음통을 씻어주세요" → 도구 카드 "얼음통").
가중치로는 안 풀린다 — 문제는 점수 크기가 아니라 '무엇을 비교하는가'다.

자산과 질의를 같은 구조(동작+대상+도구)로 표현하면 동사 호환성을 요구조건으로 걸 수
있다. 이 스크립트는 그 구조를 자산 쪽에 한 번 만들어 파일로 굳힌다. 런타임은 다시
추론하지 않는다.

원본과 분리하는 이유
-------------------
`aac_assets.json`(원본 메타데이터)에 섞지 않고 별도 파일로 낸다. LLM이 만든 파생
데이터라 재생성·검수 이력을 따로 관리해야 하고, 원본을 다시 임포트해도 덮어쓰지
않아야 하기 때문이다. `source_digest`로 원본과의 정합을 확인한다.

실행
----
    export OPENAI_API_KEY=...            # 또는 저장소 루트 .env
    python scripts/build_aac_index.py                 # 전체 생성
    python scripts/build_aac_index.py --limit 20      # 소량으로 먼저 확인
    python scripts/build_aac_index.py --job cafe      # 특정 직무만
    python scripts/build_aac_index.py --resume        # 중단분부터 이어서

중간 저장하므로 중단돼도 `--resume`으로 이어진다(401건을 한 번에 날리지 않기 위함).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ai_service"))

from taxonomy import VALID_ACTION_TYPES

ASSETS_PATH = ROOT / "data" / "aac" / "aac_assets.json"
INDEX_PATH = ROOT / "data" / "aac" / "aac_index.json"

# 질의 action_type과 자산 verb_class는 taxonomy.py의 같은 축을 사용한다.
VERB_CLASSES = VALID_ACTION_TYPES

BATCH_SIZE = 20

_SYSTEM = (
    "당신은 직무교육용 AAC 그림카드의 라벨을 구조화하는 전문가입니다. "
    "각 라벨을 '무엇을 하는 그림인가'로 분해합니다.\n"
    "\n"
    "카드는 두 종류입니다. 이 구분이 가장 중요합니다:\n"
    "- 동작 카드: 사람이 무언가를 하는 장면. verb를 채웁니다.\n"
    "- 사물 카드: 물건이나 상태만 보여주는 그림(도구, 완료된 모습 등). "
    "verb를 null로 두고 is_object_card를 true로 합니다. "
    "라벨이 명사구뿐이면(예: '행주', '빗자루', '작업 지시서', '보안경 착용 완료') 사물 카드입니다.\n"
    "\n"
    "각 항목 규칙:\n"
    "1) verb: 동작의 기본형(사전형). '쓸어낸다'→'쓸다', '담는다'→'담다', "
    "'착용한다'→'착용하다'. 사물 카드는 null.\n"
    "2) verb_class는 모든 직무가 공유하는 상위 행동군 하나를 고릅니다. 세부 동작은 verb에 남깁니다.\n"
    "   observe=보다/확인/검사/비교/세다, move=가져오다/옮기다/놓다/꺼내다/전달하다,\n"
    "   sort=분류/나누다/구분/정리, stack=쌓다/적재, pack=담다/포장/밀봉/접다,\n"
    "   clean=닦다/씻다/쓸다/치우다/버리다, wear=사람이 작업복·보호구를 착용/벗다,\n"
    "   operate=버튼·스위치·기계·일반 도구 조작,\n"
    "   assemble=부품 결합/끼움/연결/체결/맞춤/부착/분리/교체/재조립, other=그 밖의 동작.\n"
    "   주의: '장갑을 끼다'는 wear, '부품을 홈에 끼우다'는 assemble입니다. "
    "'나사를 넣다/조이다'가 조립 과정이면 assemble입니다. 사물 카드는 null.\n"
    "3) object: 대상의 **핵심 명사 하나만**. 수식어를 반드시 떼어냅니다.\n"
    "   '빈 포장 봉투'→'봉투', '같은 제품'→'제품', '제품의 방향'→'방향', "
    "'새 쓰레기봉투'→'쓰레기봉투', '완성된 음료'→'음료'. 두 단어 이상이면 잘못된 것입니다.\n"
    "4) object_detail: 3)에서 떼어낸 수식어. 없으면 null('빈', '같은', '완성된').\n"
    "5) instrument: 사용하는 도구가 라벨에 있으면 그 명사, 없으면 null.\n"
    "6) location: 장소/위치가 라벨에 있으면 그 명사, 없으면 null.\n"
    "7) keywords_ko: 한국어 검색어 4~6개. **라벨에 이미 있는 단어는 절대 넣지 마세요.**\n"
    "   이 항목의 목적은 '사업주가 라벨과 다르게 말했을 때도 찾히게' 하는 것입니다.\n"
    "   라벨 단어를 되풀이하면 아무 쓸모가 없습니다. 다르게 말하는 법만 적습니다:\n"
    "   - 동사 동의어: '쓸다'→'비질','빗자루질','쓸어담다' / '닦다'→'훔치다','청소','문지르다'\n"
    "   - '준비하다'→'챙기다','꺼내놓다','마련하다','가져다놓다'\n"
    "   - 대상의 다른 이름: '박스'→'상자','종이상자' / '컵'→'잔','텀블러'\n"
    "   - 현장에서 쓰는 말: '세척'→'설거지' / '적재'→'쌓기'\n"
    "8) keywords_en: 대응하는 영어 검색어 2~4개.\n"
    "\n"
    "출력은 반드시 JSON 하나. 입력 순서와 개수를 그대로 지킵니다.\n"
    "\n예시 입력: [{\"id\":\"A1\",\"job\":\"cleaning\",\"asset_type\":\"action\","
    "\"label\":\"바닥의 먼지를 쓸어 모은다\"},"
    "{\"id\":\"A2\",\"job\":\"cafe\",\"asset_type\":\"tool\",\"label\":\"행주\"},"
    "{\"id\":\"A3\",\"job\":\"packaging\",\"asset_type\":\"action\","
    "\"label\":\"빈 포장 봉투를 준비한다\"}]\n"
    "예시 출력: {\"items\":["
    "{\"id\":\"A1\",\"verb\":\"쓸다\",\"verb_class\":\"clean\",\"object\":\"먼지\","
    "\"object_detail\":null,\"instrument\":null,\"location\":\"바닥\","
    "\"is_object_card\":false,"
    "\"keywords_ko\":[\"비질\",\"빗자루질\",\"쓸어담다\",\"청소\",\"티끌\"],"
    "\"keywords_en\":[\"sweep\",\"dust\",\"floor\"]},"
    "{\"id\":\"A2\",\"verb\":null,\"verb_class\":null,\"object\":\"행주\","
    "\"object_detail\":null,\"instrument\":null,\"location\":null,"
    "\"is_object_card\":true,"
    "\"keywords_ko\":[\"마른행주\",\"천\",\"수건\",\"걸레\"],"
    "\"keywords_en\":[\"dishcloth\",\"cloth\",\"rag\"]},"
    "{\"id\":\"A3\",\"verb\":\"준비하다\",\"verb_class\":\"other\",\"object\":\"봉투\","
    "\"object_detail\":\"빈 포장\",\"instrument\":null,\"location\":null,"
    "\"is_object_card\":false,"
    "\"keywords_ko\":[\"챙기다\",\"꺼내놓다\",\"마련하다\",\"비닐\",\"포대\"],"
    "\"keywords_en\":[\"prepare\",\"bag\",\"pouch\"]}]}\n"
    "\n위 예시에서 keywords_ko에 '쓸다','먼지','바닥','행주','준비하다','봉투'가 "
    "**없는 것**을 보세요. 라벨에 이미 있는 말이기 때문입니다."
)


def load_dotenv() -> None:
    """저장소 루트 .env를 환경변수로 올린다(이미 설정된 값은 덮지 않는다)."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def source_digest(assets: list[dict]) -> str:
    """원본 자산의 id+label 해시. 인덱스가 어떤 원본에서 나왔는지 추적한다."""
    payload = "\n".join(f"{a['id']}\t{a.get('label','')}" for a in assets)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# 관형어(수식어)로 쓰이는 단어들. '빈 박스'의 '빈'처럼 대상 앞에 붙어 범위를 좁힌다.
_DETERMINERS = {"빈", "새", "헌", "같은", "다른", "모든", "각", "여러", "정해진", "해당"}
# 용언이 관형형으로 바뀔 때의 어미. '완성된', '사용한', '포장할', '남은' 등.
_ADNOMINAL_ENDINGS = ("된", "한", "할", "은", "는", "을", "린", "운", "긴")


def _has_modifier(obj: str) -> bool:
    """object에 수식어가 남았는지 본다.

    '부품 상자', '작업 지시서'처럼 띄어 쓰는 복합명사는 그 자체가 대상이므로 통과시킨다.
    걸러야 할 것은 '빈 포장 봉투', '완성된 음료'처럼 앞에 관형어가 붙은 경우다.
    """
    parts = obj.split()
    if len(parts) == 1:
        return False
    if len(parts) >= 3:
        return True  # 세 단어 이상이면 복합명사로 보기 어렵다.
    head = parts[0]
    return head in _DETERMINERS or head.endswith(_ADNOMINAL_ENDINGS)


def validate(item: dict, known: dict[str, dict]) -> list[str]:
    """LLM 출력 한 건을 검사한다. 문제를 문자열 목록으로 돌려준다(빈 목록이면 통과)."""
    problems: list[str] = []
    asset_id = item.get("id")
    if asset_id not in known:
        return [f"모르는 id: {asset_id!r}"]

    is_object = bool(item.get("is_object_card"))
    verb = item.get("verb")
    verb_class = item.get("verb_class")

    if is_object:
        if verb or verb_class:
            problems.append("사물 카드인데 verb/verb_class가 있다")
    else:
        if not verb:
            problems.append("동작 카드인데 verb가 없다")
        if verb_class not in VERB_CLASSES:
            problems.append(f"알 수 없는 verb_class: {verb_class!r}")

    obj = item.get("object")
    if not obj:
        problems.append("object가 비었다")
    elif _has_modifier(str(obj)):
        # 수식어가 붙으면 대상 매칭이 흐려진다("빈 포장 봉투" 대신 "봉투"여야 한다).
        # 단 '부품 상자', '작업 지시서'처럼 띄어 쓰는 복합명사는 그대로 둔다.
        problems.append(f"object에 수식어가 남았다: {obj!r}")

    for field in ("keywords_ko", "keywords_en"):
        values = item.get(field)
        if not isinstance(values, list) or not values:
            problems.append(f"{field}가 비었다")

    # 라벨 단어만 되풀이한 검색어는 값이 없다(라벨은 이미 매칭 대상이다).
    # 전부 겹칠 때만 되돌린다 — 서술형 라벨(assembly)은 내용어가 겹칠 수밖에 없다.
    label = known[asset_id].get("label", "")
    ko = [k for k in (item.get("keywords_ko") or []) if isinstance(k, str)]
    if ko and all(k in label for k in ko):
        problems.append(f"keywords_ko가 라벨을 그대로 되풀이한다({len(ko)}개 전부)")
    return problems


def build_batch(batch: list[dict], known: dict[str, dict]) -> list[dict]:
    """한 배치를 LLM에 보내고 검증까지 통과한 항목만 돌려준다."""
    import llm

    payload = [
        {"id": a["id"], "job": a.get("job", ""), "asset_type": a.get("asset_type", ""),
         "label": a.get("label", "")}
        for a in batch
    ]
    user = "다음 카드들을 구조화하세요:\n" + json.dumps(payload, ensure_ascii=False)
    raw = llm.chat_json(_SYSTEM, user, max_tokens=4000)

    items = raw.get("items")
    if not isinstance(items, list):
        raise ValueError("응답에 items 배열이 없다")

    # LLM이 배치에서 항목을 조용히 빠뜨리는 일이 있다. 검증 탈락과 달리 로그에 안 남아
    # 전체 개수가 모자란 이유를 알 수 없게 된다. 여기서 드러낸다.
    returned = {i.get("id") for i in items if isinstance(i, dict)}
    dropped = [a["id"] for a in batch if a["id"] not in returned]
    if dropped:
        print(f"    [응답 누락 {len(dropped)}건] {', '.join(dropped[:5])}"
              f"{' ...' if len(dropped) > 5 else ''}")

    out: list[dict] = []
    for item in items:
        problems = validate(item, known)
        if problems:
            print(f"    [건너뜀] {item.get('id')}: {'; '.join(problems)}")
            continue
        asset = known[item["id"]]
        out.append({
            "id": item["id"],
            "label": asset.get("label", ""),
            "job": asset.get("job", ""),
            "asset_type": asset.get("asset_type", ""),
            "frame": {
                "verb": item.get("verb"),
                "verb_class": item.get("verb_class"),
                "object": item.get("object"),
                "object_detail": item.get("object_detail"),
                "instrument": item.get("instrument"),
                "location": item.get("location"),
                "is_object_card": bool(item.get("is_object_card")),
            },
            "keywords_ko": item["keywords_ko"],
            "keywords_en": item["keywords_en"],
            "reviewed": False,  # 사람 검수 표시. 검수 후 true로 바꾼다.
        })
    return out


def write_index(entries: dict[str, dict], assets: list[dict], model: str) -> None:
    INDEX_PATH.write_text(json.dumps({
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "source_digest": source_digest(assets),
        "source_count": len(assets),
        "entry_count": len(entries),
        "note": (
            "LLM이 생성한 파생 데이터입니다. 원본은 aac_assets.json이며 이 파일은 "
            "재생성 가능합니다. reviewed=false는 사람 검수 전이라는 뜻입니다."
        ),
        "entries": [entries[a["id"]] for a in assets if a["id"] in entries],
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="AAC 자산 라벨 구조화 인덱스 생성")
    ap.add_argument("--limit", type=int, help="앞에서 N건만 처리(시험용)")
    ap.add_argument("--job", help="특정 직무만 처리")
    ap.add_argument("--resume", action="store_true", help="기존 인덱스에 없는 것만 처리")
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = ap.parse_args()

    load_dotenv()
    import llm
    if not llm.llm_available():
        raise SystemExit("OPENAI_API_KEY가 없습니다(.env 또는 환경변수).")

    assets = json.loads(ASSETS_PATH.read_text(encoding="utf-8"))["assets"]
    known = {a["id"]: a for a in assets}

    entries: dict[str, dict] = {}
    if args.resume and INDEX_PATH.exists():
        old = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        entries = {e["id"]: e for e in old.get("entries", [])}
        print(f"기존 인덱스 {len(entries)}건에서 이어서 진행합니다.")

    targets = [a for a in assets if not args.job or a.get("job") == args.job]
    if args.resume:
        targets = [a for a in targets if a["id"] not in entries]
    if args.limit:
        targets = targets[: args.limit]

    if not targets:
        print("처리할 자산이 없습니다.")
        return

    batches = [targets[i:i + args.batch_size] for i in range(0, len(targets), args.batch_size)]
    print(f"대상 {len(targets)}건 / 배치 {len(batches)}개 (모델 {llm.OPENAI_MODEL})")

    failed_batches = 0
    for i, batch in enumerate(batches, start=1):
        print(f"  [{i}/{len(batches)}] {batch[0]['id']} ~ {batch[-1]['id']}", flush=True)
        for attempt in (1, 2):
            try:
                for entry in build_batch(batch, known):
                    entries[entry["id"]] = entry
                break
            except Exception as e:  # noqa: BLE001 - 배치 단위로 재시도하고 넘어간다
                print(f"    실패(시도 {attempt}): {e}")
                if attempt == 2:
                    failed_batches += 1
                else:
                    time.sleep(2)
        # 중단돼도 지금까지 것을 잃지 않도록 배치마다 저장한다.
        write_index(entries, assets, llm.OPENAI_MODEL)

    print(f"\n인덱스 {len(entries)}/{len(assets)}건 저장: {INDEX_PATH}")
    if failed_batches:
        print(f"실패한 배치 {failed_batches}개 — --resume 으로 다시 시도하세요.")


if __name__ == "__main__":
    main()
