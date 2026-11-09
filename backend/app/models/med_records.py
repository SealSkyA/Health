"""用药记录领域模型：一次开方（处方）包含多种药品明细。"""
from datetime import datetime, date
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.med_records import MedicationItem  # noqa


class Prescription(Base):
    """一次开方（处方）。"""

    __tablename__ = "prescriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # 创建人；NULL=存量数据归 admin 可见
    patient: Mapped[str] = mapped_column(String(128), nullable=False)          # 患者
    org_dept: Mapped[str] = mapped_column(String(255), nullable=True)          # 机构/科室
    doctor: Mapped[str] = mapped_column(String(64), nullable=True)             # 开方医师
    prescribed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)   # 开方时间
    report_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("reports.id", ondelete="SET NULL"), nullable=True, index=True)  # 关联检查记录（可选）
    check_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 关联检查记录的检查时间快照
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)   # 用药开始时间（开方级）
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)     # 用药结束时间（开方级）
    note: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    items: Mapped[list["MedicationItem"]] = relationship(
        back_populates="prescription", cascade="all, delete-orphan"
    )


class MedicationItem(Base):
    """开方内的单种药品明细。"""

    __tablename__ = "medication_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prescription_id: Mapped[int] = mapped_column(
        ForeignKey("prescriptions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)            # 药品名称
    spec: Mapped[str] = mapped_column(String(128), nullable=True)             # 规格/剂量
    frequency: Mapped[str] = mapped_column(String(128), nullable=True)        # 用药频次
    usage: Mapped[str] = mapped_column(String(128), nullable=True)           # 用法（餐前/睡前等）
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="进行中")
    note: Mapped[str] = mapped_column(Text, nullable=True)

    prescription: Mapped["Prescription"] = relationship(back_populates="items")