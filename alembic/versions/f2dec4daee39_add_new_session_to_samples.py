"""add new_session to samples

Guarded with an existence check (see 166cdc6b527a for why) rather than a
plain op.add_column — harmless for this column specifically (it's brand
new, no real pre-Alembic DB ever had it), but keeps this migration correct
if it's ever replayed against a DB whose schema was seeded from a snapshot
of the live models rather than the actual migration chain (e.g. test
fixtures using Base.metadata.create_all()). server_default is required
here (unlike the nullable session_id column) since SQLite can't add a
NOT NULL column to a non-empty table without one.

Revision ID: f2dec4daee39
Revises: 413fdf8ac970
Create Date: 2026-07-28 15:26:25.739167

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f2dec4daee39'
down_revision: str | Sequence[str] | None = '413fdf8ac970'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    samples_cols = {c["name"] for c in inspector.get_columns("samples")}
    if "new_session" not in samples_cols:
        op.add_column(
            "samples",
            sa.Column("new_session", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('samples', 'new_session')
