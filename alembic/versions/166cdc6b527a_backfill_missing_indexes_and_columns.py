"""backfill missing indexes and columns

Baseline drifted behind models/db.py — Batch.samples_request_json and the
Batch.status / Sample.status / Sample.target_profile indexes were added to
the model in prior (pre-Alembic) work but never got a real migration, so
any DB that went through the actual migration chain (as opposed to the
fresh-DB create_all() fast path, which always matches models/db.py exactly)
was missing them. Caught while generating the session_id migration in the
next revision — split out separately so each migration stays one logical
change.

Guarded with existence checks rather than plain op.add_column/create_index:
a *real* legacy (pre-Alembic) DB already has these — they were added by the
old hand-rolled PRAGMA-table-info-based migration code this project used
before switching to Alembic, well before this revision existed — so
init_db()'s "stamp to baseline, then upgrade" path for such a DB would hit
"duplicate column"/"index already exists" without the guard.

Revision ID: 166cdc6b527a
Revises: ca80c3dc3444
Create Date: 2026-07-27 15:44:02.676973

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '166cdc6b527a'
down_revision: str | Sequence[str] | None = 'ca80c3dc3444'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    batches_cols = {c["name"] for c in inspector.get_columns("batches")}
    if "samples_request_json" not in batches_cols:
        op.add_column("batches", sa.Column("samples_request_json", sa.Text(), nullable=True))

    batches_idx = {ix["name"] for ix in inspector.get_indexes("batches")}
    if "ix_batches_status" not in batches_idx:
        op.create_index(op.f("ix_batches_status"), "batches", ["status"], unique=False)

    samples_idx = {ix["name"] for ix in inspector.get_indexes("samples")}
    if "ix_samples_status" not in samples_idx:
        op.create_index(op.f("ix_samples_status"), "samples", ["status"], unique=False)
    if "ix_samples_target_profile" not in samples_idx:
        op.create_index(
            op.f("ix_samples_target_profile"), "samples", ["target_profile"], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_samples_target_profile'), table_name='samples')
    op.drop_index(op.f('ix_samples_status'), table_name='samples')
    op.drop_index(op.f('ix_batches_status'), table_name='batches')
    op.drop_column('batches', 'samples_request_json')
