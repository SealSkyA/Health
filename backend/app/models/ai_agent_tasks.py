"""AI 问数后台任务模型（断线/离开页面仍在服务器端继续执行）。"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AiAgentTask(Base):
    __tablename__ = "ai_agent_tasks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running/done/error/cancelled
    message: Mapped[str] = mapped_column(Text)                           # 用户提问
    reply: Mapped[str] = mapped_column(Text, nullable=True)
    thinking: Mapped[str] = mapped_column(Text, nullable=True)
    pending: Mapped[str] = mapped_column(Text, nullable=True)            # PendingAction JSON
    searches: Mapped[str] = mapped_column(Text, nullable=True)           # 联网搜索结果 JSON
    error: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)