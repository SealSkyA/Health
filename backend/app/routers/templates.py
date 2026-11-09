"""报告模板 REST API。"""
import json
from datetime import datetime
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.routers.auth import require_perm
from app.models.templates import ReportTemplate
from app.models.user import User

router = APIRouter()


# ---------- Schemas ----------
class TemplateItemIn(BaseModel):
    """一条检验项目明细（含参考范围参数，可为区间/文字/分级）。"""
    name: str = ""
    ref_range: Optional[str] = None   # 参考范围：如「3.5~9.5」「阴性」「A,B,C」
    ref_min: Optional[str] = None     # 兼容旧数据（数字下限）
    ref_max: Optional[str] = None     # 兼容旧数据（数字上限）
    unit: Optional[str] = None
    note: Optional[str] = None


class TemplateItemOut(BaseModel):
    name: str = ""
    ref_range: Optional[str] = None
    ref_min: Optional[str] = None
    ref_max: Optional[str] = None
    unit: Optional[str] = None
    note: Optional[str] = None


class TemplateIn(BaseModel):
    name: str
    # 明细数组；兼容旧客户端直接传「·」分隔文本字符串
    items: Optional[Union[list[TemplateItemIn], str]] = []
    creator: Optional[str] = None
    note: Optional[str] = None


class TemplateOut(BaseModel):
    id: int
    name: str
    items: Optional[str] = None          # 检验项目名称拼接文本（列表展示用）
    items_detail: list[TemplateItemOut] = []   # 结构化明细（编辑回显用）
    creator: Optional[str] = None
    note: Optional[str] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# ---------- 明细存储：JSON 数组（兼容旧的「·」分隔文本） ----------
def _dump_items(items) -> str:
    if isinstance(items, str):
        return items  # 旧文本格式原样保存
    if not items:
        return "[]"
    return json.dumps(
        [it.model_dump() for it in items if it.name.strip()],
        ensure_ascii=False,
    )


def _parse_items(raw: Optional[str]) -> tuple[list[dict], str]:
    """返回 (明细列表, 名称拼接文本)。旧分隔符文本无法解析时，明细为空、文本原样返回。"""
    if not raw:
        return [], ""
    try:
        arr = json.loads(raw)
        if isinstance(arr, list):
            names = " · ".join(x.get("name", "").strip() for x in arr if x.get("name"))
            return arr, names
    except (ValueError, TypeError):
        pass
    return [], raw


def _out(obj: ReportTemplate) -> TemplateOut:
    detail, names = _parse_items(obj.items)
    return TemplateOut(
        id=obj.id, name=obj.name,
        items=names or (obj.items if obj.items not in ("[]", "") else None),
        items_detail=detail,
        creator=obj.creator, note=obj.note, created_at=obj.created_at,
    )


# ---------- CRUD ----------
@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(
    q: str = Query("", description="搜索模板名称/检验项"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ReportTemplate).order_by(ReportTemplate.id.desc())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(ReportTemplate.name.like(like) | ReportTemplate.items.like(like))
    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    return [_out(o) for o in res.scalars().all()]


@router.post("/templates", response_model=TemplateOut, status_code=201)
async def create_template(data: TemplateIn, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.tpl.write"))):
    obj = ReportTemplate(
        name=data.name, items=_dump_items(data.items),
        creator=data.creator, note=data.note,
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _out(obj)


@router.get("/templates/total-count")
async def total_count(db: AsyncSession = Depends(get_db)):
    n = await db.scalar(select(func.count()).select_from(ReportTemplate))
    return {"total": n or 0}


@router.get("/templates/{tid}", response_model=TemplateOut)
async def get_template(tid: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(ReportTemplate).where(ReportTemplate.id == tid))
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="模板不存在")
    return _out(obj)


@router.put("/templates/{tid}", response_model=TemplateOut)
async def update_template(tid: int, data: TemplateIn, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.tpl.write"))):
    res = await db.execute(select(ReportTemplate).where(ReportTemplate.id == tid))
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="模板不存在")
    obj.name = data.name
    obj.items = _dump_items(data.items)
    obj.creator = data.creator
    obj.note = data.note
    await db.commit()
    await db.refresh(obj)
    return _out(obj)


@router.delete("/templates/{tid}", status_code=204)
async def delete_template(tid: int, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.tpl.write"))):
    res = await db.execute(select(ReportTemplate).where(ReportTemplate.id == tid))
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="模板不存在")
    await db.delete(obj)
    await db.commit()


@router.post("/templates/batch-delete", status_code=204)
async def batch_delete_templates(ids: list[int], db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.tpl.write"))):
    """批量删除模板。"""
    if not ids:
        return
    res = await db.execute(select(ReportTemplate).where(ReportTemplate.id.in_(ids)))
    for obj in res.scalars().all():
        await db.delete(obj)
    await db.commit()
