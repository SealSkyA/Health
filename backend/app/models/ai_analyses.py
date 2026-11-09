"""AI 分析结果存储模型。"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AiAnalysis(Base):
    """一次报告 AI 分析记录（整检查记录或单份报告）。"""

    __tablename__ = "ai_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # 创建人；NULL=存量数据归 admin 可见
    record_id: Mapped[int] = mapped_column(Integer, index=True)       # 检查记录 id（reports.id）
    doc_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 报告 id（report_docs.id；None=整记录）
    alias: Mapped[str] = mapped_column(String(128), default="")       # 使用的供应商别名
    model: Mapped[str] = mapped_column(String(128), default="")       # 使用的模型名
    question: Mapped[str] = mapped_column(String(512), default="")    # 用户问题/分析指令
    result: Mapped[str] = mapped_column(Text, default="")             # AI 分析结果
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
