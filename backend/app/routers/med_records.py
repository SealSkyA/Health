"""用药记录 REST API：一次开方（处方）含多种药品明细。"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.routers.auth import require_perm
from app.models.med_records import MedicationItem, Prescription
from app.models.reports import Report
from app.models.user import User

router = APIRouter()


# ---------- Schemas ----------
from datetime import date as _date
class ItemIn(BaseModel):
    name: str
    spec: Optional[str] = None
    frequency: Optional[str] = None
    usage: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: str = "进行中"
    note: Optional[str] = None


class PrescriptionIn(BaseModel):
    patient: str
    org_dept: Optional[str] = None
    doctor: Optional[str] = None
    prescribed_at: Optional[str] = None
    report_id: Optional[int] = None   # 关联检查记录（可选，非必填）
    start_date: Optional[str] = None  # 用药开始时间（开方级）
    end_date: Optional[str] = None    # 用药结束时间（开方级）
    note: Optional[str] = None
    items: list[ItemIn] = []


class ItemOut(BaseModel):
    id: int
    name: str
    spec: Optional[str] = None
    frequency: Optional[str] = None
    usage: Optional[str] = None
    start_date: Optional[_date] = None
    end_date: Optional[_date] = None
    status: str
    note: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class PrescriptionOut(BaseModel):
    id: int
    patient: str
    org_dept: Optional[str] = None
    doctor: Optional[str] = None
    prescribed_at: Optional[datetime] = None
    report_id: Optional[int] = None
    check_time: Optional[datetime] = None
    start_date: Optional[_date] = None
    end_date: Optional[_date] = None
    note: Optional[str] = None
    created_at: Optional[datetime] = None
    items: list[ItemOut] = []
    model_config = ConfigDict(from_attributes=True)


# ---------- CRUD ----------
def _scope(user: User):
    """数据隔离条件：admin 全量；其他用户只见自己创建的（存量 user_id=NULL 归 admin）。"""
    return None if user.role == "admin" else Prescription.user_id == user.id


@router.get("/med-records", response_model=list[PrescriptionOut])
async def list_prescriptions(
    q: str = Query("", description="搜索患者/医师/药品"),
    status: str = Query("", description="全部|进行中|已结束|已停药"),
    report_id: Optional[int] = Query(None, description="仅返回绑定该检查记录的开方"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _can: User = Depends(require_perm("page.med")),
):
    # 按开方时间倒序；开方时间为空的开方排最后；同时间按记录 id 新在前
    _null_last = case((Prescription.prescribed_at.is_(None), 1), else_=0)
    stmt = (
        select(Prescription)
        .options(selectinload(Prescription.items))
        .order_by(_null_last, Prescription.prescribed_at.desc(), Prescription.id.desc())
    )
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    if report_id is not None:
        stmt = stmt.where(Prescription.report_id == report_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            Prescription.patient.like(like)
            | Prescription.doctor.like(like)
        )
    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    return res.scalars().all()


@router.post("/med-records", response_model=PrescriptionOut, status_code=201)
async def create_prescription(data: PrescriptionIn, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.med.write"))):
    rx = Prescription(
        user_id=_can.id,
        patient=data.patient,
        org_dept=data.org_dept,
        doctor=data.doctor,
        prescribed_at=_parse_dt(data.prescribed_at),
        start_date=_parse_date(data.start_date),
        end_date=_parse_date(data.end_date),
        note=data.note,
    )
    await _link_report(db, rx, data.report_id, _can)
    for it in data.items:
        rx.items.append(MedicationItem(
            name=it.name, spec=it.spec, frequency=it.frequency, usage=it.usage,
            start_date=_parse_date(it.start_date), end_date=_parse_date(it.end_date),
            status=it.status, note=it.note,
        ))
    db.add(rx)
    await db.commit()
    await db.refresh(rx)
    # 重新加载关联
    rx = (await db.execute(
        select(Prescription).options(selectinload(Prescription.items)).where(Prescription.id == rx.id)
    )).scalar_one()
    return rx


@router.put("/med-records/{rid}", response_model=PrescriptionOut)
async def update_prescription(rid: int, data: PrescriptionIn, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.med.write"))):
    """编辑开方：更新主信息 + 全量替换药品明细。"""
    stmt = select(Prescription).options(selectinload(Prescription.items)).where(Prescription.id == rid)
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    res = await db.execute(stmt)
    rx = res.scalar_one_or_none()
    if not rx:
        raise HTTPException(status_code=404, detail="开方不存在")
    rx.patient = data.patient
    rx.org_dept = data.org_dept
    rx.doctor = data.doctor
    rx.prescribed_at = _parse_dt(data.prescribed_at)
    rx.start_date = _parse_date(data.start_date)
    rx.end_date = _parse_date(data.end_date)
    rx.note = data.note
    await _link_report(db, rx, data.report_id, _can)
    # 全量替换明细（旧明细级联删除）
    rx.items.clear()
    for it in data.items:
        rx.items.append(MedicationItem(
            name=it.name, spec=it.spec, frequency=it.frequency, usage=it.usage,
            start_date=_parse_date(it.start_date), end_date=_parse_date(it.end_date),
            status=it.status, note=it.note,
        ))
    await db.commit()
    await db.refresh(rx)
    rx = (await db.execute(
        select(Prescription).options(selectinload(Prescription.items)).where(Prescription.id == rx.id)
    )).scalar_one()
    return rx


async def _link_report(db: AsyncSession, rx: Prescription, report_id: Optional[int], user: User):
    """关联检查记录：有则带出其检查时间快照，无/失效/无权则清空。

    user 为当前操作人：非 admin 只能绑定自己创建的检查记录。
    """
    if report_id:
        rep = await db.get(Report, report_id)
        if rep and (user.role == "admin" or rep.user_id == user.id):
            rx.report_id = rep.id
            rx.check_time = rep.checked_at
            return
    rx.report_id = None
    rx.check_time = None


@router.get("/med-records/total-count")
async def total_count(db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("page.med"))):
    stmt = select(func.count()).select_from(Prescription)
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    n = await db.scalar(stmt)
    return {"total": n or 0}


@router.get("/med-records/{rid}", response_model=PrescriptionOut)
async def get_prescription(rid: int, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("page.med"))):
    stmt = select(Prescription).options(selectinload(Prescription.items)).where(Prescription.id == rid)
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    res = await db.execute(stmt)
    rx = res.scalar_one_or_none()
    if not rx:
        raise HTTPException(status_code=404, detail="开方不存在")
    return rx


@router.delete("/med-records/{rid}", status_code=204)
async def delete_prescription(rid: int, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.med.write"))):
    stmt = select(Prescription).where(Prescription.id == rid)
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    res = await db.execute(stmt)
    rx = res.scalar_one_or_none()
    if not rx:
        raise HTTPException(status_code=404, detail="开方不存在")
    await db.delete(rx)
    await db.commit()


@router.post("/med-records/batch-delete", status_code=204)
async def batch_delete_prescriptions(ids: list[int], db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.med.write"))):
    """批量删除开方（级联删除药品明细）。"""
    if not ids:
        return
    stmt = select(Prescription).where(Prescription.id.in_(ids))
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    res = await db.execute(stmt)
    for rx in res.scalars().all():
        await db.delete(rx)
    await db.commit()


def _parse_dt(s: Optional[str]):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _parse_date(s: Optional[str]):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None