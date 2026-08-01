"""devices 增加 app 独立认领标识 binding_id。

MAC/device_uid 仍是小智硬件标识；binding_id 是 app 扫码或输入时使用的不可猜测标识。

Revision ID: 0005_devices_binding_id
Revises: 0004_persona_kb_seed
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_devices_binding_id"
down_revision: str | None = "0004_persona_kb_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("binding_id", sa.String(length=64), nullable=True))
    # 已有资产也必须可被 app 认领；随机值不可由 MAC 或连续主键推导。
    op.execute(
        "UPDATE devices SET binding_id = md5(random()::text || clock_timestamp()::text || id::text) "
        "WHERE binding_id IS NULL"
    )
    op.alter_column("devices", "binding_id", nullable=False)
    op.create_index("uq_devices_binding_id", "devices", ["binding_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_devices_binding_id", table_name="devices")
    op.drop_column("devices", "binding_id")
