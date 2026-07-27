from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func
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
    # Indexed: count_batches_by_status GROUP BYs it, and list/stats queries
    # filter on it (e.g. the retention-prune "terminal batches" scan).
    status = Column(
        String, nullable=False, default="queued", index=True
    )  # queued|running|done|failed|cancelled
    concurrency = Column(Integer, nullable=False, default=1)
    total = Column(Integer, nullable=False, default=0)
    done = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    avg_duration_ms = Column(Integer, nullable=True)
    total_duration_ms = Column(Integer, nullable=True)
    target_profile_default = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    # Index because every list/count/stats query orders by it desc;
    # without one SQLite full-scans as the batches table grows.
    created_at = Column(DateTime, server_default=func.now(), index=True)
    # Verbatim JSON of the originally-submitted Sample list (id, prompts,
    # new_session, timeout_sec, retry, dry_run, callback_url, metadata — the
    # full request, not just what SampleResult persists post-execution).
    # Written once at submission time so /replay can resubmit an identical
    # batch; NULL for batches created before this existed.
    samples_request_json = Column(Text, nullable=True)


class Sample(Base):
    __tablename__ = "samples"
    batch_id = Column(String, primary_key=True)
    id = Column(String, primary_key=True)
    # Indexed: the empty_response_only / status filters join+filter Sample
    # across the whole table (not scoped to one batch_id) when applied
    # batch-wide, e.g. from the dashboard stats query.
    status = Column(
        String, nullable=False, default="queued", index=True
    )  # queued|running|done|failed|timeout|extraction_failed|cancelled
    prompts_sent_json = Column(Text, nullable=True)
    responses_json = Column(Text, nullable=True)
    llm_responses_json = Column(Text, nullable=True)
    llm_errors_json = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    mode = Column(String, nullable=False)
    # Indexed: list_batches/count_batches_by_status filter on it whenever
    # target_profile is supplied.
    target_profile = Column(String, nullable=False, index=True)
    metadata_json = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    logs_dir = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    # Indexed: reconstructing a multi-turn conversation queries across the
    # whole table (a session's turns are typically scattered across many
    # separate single-sample batches, not one batch). NULL for the
    # overwhelming majority of samples that never set Sample.session_id.
    session_id = Column(String, nullable=True, index=True)


class Device(Base):
    __tablename__ = "devices"
    serial = Column(String, primary_key=True)
    label = Column(String, nullable=True)
    model = Column(String, nullable=True)
    android_version = Column(String, nullable=True)
    adb_keyboard_installed = Column(Boolean, nullable=True)
    adb_keyboard_enabled = Column(Boolean, nullable=True)
    online = Column(Boolean, nullable=False, default=False)
    enabled = Column(Boolean, nullable=False, default=True)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class ConfigKV(Base):
    __tablename__ = "configs"
    key = Column(String, primary_key=True)
    value_json = Column(Text, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
