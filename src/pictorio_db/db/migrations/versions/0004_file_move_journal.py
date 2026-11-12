# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Journal of file moves in progress, so that a crash never loses track of a file."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "file_move",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("from_path", sa.String(), nullable=False),
        sa.Column("to_path", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["image_id"], ["image.id"], name="fk_file_move_image_id_image", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_file_move"),
    )


def downgrade() -> None:
    op.drop_table("file_move")
