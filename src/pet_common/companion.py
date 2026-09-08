"""约定持久化与沟通偏好枚举，复用现有用户和设备身份。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pet_common.models import Base, TimestampMixin

PREFERENCE_VALUES: dict[str, set[str]] = {
    "reply_length": {"short", "medium", "long"},
    "support_style": {"listen", "advice", "balanced"},
    "question_frequency": {"none", "one"},
    "tone": {"gentle", "direct", "playful"},
}


class CompanionFollowup(TimestampMixin, Base):
    __tablename__ = "companion_followups"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("devices.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    __table_args__ = (
        Index("uq_companion_followup_request", "device_id", "user_id", "request_id", unique=True),
        Index("ix_companion_followup_due", "device_id", "user_id", "status", "due_at"),
    )
