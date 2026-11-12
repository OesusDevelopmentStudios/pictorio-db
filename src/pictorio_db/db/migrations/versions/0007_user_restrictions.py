# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Restricted tags per user, set by an admin."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_restriction",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("term", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name="fk_user_restriction_user_id_user", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "term", name="pk_user_restriction"),
    )


def downgrade() -> None:
    op.drop_table("user_restriction")
