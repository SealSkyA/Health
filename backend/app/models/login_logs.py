"""登录记录模型。"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class LoginLog(Base):
    __tablename__ = "login_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=True)
    username: Mapped[str] = mapped_column(String(64), nullable=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=True)               # 来源 IP
    device: Mapped[str] = mapped_column(String(128), nullable=True)          # 设备标识
    status: Mapped[str] = mapped_column(String(32), default="成功")          # 成功/失败
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
