from sqlalchemy import Column, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    username = Column(String, primary_key=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class Batch(Base):
    __tablename__ = "batches"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    mode = Column(String, nullable=False)
    status = Column(String, nullable=False, default="queued")  # queued|running|done|failed|cancelled
    concurrency = Column(Integer, nullable=False, default=1)
    total = Column(Integer, nullable=False, default=0)
    done = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    avg_duration_ms = Column(Integer, nullable=True)
    total_duration_ms = Column(Integer, nullable=True)
    target_profile_default = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class Sample(Base):
    __tablename__ = "samples"
    batch_id = Column(String, primary_key=True)
    id = Column(String, primary_key=True)
    status = Column(String, nullable=False, default="queued")  # queued|running|done|failed|timeout|extraction_failed|cancelled
    prompts_sent_json = Column(Text, nullable=True)
    responses_json = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    mode = Column(String, nullable=False)
    target_profile = Column(String, nullable=False)
    metadata_json = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    logs_dir = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)


class ConfigKV(Base):
    __tablename__ = "configs"
    key = Column(String, primary_key=True)
    value_json = Column(Text, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
