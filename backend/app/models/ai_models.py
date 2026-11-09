"""AI 模型配置模型。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AiModel(Base):
    __tablename__ = "ai_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alias: Mapped[str] = mapped_column(String(128), nullable=True)          # 供应商别名（配置标识）
    name: Mapped[str] = mapped_column(String(128), nullable=False)          # 模型名称
    vendor: Mapped[str] = mapped_column(String(64), nullable=True)          # 服务商
    addr: Mapped[str] = mapped_column(String(512), nullable=True)           # 接入地址
    api_key: Mapped[str] = mapped_column(String(512), nullable=True)        # API KEY
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)            # 是否启用
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
