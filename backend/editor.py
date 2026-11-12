"""사업주 편집기 API(2b-1, contract §3.4). main.py에서는 include만 한다.

- POST /api/tasks/{id}/pictures/confirm: [보이는 자동 그림 모두 맞아요] 일괄 확인. 확인할 수 없는 단계가 섞이면 422,
  아무것도 바꾸지 않는다(원자성). 이미 확인한 단계는 그대로 둔다(다시 눌러도 같은 결과).
- POST /api/tasks/{id}/steps/{sid}/picture: 후보·검색 결과 적용 → 확인함(confirmed).
- GET  /api/tasks/{id}/candidates: 모든 단계의 그림 후보(최대 3)를 한 번에. **유료 모델 없이** — ai_service에
  context.rerank=false를 넘겨 GPT 재순위를 끈다(contract §3.3). 생성 때 후보 순서(GPT가 앞으로 올린 그림이 맨 앞,
  steps.symbol_candidates)를 먼저 두고 규칙 검색 결과로 채운다(그림 정확도 ②).
- POST /api/tasks/{id}/steps/{sid}/tts: [목소리 듣기]. 음성이 없거나 옛 문장이면 그때 합성한다(트랜잭션 밖, step_audio).
- GET  /api/tasks/{id}/preview: 미리보기(근로자 Step 모양 + 조심·묶음 경계). 기록·감사를 남기지 않는다.
이 모듈은 main을 import하지 않는다.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import ai_client
import media
import step_audio
import versions
from aac_assets import _labels, asset_label, card_id_from_url, public_aac_url
from auth import require_employer
from database import get_db
from models import Step, Task
from privacy import employer_pseudonymizer
from schemas import (
    CandidateOut,
    EditorStepOut,
    PictureApply,
    PicturesConfirm,
    PreviewOut,
    StepCandidatesOut,
    TaskCandidatesOut,
    TtsOut,
)
from send import ApiError, _owned_task
from step_context import _is_own_image_url, _step_search_terms, _task_context, stored_candidates

router = APIRouter()

MAX_CANDIDATES = 3
_WORKERS = int(os.getenv("STEP_PREP_WORKERS", "8"))

MSG_STEP_NOT_FOUND = "단계를 찾을 수 없습니다."
MSG_NOT_OUR_PICTURE = "이 서비스의 그림만 붙일 수 있어요. 사진은 [현장 사진 올리기]로 올려 주세요."
MSG_CARD_MISMATCH = "그림 정보가 맞지 않아요. 후보를 새로 불러온 뒤 다시 골라 주세요."
# 일괄 확인에서 확인할 수 없는 상태의 이름(오류 문구 예: 3단계(골라 주세요)).
_STATE_NAMES = {"choose": "골라 주세요", "none": "그림 없음"}


def _owned_step(task: Task, step_id: str) -> Step:
    step = next((s for s in task.steps if s.id == step_id), None)
    if step is None:
        raise HTTPException(status_code=404, detail=MSG_STEP_NOT_FOUND)
    return step


# --- 일괄 확인 ---------------------------------------------------------------------------------

@router.post("/api/tasks/{task_id}/pictures/confirm", response_model=list[EditorStepOut])
def confirm_pictures(task_id: str, payload: PicturesConfirm, db: Session = Depends(get_db),
                     user: dict = Depends(require_employer)) -> list[EditorStepOut]:
    task = _owned_task(task_id, user["sub"], db)
    by_id = {s.id: s for s in task.steps}
    ids = list(dict.fromkeys(payload.step_ids))
    if any(i not in by_id for i in ids):
        raise HTTPException(status_code=404, detail=MSG_STEP_NOT_FOUND)
    states = {i: versions.picture_state(by_id[i]) for i in ids}
    bad = sorted((by_id[i] for i in ids if states[i] not in ("auto_high", "confirmed")),
                 key=lambda s: s.order_index)
    if bad:
        names = ", ".join(f"{s.order_index}단계({_STATE_NAMES[states[s.id]]})" for s in bad)
        raise ApiError(422, f"확인할 수 없는 단계가 있어요: {names}", code="not_confirmable",
                       step_ids=[s.id for s in bad])
    for i in ids:
        if states[i] == "auto_high":
            by_id[i].picture_confirmed = True
    db.commit()
    db.refresh(task)
    return [versions.step_to_out(by_id[i]) for i in ids]


# --- 후보·검색 결과 적용 -----------------------------------------------------------------------

def _relative_aac_path(url: str) -> str:
    base = os.getenv("PUBLIC_BACKEND_URL", "http://localhost:8000").rstrip("/")
    return url[len(base):] if url.startswith(base + "/") else url


@router.post("/api/tasks/{task_id}/steps/{step_id}/picture", response_model=EditorStepOut)
def apply_picture(task_id: str, step_id: str, payload: PictureApply, db: Session = Depends(get_db),
                  user: dict = Depends(require_employer)) -> EditorStepOut:
    """후보(GET …/candidates)나 검색 결과(POST /api/aac/search)를 단계에 붙인다. 사업주가 고른 것이라 바로 확인함이다.
    사진(media URL)은 받지 않는다(사진은 …/photo로 올린다). label은 받아도 저장하지 않는다(자산 목록에서 찾는다)."""
    task = _owned_task(task_id, user["sub"], db)
    step = _owned_step(task, step_id)
    url = payload.url.strip()
    if media.parse_media_url(url) is not None or not _is_own_image_url(url):
        raise HTTPException(status_code=400, detail=MSG_NOT_OUR_PICTURE)
    card_id = card_id_from_url(url)
    if card_id != payload.card_id.strip() or (_labels() and not asset_label(card_id)):
        raise HTTPException(status_code=400, detail=MSG_CARD_MISMATCH)
    released = [step.symbol_media_id] if step.symbol_media_id else []
    step.symbol_media_id = None
    step.symbol_url = public_aac_url(_relative_aac_path(url))
    step.symbol_source = versions.SOURCE_MANUAL_PICK
    step.needs_fallback = False
    step.picture_confirmed = True
    db.commit()
    media.release(db, released)
    db.refresh(step)
    return versions.step_to_out(step)


# --- 모든 단계 후보 ----------------------------------------------------------------------------

def _is_accepted(result: dict) -> bool:
    symbols = result.get("symbols") or []
    return bool(symbols) and symbols[0].get("reason") == "accepted" and bool(symbols[0].get("image_url"))


def stored_as_matches(step: Step) -> list[dict]:
    """생성 때 후보(steps.symbol_candidates)를 ai_service 후보 모양으로. 점수는 없다(화면에 숫자를 보이지 않는다)."""
    return [{"asset_id": cid, "group_id": cid, "job": "", "asset_type": "action", "label": label,
             "image_url": rel, "score": 0.0} for cid, rel, label in stored_candidates(step)]


def candidates_from_symbols(result: dict, extra: list[dict] | None = None,
                            first: list[dict] | None = None) -> list[CandidateOut]:
    """ai_service map-symbols 결과 → 후보 최대 3장. 자동 채택이면 채택한 그림이 맨 앞이다.

    first(생성 때 후보 순서)가 있으면 그것을 맨 앞에 둔다 — 지금 검색은 규칙만이라 생성 때 GPT가 앞으로 올린 그림이
    뒤로 밀리거나 빠진다. 자동 채택한 단계는 map-symbols가 후보 목록을 주지 않으므로(채택 그림 하나), 그 뒤를 같은
    맥락의 그림 검색 결과(extra, /ai/aac/search — 규칙 검색, GPT 없음)로 채운다."""
    symbols = result.get("symbols") or []
    sym = symbols[0] if symbols else {}
    raw = list(first or []) + list(sym.get("candidates") or []) + list(extra or [])
    if sym.get("reason") == "accepted" and sym.get("image_url"):
        accepted_id = sym.get("external_id") or card_id_from_url(sym.get("image_url"))
        if not any((c.get("asset_id") or card_id_from_url(c.get("image_url"))) == accepted_id for c in raw):
            raw.insert(len(first or []), {"asset_id": accepted_id, "label": sym.get("resolved_keyword", ""),
                                          "image_url": sym.get("image_url")})
    out: list[CandidateOut] = []
    seen: set[str] = set()
    for c in raw:
        url = public_aac_url(c.get("image_url"))
        card_id = c.get("asset_id") or card_id_from_url(url)
        if not url or not card_id or card_id in seen:
            continue
        seen.add(card_id)
        out.append(CandidateOut(card_id=card_id, url=url, label=str(c.get("label") or asset_label(card_id))))
        if len(out) >= MAX_CANDIDATES:
            break
    return out


def search_context(context: dict) -> dict:
    """그림 검색(/ai/aac/search)에 넘길 맥락 — rerank 같은 map-symbols 전용 칸은 뺀다."""
    return {k: v for k, v in context.items() if k != "rerank"}


def symbol_query(task: Task, step: Step, masker) -> tuple[list, dict]:
    """후보 조회 질의: 생성 때와 같은 검색어·맥락(별칭 적용) + rerank=false(유료 모델 끔)."""
    context = masker.mask_obj(_task_context(task, step.sentence, step.action_type))
    context["rerank"] = False
    return masker.mask_obj(_step_search_terms(step)), context


@router.get("/api/tasks/{task_id}/candidates", response_model=TaskCandidatesOut)
def task_candidates(task_id: str, db: Session = Depends(get_db),
                    user: dict = Depends(require_employer)) -> TaskCandidatesOut:
    """모든 단계(확인한 단계 포함)의 그림 후보. 생성 때 후보 순서를 앞에 두고, 모자라면 그때그때 규칙으로 찾아 채운다.
    생성 때 후보가 3장이면 다시 찾지 않는다."""
    task = _owned_task(task_id, user["sub"], db)
    steps = sorted(task.steps, key=lambda s: s.order_index)
    masker = employer_pseudonymizer(db, user["sub"])
    queries = [(s.id, *symbol_query(task, s, masker), stored_as_matches(s)) for s in steps]
    db.commit()  # 그림 검색(네트워크) 동안 읽기 트랜잭션도 쥐지 않는다

    def run(q):
        if len(q[3]) >= MAX_CANDIDATES:
            return {}, None
        result = ai_client.map_symbols(q[1], context=q[2])
        extra = None
        if _is_accepted(result):
            ctx = search_context(q[2])
            query = str(ctx.get("sentence") or " ".join(q[1])).strip()
            if query:
                extra = ai_client.search_aac(query, context=ctx, limit=MAX_CANDIDATES + 1).get("matches")
        return result, extra

    if len(queries) > 1:
        with ThreadPoolExecutor(max_workers=min(_WORKERS, len(queries))) as pool:
            results = list(pool.map(run, queries))
    else:
        results = [run(q) for q in queries]
    return TaskCandidatesOut(steps=[StepCandidatesOut(step_id=q[0], candidates=candidates_from_symbols(r, extra, q[3]))
                                    for q, (r, extra) in zip(queries, results)])


# --- 목소리 듣기 ---------------------------------------------------------------------------------

@router.post("/api/tasks/{task_id}/steps/{step_id}/tts", response_model=TtsOut)
def step_tts(task_id: str, step_id: str, db: Session = Depends(get_db),
             user: dict = Depends(require_employer)) -> TtsOut:
    task = _owned_task(task_id, user["sub"], db)
    step = _owned_step(task, step_id)
    sid = step.id
    step_audio.refresh(db, user["sub"], [step], include_missing=True)
    step = db.get(Step, sid)
    if step is None or step.tts_stale or step.tts_media is None:
        return TtsOut(tts_url=None)
    return TtsOut(tts_url=media.signed_url(step.tts_media.id))


# --- 미리보기 -----------------------------------------------------------------------------------

@router.get("/api/tasks/{task_id}/preview", response_model=PreviewOut)
def task_preview(task_id: str, db: Session = Depends(get_db),
                 user: dict = Depends(require_employer)) -> PreviewOut:
    """근로자 화면처럼 미리 본다. 배정·수행 기록·도움·열람 감사를 만들지 않는다(근로자 개인 데이터를 읽지 않는다)."""
    task = _owned_task(task_id, user["sub"], db)
    steps = sorted(task.steps, key=lambda s: s.order_index)
    return PreviewOut(title=task.title, steps=[versions.preview_step_out(s) for s in steps])
