"""为设备人设增加稳定角色档案。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_persona_dossier"
down_revision: str | None = "0006_complete_persona_kb_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "persona_profiles",
        sa.Column(
            "dossier", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
    )


def downgrade() -> None:
    op.drop_column("persona_profiles", "dossier")
