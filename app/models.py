from datetime import datetime
from sqlalchemy import String, Integer, BigInteger, DateTime, Text, Float, Boolean, JSON, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class Recording(Base):
    __tablename__ = 'qc_recordings'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    object_key: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    etag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    device_id: Mapped[str] = mapped_column(String(128), default='unknown', index=True)
    filename: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    last_modified: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default='PENDING', index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    detected_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Transcript(Base):
    __tablename__ = 'qc_transcriptions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recording_id: Mapped[int] = mapped_column(Integer, index=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    segments: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Analysis(Base):
    __tablename__ = 'qc_analysis'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recording_id: Mapped[int] = mapped_column(Integer, index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    risk_level: Mapped[str] = mapped_column(String(32), default='REVIEW')
    summary: Mapped[str] = mapped_column(Text, default='')
    result: Mapped[dict] = mapped_column(JSON)
    model_name: Mapped[str] = mapped_column(String(128), default='rules-only')
    human_review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class TranscriptComparison(Base):
    __tablename__ = 'qc_qwen_transcripts'
    recording_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    status: Mapped[str] = mapped_column(String(16), index=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    claim: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Employee(Base):
    __tablename__ = 'qc_employees'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    team: Mapped[str] = mapped_column(String(128), default='')
    device_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Rule(Base):
    __tablename__ = 'qc_rules'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(32))
    keywords: Mapped[list] = mapped_column(JSON)
    deduction: Mapped[int] = mapped_column(Integer, default=10)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
