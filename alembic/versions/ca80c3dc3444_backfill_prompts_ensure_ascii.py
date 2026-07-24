"""backfill prompts ensure ascii

prompts_sent_json used to be written with ensure_ascii (default), so
non-ASCII prompts were stored as \\uXXXX escapes and the batch search LIKE
could never match a Chinese query. Re-dump any still-escaped rows as
literal UTF-8. This used to run unconditionally on every single app boot
(storage/database.py::_backfill_prompts_ensure_ascii, an unindexed
full-table LIKE scan of `samples`) — moved here so it runs exactly once,
tracked like any other migration.

Revision ID: ca80c3dc3444
Revises: e40685cf4319
Create Date: 2026-07-23 11:49:36.538823

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ca80c3dc3444"
down_revision: str | Sequence[str] | None = "e40685cf4319"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT batch_id, id, prompts_sent_json FROM samples "
            "WHERE prompts_sent_json LIKE '%\\u%'"
        )
    ).fetchall()
    for batch_id, sample_id, raw in rows:
        try:
            fixed = json.dumps(json.loads(raw), ensure_ascii=False)
        except (TypeError, ValueError):
            continue
        if fixed != raw:
            conn.execute(
                sa.text(
                    "UPDATE samples SET prompts_sent_json = :v WHERE batch_id = :b AND id = :s"
                ),
                {"v": fixed, "b": batch_id, "s": sample_id},
            )


def downgrade() -> None:
    """Data-only migration; nothing to reverse."""
