"""단계 음성 다시 만들기(2b-1, contract §3.4·send 처리 순서 1).

- 600ms 자동 저장(PATCH …/steps/{sid}, defer_media=true)은 문장만 저장하고 tts_stale=1로 둔다.
- 음성은 [목소리 듣기](POST …/steps/{sid}/tts)와 보내기(send) 때 만든다. 합성(Google TTS, 네트워크·과금)은
  **DB 쓰기 트랜잭션 밖에서** 먼저 끝내고, 결과만 짧은 쓰기로 붙인다 — SQLite 쓰기 잠금은 DB 전체라, 합성 동안 쥐면
  근로자 기기의 기록 저장까지 기다린다.
- 합성에 실패하면 음성 없이 둔다(근로자·사업주 기기의 음성 합성이 대신 읽는다). tts_stale은 남겨 다음에 다시 시도한다.
- 합성하는 동안 문장이 또 바뀌었으면 그 결과는 붙이지 않는다(옛 문장 음성).
- 시험은 synthesize_tts를 모의로 바꾼다(conftest). 이 모듈은 main을 import하지 않는다.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import Session

import media
from models import Step
from tts import synthesize_tts

logger = logging.getLogger("jobcard.step_audio")

_WORKERS = int(os.getenv("STEP_PREP_WORKERS", "8"))


def needs_audio(step: Step, include_missing: bool = False) -> bool:
    if step.tts_stale:
        return True
    return include_missing and step.tts_media_id is None


def _synthesize(text: str, scope: str) -> str | None:
    try:
        return synthesize_tts(text, scope)
    except Exception:  # noqa: BLE001 - 음성은 없어도 된다(기기 음성이 대신)
        logger.warning("단계 음성 합성 실패 — 음성 없이 둔다", exc_info=True)
        return None


def refresh(db: Session, employer_id: str, steps, include_missing: bool = False) -> int:
    """steps 중 음성을 다시 만들어야 하는 단계를 합성해 붙인다. 붙인 수를 돌려준다.

    부르기 전에 이 세션에 쓰지 않은 변경이 없어야 한다(먼저 커밋해 읽기도 끝낸다). 합성은 잠금 없이 하고,
    결과를 붙이는 쓰기는 마지막에 한 번 커밋한다. 직무 updated_at(고친 날)은 바꾸지 않는다(models._only_media_changed).
    """
    targets = [(s.id, s.sentence) for s in steps if needs_audio(s, include_missing)]
    if not targets:
        return 0
    db.commit()  # 열린 트랜잭션을 끝낸다(합성 동안 아무 잠금도 쥐지 않는다)
    if len(targets) == 1:
        keys = [_synthesize(targets[0][1], employer_id)]
    else:
        with ThreadPoolExecutor(max_workers=min(_WORKERS, len(targets))) as pool:
            keys = list(pool.map(lambda t: _synthesize(t[1], employer_id), targets))
    released: list[str] = []
    applied = 0
    for (sid, sentence), key in zip(targets, keys):
        if not key:
            continue
        step = db.get(Step, sid)
        if step is None or step.sentence != sentence:
            continue  # 그사이 지웠거나 문장을 또 고쳤다 — 옛 문장 음성은 붙이지 않는다
        rec = media.create_record(db, employer_id, media.KIND_TTS, key)
        if rec is None:
            continue
        if step.tts_media_id and step.tts_media_id != rec.id:
            released.append(step.tts_media_id)
        step.tts_media_id = rec.id
        step.tts_stale = False
        applied += 1
    db.commit()
    if released:
        media.release(db, released)
    return applied
