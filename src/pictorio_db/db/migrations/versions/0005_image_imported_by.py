# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Who imported each image; empty once that user is deleted."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite cannot add a foreign key to an existing table; batch mode copies the table instead.
    with op.batch_alter_table("image") as image_table:
        image_table.add_column(sa.Column("imported_by_user_id", sa.Integer(), nullable=True))
        image_table.create_foreign_key(
            "fk_image_imported_by_user_id_user", "user", ["imported_by_user_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("image") as image_table:
        image_table.drop_constraint("fk_image_imported_by_user_id_user", type_="foreignkey")
        image_table.drop_column("imported_by_user_id")
