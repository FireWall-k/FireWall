"""단계 그림 검색 맥락과 그림 주소 검사(2b-1에 main.py에서 옮김).

main.py(직무 생성·단계 추가·후보 조회)와 editor.py(모든 단계 후보·그림 적용)가 같이 쓴다. 같은 맥락으로 검색해야
생성 때 판정과 후보 목록이 어긋나지 않는다. 이 모듈은 main을 import하지 않는다.
"""
from __future__ import annotations

import os
import posixpath
import re
from urllib.parse import unquote

from models import Step, Task


def _step_search_terms(step: "Step") -> list[str]:
    """단계의 AAC 검색어. 저장된 symbol_query가 있으면 그걸 쓴다(생성 때와 같은 질의),
    없으면 문장에서 뽑는다(사업주가 직접 추가했거나 문장을 수정한 경우)."""
    stored = [t.strip() for t in (step.symbol_query or "").split(",") if t.strip()]
    if stored:
        return stored[:4]
    terms = re.findall(r"[가-힣A-Za-z]+", step.sentence) or [step.sentence[:12]]
    return terms[:4]


def _task_context(task: Task, sentence: str, action_type: str) -> dict:
    """AAC 검색용 맥락. 직무 생성 시와 같은 조건을 재현한다.

    같은 문장이라도 업종 맥락이 있고 없고에 따라 순위와 채택 여부가 달라진다.
    생성·후보조회·단계추가가 모두 이 함수를 거쳐야 결과가 어긋나지 않는다.
    """
    return {
        "business_type": task.business_type or "",
        "work_environment": task.work_environment or "",

        "job": (
            (task.business_type or "")
            if (task.business_type or "").strip()
            else ""
        ),
        "job_hint": task.job or "",

        "sentence": sentence,
        "action_type": action_type,
        # 업종을 안 넣은 직무는 단계 문장 하나만으로 직무를 못 알아낼 때가 많다
        # ("큰 나사를 나누세요"만 봐서는 조립인지 알 수 없다). 원문 전체에는 대개
        # 직무를 알려주는 단어가 하나쯤 있다("부품 상자에서 나사를...") — AAC 검색의
        # infer_job()이 이걸 보조 신호로 쓴다.
        "raw_input": task.raw_input or "",
    }


# (Phase 0.3) 업로드 사진은 더 이상 경로 prefix로 받지 않는다. "/api/photos/"만 맞으면 다른 사업장의 사진 URL도
# 붙일 수 있었다. 사진은 아래 update_step에서 소유 레코드(MediaFile.employer_id)를 조회해 받는다.
_OWN_IMAGE_PATHS = ("/api/aac/images/",)


def _is_own_image_url(url: str) -> bool:
    """근로자 화면에 뜨는 그림은 이 서버가 내주는 AAC 이미지여야 한다(업로드 사진은 update_step이 따로 본다).

    아무 URL이나 받으면 외부 이미지(부적절한 그림, 접속 추적용 픽셀)가 근로자 화면에 뜬다.
    경로는 퍼센트 인코딩을 끝까지 푼 뒤 검사한다. 브라우저·프록시는 %2e%2e를 ..로, %2f를 /로 풀어 정규화하므로
    인코딩된 채로 보면 "/api/aac/images/%2e%2e/..."가 prefix 검사를 통과해 AAC 폴더 밖 경로를 가리킬 수 있다.
    이중 인코딩(%252e)도 있으니 더 바뀌지 않을 때까지 푼다. 정규화 결과가 원래 경로와 다르면(., .., //) 거부한다.
    """
    base = os.getenv("PUBLIC_BACKEND_URL", "http://localhost:8000").rstrip("/")
    path = url[len(base):] if url.startswith(base + "/") else url
    decoded = path
    for _ in range(5):
        nxt = unquote(decoded)
        if nxt == decoded:
            break
        decoded = nxt
    else:
        return False  # 다섯 번 풀어도 계속 바뀌는 경로는 정상 그림 URL이 아니다
    if any(ch in decoded for ch in ("\\", "\x00", "?", "#")) or "//" in decoded:
        return False
    # 제어 문자(탭·줄바꿈 등)는 브라우저 URL 파서가 지운 뒤 정규화한다. ".\t."은 여기서는 ".."이 아니지만
    # 브라우저에서는 ".."이 되어 AAC 폴더 밖 경로를 가리키므로, 정상 그림 경로에 없을 제어 문자는 통째로 거부한다.
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in decoded):
        return False
    if posixpath.normpath(decoded) != decoded or ".." in decoded.split("/"):
        return False
    return decoded.startswith(_OWN_IMAGE_PATHS)
