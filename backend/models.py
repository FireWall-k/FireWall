"""ORM 모델.

엔티티: Employer, Worker, Task, Step, Assignment, PerformanceLog.
변경점(평가 반영):
- Employer.login_id/password_hash, Worker.access_code 추가 → 인증 가능
- 모든 FK에 index=True (조회 성능)
- PerformanceLog(assignment_id, step_id) UNIQUE → 단계당 1로그 보장(업서트)
- 미사용 SymbolAsset 테이블 제거(死 코드 정리). 자체 상징 DB는 도입 시점에 재설계한다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Employer(Base):
    __tablename__ = "employers"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, default="")
    org_name: Mapped[str] = mapped_column(String, default="")
    login_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    tasks: Mapped[list["Task"]] = relationship(back_populates="employer")
    workers: Mapped[list["Worker"]] = relationship(back_populates="employer")


class Worker(Base):
    __tablename__ = "workers"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    employer_id: Mapped[str] = mapped_column(ForeignKey("employers.id"), index=True)
    display_name: Mapped[str] = mapped_column(String, default="근로자")
    # 발달장애인 근로자는 비밀번호 대신 짧은 접속 코드로 로그인한다(현장 디바이스 공유 가정).
    access_code: Mapped[str] = mapped_column(String, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    employer: Mapped["Employer"] = relationship(back_populates="workers")


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    employer_id: Mapped[str] = mapped_column(ForeignKey("employers.id"), index=True)
    title: Mapped[str] = mapped_column(String, default="")
    raw_input: Mapped[str] = mapped_column(Text, default="")
    # draft -> published -> archived
    status: Mapped[str] = mapped_column(String, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    employer: Mapped["Employer"] = relationship(back_populates="tasks")
    steps: Mapped[list["Step"]] = relationship(
        back_populates="task", order_by="Step.order_index",
        cascade="all, delete-orphan",
    )


class Step(Base):
    __tablename__ = "steps"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer)
    sentence: Mapped[str] = mapped_column(Text)
    action_type: Mapped[str] = mapped_column(String, default="other")
    symbol_url: Mapped[str | None] = mapped_column(String, nullable=True)
    symbol_source: Mapped[str] = mapped_column(String, default="fallback")
    needs_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    tts_audio_url: Mapped[str | None] = mapped_column(String, nullable=True)

    task: Mapped["Task"] = relationship(back_populates="steps")


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"), index=True)
    assigned_date: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    status: Mapped[str] = mapped_column(String, default="assigned")


class PerformanceLog(Base):
    __tablename__ = "performance_logs"
    __table_args__ = (
        UniqueConstraint("assignment_id", "step_id", name="uq_log_assignment_step"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id"), index=True)
    step_id: Mapped[str] = mapped_column(ForeignKey("steps.id"), index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    replay_count: Mapped[int] = mapped_column(Integer, default=0)
    stuck: Mapped[bool] = mapped_column(Boolean, default=False)
