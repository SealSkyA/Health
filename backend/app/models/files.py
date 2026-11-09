"""文件存储元数据模型（实际对象存 MinIO）。"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class StoredFile(Base):
    __tablename__ = "stored_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # 创建人；NULL=存量数据归 admin 可见
    filename: Mapped[str] = mapped_column(String(255), nullable=False)      # 原文件名
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)     # MinIO 对象键
    content_type: Mapped[str] = mapped_column(String(128), nullable=True)   # MIME 类型
    size: Mapped[int] = mapped_column(BigInteger, default=0)                 # 字节大小
    bucket: Mapped[str] = mapped_column(String(128), nullable=True)         # MinIO bucket
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
