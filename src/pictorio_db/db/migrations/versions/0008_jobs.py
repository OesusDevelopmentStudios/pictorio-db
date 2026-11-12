# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Long tasks for the background worker, with their progress and results."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("progress_done", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name="ck_job_status"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_job_created_by_user", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_job"),
    )
    op.create_index("ix_job_status_id", "job", ["status", "id"])


def downgrade() -> None:
    op.drop_index("ix_job_status_id", table_name="job")
    op.drop_table("job")
