"""角色与权限模型：角色（Role）+ 角色权限点（RolePerm）。"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Boolean, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    desc: Mapped[str] = mapped_column(String(255), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # 内置角色：不可删除
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RolePerm(Base):
    __tablename__ = "role_perms"
    __table_args__ = (UniqueConstraint("role_code", "perm", name="uq_role_perm"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_code: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    perm: Mapped[str] = mapped_column(String(64), index=True, nullable=False)