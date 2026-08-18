"""宠物-主人相处关系（persona_profiles.bond）。

Revision ID: 0012_pet_owner_bond
Revises: 0011_owner_user_scoped
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_pet_owner_bond"
down_revision: str | None = "0011_owner_user_scoped"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "persona_profiles",
        sa.Column(
            "bond",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("persona_profiles", "bond")
