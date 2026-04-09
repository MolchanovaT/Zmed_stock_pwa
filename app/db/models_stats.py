from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, String, DateTime, Boolean, Text, ForeignKey
from datetime import datetime, timezone
from app.db.base import Base

def now_utc():
    return datetime.now(timezone.utc)

class TgUser(Base):
    __tablename__ = "tg_users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    language_code: Mapped[str | None] = mapped_column(String(8))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_seen_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), default=now_utc)

class Interaction(Base):
    __tablename__ = "tg_interactions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bot_name: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tg_users.id", ondelete="CASCADE"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    chat_type: Mapped[str | None] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))  # message|command|start|callback
    payload: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
