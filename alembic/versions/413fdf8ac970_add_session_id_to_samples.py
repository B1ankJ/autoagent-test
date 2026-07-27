"""add session_id to samples

Guarded with an existence check (see 166cdc6b527a for why) rather than a
plain op.add_column/create_index — harmless for this column specifically
(it's brand new, no real pre-Alembic DB ever had it), but keeps this
migration correct if it's ever replayed against a DB whose schema was
seeded from a snapshot of the live models rather than the actual migration
chain (e.g. test fixtures using Base.metadata.create_all()).

Revision ID: 413fdf8ac970
Revises: 166cdc6b527a
Create Date: 2026-07-27 15:50:26.177311

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '413fdf8ac970'
down_revision: str | Sequence[str] | None = '166cdc6b527a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    samples_cols = {c["name"] for c in inspector.get_columns("samples")}
    if "session_id" not in samples_cols:
        op.add_column("samples", sa.Column("session_id", sa.String(), nullable=True))

    samples_idx = {ix["name"] for ix in inspector.get_indexes("samples")}
    if "ix_samples_session_id" not in samples_idx:
        op.create_index(op.f("ix_samples_session_id"), "samples", ["session_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_samples_session_id'), table_name='samples')
    op.drop_column('samples', 'session_id')
