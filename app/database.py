import os
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, Float, Integer, String, Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////data/metrics.db")

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Repository(Base):
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False)
    url = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class CommitAnalysis(Base):
    __tablename__ = "commit_analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_name = Column(String(255), nullable=False, index=True)
    commit_sha = Column(String(40), nullable=False, index=True)
    branch = Column(String(255), default="main")
    author = Column(String(255))
    message = Column(Text)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # --- metrics ---
    total_lines = Column(Integer, default=0)
    lines_added = Column(Integer, default=0)
    lines_deleted = Column(Integer, default=0)
    files_changed = Column(Integer, default=0)
    complexity_avg = Column(Float, default=0.0)
    maintainability_index = Column(Float, default=0.0)
    quality_score = Column(Float, default=0.0)  # 0-100

    # --- integrity ---
    integrity_hash = Column(String(64))
    integrity_status = Column(String(20), default="pending")  # pending | pass | fail

    # --- claude review ---
    claude_review = Column(Text, default="")
    md_report = Column(Text, default="")
    deprecation_warnings = Column(Text, default="")


class PushEvent(Base):
    __tablename__ = "push_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_name = Column(String(255), nullable=False)
    branch = Column(String(255), nullable=False)
    pusher = Column(String(255))
    commit_count = Column(Integer, default=0)
    head_sha = Column(String(40))
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    overall_score = Column(Float, default=0.0)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
