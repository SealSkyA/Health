"""检查报告模型。"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # 创建人；NULL=存量数据归 admin 可见
    category: Mapped[str] = mapped_column(String(32), default="体检", nullable=True)  # 类别：体检/专项/复查
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)   # 检查时间
    addr: Mapped[str] = mapped_column(String(255), nullable=True)           # 检查地址/机构
    doctor: Mapped[str] = mapped_column(String(64), nullable=True)          # 负责人
    report_count: Mapped[int] = mapped_column(Integer, default=0)           # 报告数（冗余统计，兼容线上表结构）
    items_json: Mapped[str] = mapped_column(Text, nullable=True)            # 兼容线上表结构（明细现存 report_docs）
    note: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReportDoc(Base):
    """一份报告（挂在检查记录下，可多份，每份有名称/备注/明细）。"""
    __tablename__ = "report_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(Integer, index=True)   # 所属检查记录 id
    name: Mapped[str] = mapped_column(String(128), nullable=True)  # 报告名称
    note: Mapped[str] = mapped_column(Text, nullable=True)         # 报告备注
    items_json: Mapped[str] = mapped_column(Text, nullable=True)   # 检验结果明细（JSON 数组）
    image: Mapped[str] = mapped_column(String(255), nullable=True)  # 附件图片（静态路径 report_docs/xx.jpg）
    attach_json: Mapped[str] = mapped_column(Text, nullable=True)   # 附件清单 JSON：[{name,path,size,mime}]
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReportInterest(Base):
    """用户关注的检查项名称（按用户隔离，用于首页展示历史走势）。
    doc_id 为来源报告（组合关注）：非空时该项与同一 doc_id 下其它关注项合并到一张组合图对照显示。"""
    __tablename__ = "report_interests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # 关注人
    name: Mapped[str] = mapped_column(String(128), nullable=False)                    # 检查项名称
    doc_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)   # 来源报告 id（组合关注）
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
