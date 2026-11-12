# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Each user's preferences: the hidden-by-default search filters."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_pref",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("hidden_filters", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_user_pref_user_id_user", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_pref"),
    )


def downgrade() -> None:
    op.drop_table("user_pref")
