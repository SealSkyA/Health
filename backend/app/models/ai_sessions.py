"""AI 问数会话持久化（整份会话数据按用户存 JSON，1 行/用户）。"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AiChatSession(Base):
    """用户 AI 问数会话（groups + sessions 整体序列化存储）。"""

    __tablename__ = "ai_chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)        # users.id
    data: Mapped[str] = mapped_column(Text, default="")              # {"groups": [...], "sessions": [...]}
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )