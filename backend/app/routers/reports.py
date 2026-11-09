"""检查报告 REST API：检查记录（父级）+ 报告（子级，名称/备注/明细）。"""
import asyncio
import base64
import json
import os
import re
import urllib.request
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.routers.auth import require_perm
from app.models.reports import Report, ReportDoc, ReportInterest
from app.models.user import User

router = APIRouter()

_IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}


def _doc_img_dir() -> str:
    d = os.path.join(get_settings().UPLOAD_DIR, "report_docs")
    os.makedirs(d, exist_ok=True)
    return d


def _att_dir() -> str:
    d = os.path.join(get_settings().UPLOAD_DIR, "report_docs", "att")
    os.makedirs(d, exist_ok=True)
    return d


def _parse_attach(raw: Optional[str]) -> list[dict]:
    """解析报告的附件清单 JSON。"""
    if not raw:
        return []
    try:
        arr = json.loads(raw)
        return arr if isinstance(arr, list) else []
    except (ValueError, TypeError):
        return []


def _is_img_att(a: dict) -> bool:
    """附件是否为图片（按 mime 或扩展名判断）。"""
    mime = (a.get("mime") or "").lower()
    if mime.startswith("image/"):
        return True
    ext = os.path.splitext((a.get("name") or "").lower())[1]
    return ext in _IMG_EXTS


def _doc_cover(obj: ReportDoc) -> Optional[str]:
    """报告展示图：优先最后一张（最新上传）图片附件，否则回退附件图片 doc.image。"""
    for a in reversed(_parse_attach(obj.attach_json)):
        if _is_img_att(a):
            return a.get("path")
    return obj.image


# ---------- Schemas ----------
class ReportItemIn(BaseModel):
    """一条检验结果明细。"""
    name: str = ""
    ref_range: Optional[str] = None   # 参考范围（数字区间 / 文字）
    unit: Optional[str] = None
    value: Optional[str] = None       # 实测结果值
    result: Optional[str] = None      # high/low/normal/abnormal（后端计算）


class ReportItemOut(BaseModel):
    name: str = ""
    ref_range: Optional[str] = None
    unit: Optional[str] = None
    value: Optional[str] = None
    result: Optional[str] = None


class ReportIn(BaseModel):
    """检查记录（父级）。"""
    category: Optional[str] = None
    checked_at: Optional[str] = None
    addr: Optional[str] = None
    doctor: Optional[str] = None
    note: Optional[str] = None


class ReportOut(BaseModel):
    id: int
    category: Optional[str] = None
    checked_at: Optional[datetime] = None
    addr: Optional[str] = None
    doctor: Optional[str] = None
    report_count: int = 0          # 已录报告数（自动统计）
    note: Optional[str] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class DocIn(BaseModel):
    """一份报告（子级）。"""
    name: Optional[str] = None
    note: Optional[str] = None
    items: Optional[list[ReportItemIn]] = []


class DocOut(BaseModel):
    id: int
    report_id: int
    name: Optional[str] = None
    note: Optional[str] = None
    items_detail: list[ReportItemOut] = []
    image: Optional[str] = None          # 附件图片（静态路径，如 report_docs/12.jpg）
    attachments: list[dict] = []         # 附件清单：[{name,path,size,mime}]
    cover: Optional[str] = None          # 展示图：最后一张图片附件，否则回退 image
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# ---------- 标准值判定 ----------
def _calc_result(value, ref_range) -> str:
    """对照参考范围判定结果：normal/high/low/abnormal/blank。"""
    if value is None or str(value).strip() == "":
        return "blank"
    v = str(value).strip()
    # OCR 常见：结果值尾巴带箭头（56.6 ↑ / 39.3 ↓），剥离后参与判定
    v = re.sub(r"\s*[↑⇧↓⇩]\s*$", "", v).strip()
    r = (ref_range or "").strip()
    if not r:
        return "blank"

    def _num(s):
        try:
            return float(s)
        except ValueError:
            return None

    n = _num(v)

    # 值本身带大小比较前缀：>150 / <0.1 表示超出检测范围
    if n is None:
        pm = re.match(r"^\s*([><])\s*([\d.]+)\s*$", v)
        if pm:
            return "high" if pm.group(1) == ">" else "low"

    # 数字区间：3.5~9.5 / 3.5-9.5 / 9--50（OCR 双横）/ 9 50（空格）等，可选括号包裹
    m = re.match(r"^\s*[\(\（]?\s*(-?[\d.]+)\s*[~\-—～\s]+\s*(-?[\d.]+)\s*[\)\）]?\s*$", r)
    if m:
        lo, hi = _num(m.group(1)), _num(m.group(2))
        if n is None:
            return "abnormal"
        if n < lo:
            return "low"
        if n > hi:
            return "high"
        return "normal"

    # 上限参考：≤1.70 / <3.37（value 不超过 b 正常）
    m = re.match(r"^\s*[≤<]+\s*(-?[\d.]+)\s*$", r)
    if m:
        b = _num(m.group(1))
        if n is None:
            return "abnormal"
        return "normal" if n <= b else "high"

    # 下限参考：≥0.8 / >0.5（value 不低于 b 正常）
    m = re.match(r"^\s*[≥>]+\s*(-?[\d.]+)\s*$", r)
    if m:
        b = _num(m.group(1))
        if n is None:
            return "abnormal"
        return "normal" if n >= b else "low"

    # 文字参考值（阴性 / A,B,C 等）：完全一致才正常
    return "normal" if v == r else "abnormal"


def _dump_items(items: list[ReportItemIn]) -> str:
    if not items:
        return "[]"
    arr = []
    for it in items:
        if not it.name or not it.name.strip():
            continue
        arr.append({
            "name": it.name.strip(),
            "ref_range": it.ref_range,
            "unit": it.unit,
            "value": (it.value or "").strip() or None,
            "result": _calc_result(it.value, it.ref_range),
        })
    return json.dumps(arr, ensure_ascii=False)


def _parse_items(raw: Optional[str]) -> list[dict]:
    if not raw:
        return []
    try:
        arr = json.loads(raw)
        return arr if isinstance(arr, list) else []
    except (ValueError, TypeError):
        return []


def _doc_out(obj: ReportDoc) -> DocOut:
    return DocOut(
        id=obj.id, report_id=obj.report_id,
        name=obj.name, note=obj.note,
        items_detail=_parse_items(obj.items_json),
        image=obj.image,
        attachments=_parse_attach(obj.attach_json),
        cover=_doc_cover(obj),
        created_at=obj.created_at,
    )


# ---------- 检查记录 CRUD（父级） ----------
def _scope(user: User):
    """数据隔离条件：admin 全量；其他用户只见自己创建的（存量 user_id=NULL 归 admin）。"""
    return None if user.role == "admin" else Report.user_id == user.id


@router.get("/reports", response_model=list[ReportOut])
async def list_reports(
    q: str = Query("", description="搜索地址/负责人"),
    category: str = Query("", description="类别：体检/专项/复查"),
    start_date: str = Query("", description="检查时间起（YYYY-MM-DD）"),
    end_date: str = Query("", description="检查时间止（YYYY-MM-DD）"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _can: User = Depends(require_perm("page.report")),
):
    cnt_sub = (
        select(ReportDoc.report_id, func.count().label("cnt"))
        .group_by(ReportDoc.report_id)
        .subquery()
    )
    stmt = (
        select(Report, cnt_sub.c.cnt)
        .outerjoin(cnt_sub, cnt_sub.c.report_id == Report.id)
        .order_by(Report.id.desc())
    )
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Report.addr.like(like) | Report.doctor.like(like))
    if category:
        stmt = stmt.where(Report.category == category)
    if start_date:
        start_dt = _parse_dt(start_date) or _parse_dt(f"{start_date}T00:00:00")
        if start_dt:
            stmt = stmt.where(Report.checked_at >= start_dt)
    if end_date:
        end_dt = _parse_dt(end_date) or _parse_dt(f"{end_date}T23:59:59")
        if end_dt:
            stmt = stmt.where(Report.checked_at <= end_dt)
    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    rows_out = []
    for obj, cnt in res.all():
        d = ReportOut.model_validate(obj)
        d.report_count = cnt or 0
        rows_out.append(d)
    return rows_out


@router.get("/reports/total-count")
async def total_count(db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("page.report"))):
    stmt = select(func.count()).select_from(Report)
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    n = await db.scalar(stmt)
    return {"total": n or 0}


@router.get("/reports/doc-names")
async def doc_names(db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("page.report"))):
    """返回当前用户可见范围内的报告名称（去重、按名称排序），供新增报告时下拉选择。"""
    stmt = (
        select(ReportDoc.name)
        .join(Report, Report.id == ReportDoc.report_id)
        .where(ReportDoc.name.is_not(None), ReportDoc.name != "")
        .distinct()
        .order_by(ReportDoc.name)
        .limit(300)
    )
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    res = await db.execute(stmt)
    return [r for r in res.scalars().all() if r and r.strip()]


@router.get("/reports/latest-docs")
async def latest_docs(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _can: User = Depends(require_perm("page.report")),
):
    """首页「最新报告」：按检查时间倒序返回最新报告文档（含明细与异常统计），点击即可在首页直接查看。"""
    _null_last = case((Report.checked_at.is_(None), 1), else_=0)
    stmt = (
        select(ReportDoc, Report.checked_at, Report.category, Report.addr, Report.doctor)
        .join(Report, Report.id == ReportDoc.report_id)
        .order_by(_null_last, Report.checked_at.desc(), ReportDoc.id.desc())
        .limit(limit)
    )
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    res = await db.execute(stmt)
    out = []
    for obj, checked_at, category, addr, doctor in res.all():
        items = _parse_items(obj.items_json)
        abn = [it for it in items if it.get("result") in ("high", "low", "abnormal")]
        out.append({
            "id": obj.id,
            "report_id": obj.report_id,
            "name": obj.name,
            "note": obj.note or "",
            "image": obj.image or "",
            "attachments": _parse_attach(obj.attach_json),
            "cover": _doc_cover(obj) or "",
            "checked_at": checked_at.isoformat()[:10] if checked_at else "",
            "category": category or "",
            "addr": addr or "",
            "doctor": doctor or "",
            "items_detail": items,
            "item_count": len(items),
            "abnormal": len(abn),
        })
    return out


# ---------- 检查项趋势 ----------
def _num_value(v) -> Optional[float]:
    """数值化检查结果：剥箭头/前缀比较符；非数值返回 None。"""
    if v is None:
        return None
    s = str(v).strip()
    s = re.sub(r"\s*[↑⇧↓⇩]\s*$", "", s).strip()
    try:
        return float(s)
    except ValueError:
        m = re.match(r"^[><]\s*([\d.]+)\s*$", s)
        return float(m.group(1)) if m else None


async def _trend_points(db: AsyncSession, user: User, name: str, start=None, limit: Optional[int] = None):
    """当前用户可见范围内，某检查项的历史数值点（按检查时间升序，最多取最近 limit 个）。"""
    stmt = (
        select(ReportDoc, Report.checked_at)
        .join(Report, Report.id == ReportDoc.report_id)
        .where(ReportDoc.items_json.is_not(None), ReportDoc.items_json != "[]")
    )
    sc = _scope(user)
    if sc is not None:
        stmt = stmt.where(sc)
    if start is not None:
        stmt = stmt.where(Report.checked_at >= start)
    rows = (await db.execute(stmt)).all()
    pts = []
    for doc, checked_at in rows:
        for it in _parse_items(doc.items_json):
            if (it.get("name") or "").strip() != name:
                continue
            when = ""
            if checked_at:
                when = checked_at.isoformat()[:10]
            elif doc.created_at:
                when = doc.created_at.strftime("%Y-%m-%d")
            pts.append({
                "checked_at": when,
                "value": it.get("value"),
                "num": _num_value(it.get("value")),
                "ref_range": it.get("ref_range"),
                "unit": it.get("unit"),
                "result": it.get("result"),
            })
    pts.sort(key=lambda p: (p["checked_at"] or "0000-00-00",))
    if limit and len(pts) > limit:
        pts = pts[-limit:]
    return pts


@router.get("/reports/trend")
async def report_item_trend(
    name: str = Query(..., min_length=1, max_length=128),
    scope: str = Query("all", pattern="^(all|year|quarter|recent3)$"),
    db: AsyncSession = Depends(get_db),
    _can: User = Depends(require_perm("page.report")),
):
    """检查项趋势：全年 / 今年 / 本季度 / 最近三次（默认全年），返回按日期升序的数值点。"""
    today = datetime.now().date()
    start = None
    if scope == "year":
        start = datetime(today.year, 1, 1)
    elif scope == "quarter":
        q = (today.month - 1) // 3
        start = datetime(today.year, q * 3 + 1, 1)
    pts = await _trend_points(db, _can, name.strip(), start=start, limit=(3 if scope == "recent3" else None))
    unit = ""
    for p in reversed(pts):
        if p.get("unit"):
            unit = p["unit"]
            break
    return {"name": name.strip(), "scope": scope, "unit": unit, "points": pts}


# ---------- 检查项关注（首页展示） ----------
class InterestIn(BaseModel):
    name: str = ""
    doc_id: Optional[int] = None   # 来源报告 id：非空=组合关注（同报告多项合并一张图对照）


@router.get("/reports/interests")
async def list_interests(db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("page.report"))):
    """当前用户关注的检查项；返回分为 singles（单独卡）与 groups（同报告组合，多系列一图）。"""
    stmt = (
        select(ReportInterest)
        .where(ReportInterest.user_id == _can.id)
        .order_by(ReportInterest.created_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    singles = []
    groups_map = {}   # doc_id -> {doc_id, doc_name, series:[...]}
    for it in rows:
        pts = await _trend_points(db, _can, it.name, limit=40)
        latest = pts[-1] if pts else None
        entry = {
            "name": it.name,
            "unit": latest.get("unit") if latest else "",
            "points": pts,
            "latest_value": latest.get("value") if latest else None,
            "latest_result": latest.get("result") if latest else "",
            "latest_checked_at": latest.get("checked_at") if latest else "",
        }
        if it.doc_id:
            g = groups_map.get(it.doc_id)
            if g is None:
                doc = await db.get(ReportDoc, it.doc_id)
                g = {
                    "doc_id": it.doc_id,
                    "doc_name": doc.name if doc else f"报告 #{it.doc_id}",
                    "series": [],
                }
                groups_map[it.doc_id] = g
            g["series"].append(entry)
        else:
            singles.append(entry)
    groups = [groups_map[k] for k in sorted(groups_map.keys())]
    return {"singles": singles, "groups": groups}


@router.post("/reports/interests", status_code=201)
async def add_interest(data: InterestIn, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("page.report"))):
    """关注一个检查项（幂等）。doc_id 非空时按「同报告组合」去重。"""
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="请填写检查项名称")
    q = select(ReportInterest).where(
        ReportInterest.user_id == _can.id, ReportInterest.name == name
    )
    if data.doc_id is not None:
        q = q.where(ReportInterest.doc_id == data.doc_id)
    else:
        q = q.where(ReportInterest.doc_id.is_(None))
    exist = await db.scalar(q)
    if not exist:
        db.add(ReportInterest(user_id=_can.id, name=name, doc_id=data.doc_id))
        await db.commit()
    return {"name": name, "doc_id": data.doc_id}


@router.delete("/reports/interests")
async def remove_interest(
    name: str = Query(..., min_length=1),
    doc_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _can: User = Depends(require_perm("page.report")),
):
    """取消关注。doc_id 缺省时删除该名下全部关注（含组合）。"""
    q = select(ReportInterest).where(
        ReportInterest.user_id == _can.id, ReportInterest.name == name
    )
    if doc_id is not None:
        q = q.where(ReportInterest.doc_id == doc_id)
    else:
        q = q.where(ReportInterest.doc_id.is_(None))
    objs = (await db.execute(q)).scalars().all()
    if not objs:
        raise HTTPException(status_code=404, detail="未关注该检查项")
    for o in objs:
        await db.delete(o)
    await db.commit()
    return {"ok": True}


@router.post("/reports", response_model=ReportOut, status_code=201)
async def create_report(data: ReportIn, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.report.write"))):
    obj = Report(
        user_id=_can.id,
        category=data.category, checked_at=_parse_dt(data.checked_at),
        addr=data.addr, doctor=data.doctor,
        note=data.note,
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _out_with_count(obj, 0)


@router.get("/reports/{rid}", response_model=ReportOut)
async def get_report(rid: int, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("page.report"))):
    stmt = select(Report).where(Report.id == rid)
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    res = await db.execute(stmt)
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="检查记录不存在")
    cnt = await db.scalar(
        select(func.count()).select_from(ReportDoc).where(ReportDoc.report_id == rid)
    )
    return _out_with_count(obj, cnt or 0)


@router.put("/reports/{rid}", response_model=ReportOut)
async def update_report(rid: int, data: ReportIn, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.report.write"))):
    stmt = select(Report).where(Report.id == rid)
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    res = await db.execute(stmt)
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="检查记录不存在")
    obj.checked_at = _parse_dt(data.checked_at)
    obj.category = data.category
    obj.addr = data.addr
    obj.doctor = data.doctor
    obj.note = data.note
    await db.commit()
    await db.refresh(obj)
    cnt = await db.scalar(
        select(func.count()).select_from(ReportDoc).where(ReportDoc.report_id == rid)
    )
    return _out_with_count(obj, cnt or 0)


@router.delete("/reports/{rid}", status_code=204)
async def delete_report(rid: int, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.report.write"))):
    stmt = select(Report).where(Report.id == rid)
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    res = await db.execute(stmt)
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="检查记录不存在")
    await db.execute(delete(ReportDoc).where(ReportDoc.report_id == rid))
    await db.delete(obj)
    await db.commit()


@router.post("/reports/batch-delete", status_code=204)
async def batch_delete_reports(ids: list[int], db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.report.write"))):
    """批量删除检查记录（连同其下报告）。"""
    if not ids:
        return
    stmt = delete(Report).where(Report.id.in_(ids))
    _sc = _scope(_can)
    if _sc is not None:
        # 普通用户只允许删自己名下的记录；需先取中标的子表删除
        sel = select(Report.id).where(Report.id.in_(ids))
        sel = sel.where(_sc)
        mine = (await db.execute(sel)).scalars().all()
        if not mine:
            return
        await db.execute(delete(ReportDoc).where(ReportDoc.report_id.in_(mine)))
        await db.execute(delete(Report).where(Report.id.in_(mine)))
    else:
        await db.execute(delete(ReportDoc).where(ReportDoc.report_id.in_(ids)))
        await db.execute(stmt)
    await db.commit()


def _out_with_count(obj: Report, cnt: int) -> ReportOut:
    d = ReportOut.model_validate(obj)
    d.report_count = cnt
    return d


# ---------- 报告 CRUD（子级） ----------
async def _get_report_or_404(rid: int, db: AsyncSession, user: User) -> Report:
    stmt = select(Report).where(Report.id == rid)
    _sc = _scope(user)
    if _sc is not None:
        stmt = stmt.where(_sc)
    res = await db.execute(stmt)
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="检查记录不存在")
    return obj


@router.post("/reports/{rid}/docs", response_model=DocOut, status_code=201)
async def create_doc(rid: int, data: DocIn, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.report.write"))):
    await _get_report_or_404(rid, db, _can)
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="请填写报告名称")
    obj = ReportDoc(
        report_id=rid, name=name, note=data.note,
        items_json=_dump_items(data.items),
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _doc_out(obj)


@router.get("/reports/{rid}/docs", response_model=list[DocOut])
async def list_docs(rid: int, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("page.report"))):
    await _get_report_or_404(rid, db, _can)
    res = await db.execute(
        select(ReportDoc).where(ReportDoc.report_id == rid).order_by(ReportDoc.id.desc())
    )
    return [_doc_out(o) for o in res.scalars().all()]


@router.put("/reports/{rid}/docs/{did}", response_model=DocOut)
async def update_doc(rid: int, did: int, data: DocIn, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.report.write"))):
    await _get_report_or_404(rid, db, _can)
    res = await db.execute(
        select(ReportDoc).where(ReportDoc.id == did, ReportDoc.report_id == rid)
    )
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="报告不存在")
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="请填写报告名称")
    obj.name = name
    obj.note = data.note
    obj.items_json = _dump_items(data.items)
    await db.commit()
    await db.refresh(obj)
    return _doc_out(obj)


@router.delete("/reports/{rid}/docs/{did}", status_code=204)
async def delete_doc(rid: int, did: int, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.report.write"))):
    await _get_report_or_404(rid, db, _can)
    res = await db.execute(
        select(ReportDoc).where(ReportDoc.id == did, ReportDoc.report_id == rid)
    )
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="报告不存在")
    _remove_doc_image(obj)
    await db.delete(obj)
    await db.commit()


@router.post("/reports/{rid}/docs/{did}/image", response_model=DocOut)
async def upload_doc_image(
    rid: int, did: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.report.write"))
):
    """上传报告附件图片（保存到静态目录，覆盖旧图）。"""
    await _get_report_or_404(rid, db, _can)
    obj = await _get_doc_or_404(rid, did, db)
    data = await file.read()
    if len(data) > get_settings().MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="图片超过大小限制（10MB）")
    return await _save_doc_image(obj, data, file.filename, file.content_type, db)


class ImageB64In(BaseModel):
    """图片 JSON 上传体：data URL 或纯 base64。"""
    image: str
    filename: Optional[str] = None


@router.post("/reports/{rid}/docs/{did}/image-json", response_model=DocOut)
async def upload_doc_image_json(
    rid: int, did: int, data: ImageB64In, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.report.write"))
):
    """上传报告附件图片（JSON + base64，规避部分网络对 multipart 的拦截）。"""
    await _get_report_or_404(rid, db, _can)
    obj = await _get_doc_or_404(rid, did, db)
    raw = _b64decode(data.image)
    if len(raw) > get_settings().MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="图片超过大小限制（10MB）")
    return await _save_doc_image(obj, raw, data.filename, "", db)


async def _get_doc_or_404(rid: int, did: int, db: AsyncSession) -> ReportDoc:
    res = await db.execute(
        select(ReportDoc).where(ReportDoc.id == did, ReportDoc.report_id == rid)
    )
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="报告不存在")
    return obj


async def _save_doc_image(obj: ReportDoc, data: bytes, filename: Optional[str],
                          content_type: Optional[str], db: AsyncSession) -> DocOut:
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    ext = os.path.splitext((filename or "").lower())[1]
    if ext not in _IMG_EXTS:
        ct = (content_type or "").lower()
        for e, m in ((".jpg", "image/jpeg"), (".png", "image/png"),
                     (".gif", "image/gif"), (".webp", "image/webp"),
                     (".bmp", "image/bmp")):
            if ct == m:
                ext = e
                break
        if ext not in _IMG_EXTS:
            ext = ".jpg"
    if obj.image:
        _remove_doc_image(obj)
    rel = f"report_docs/{obj.id}{ext}"
    with open(os.path.join(_doc_img_dir(), f"{obj.id}{ext}"), "wb") as fh:
        fh.write(data)
    obj.image = rel
    await db.commit()
    await db.refresh(obj)
    return _doc_out(obj)


def _b64decode(s: str) -> bytes:
    """解析 data URL 或纯 base64；非法返回空字节。"""
    txt = (s or "").strip()
    if txt.startswith("data:"):
        txt = txt.split(",", 1)[-1]
    try:
        return base64.b64decode(txt, validate=False)
    except Exception:
        raise HTTPException(status_code=400, detail="图片编码无效")


def _remove_doc_image(obj: ReportDoc):
    """删除报告的附件图片文件（只允许 uploads/report_docs 下的相对路径）。"""
    if not obj.image:
        return
    img = obj.image.replace("\\", "/")
    if ".." in img or img.startswith("/") or ":" in img:
        return
    base = os.path.join(get_settings().UPLOAD_DIR, "report_docs")
    full = os.path.normpath(os.path.join(base, img))
    if not full.startswith(base + os.sep):
        return
    try:
        if os.path.isfile(full):
            os.remove(full)
    except OSError:
        pass


def _remove_att_file(rel: Optional[str]):
    """删除报告附件文件（只允许 uploads/report_docs/att 下的相对路径）。"""
    if not rel:
        return
    p = rel.replace("\\", "/")
    if ".." in p or p.startswith("/") or ":" in p:
        return
    base = os.path.join(get_settings().UPLOAD_DIR, "report_docs", "att")
    full = os.path.normpath(os.path.join(base, p))
    if not full.startswith(base + os.sep):
        return
    try:
        if os.path.isfile(full):
            os.remove(full)
    except OSError:
        pass


def _safe_att_name(name: Optional[str]) -> str:
    """去除路径部分，保留文件名。"""
    base = os.path.basename((name or "file").replace("\\", "/"))
    return base or "file"


async def _save_doc_attach(obj: ReportDoc, data: bytes, filename: Optional[str],
                           content_type: Optional[str], db: AsyncSession) -> DocOut:
    """保存一个附件文件到 report_docs/att/ 并追加到清单。"""
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    name = _safe_att_name(filename)
    ext = os.path.splitext(name)[1].lower()
    if not ext:
        ext = "." + (content_type.split("/")[-1].split(";")[0].strip() if content_type else "bin")
        if len(ext) > 12:
            ext = ".bin"
    seq = len(_parse_attach(obj.attach_json)) + 1
    rel_name = f"{obj.id}_att_{seq}{ext}"
    with open(os.path.join(_att_dir(), rel_name), "wb") as fh:
        fh.write(data)
    atts = _parse_attach(obj.attach_json)
    atts.append({
        "name": name,
        "path": f"report_docs/att/{rel_name}",
        "size": len(data),
        "mime": content_type or "",
    })
    obj.attach_json = json.dumps(atts, ensure_ascii=False)
    await db.commit()
    await db.refresh(obj)
    return _doc_out(obj)


@router.post("/reports/{rid}/docs/{did}/attach", response_model=DocOut)
async def upload_doc_attach(
    rid: int, did: int, file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.report.write")),
):
    """上传报告附件（multipart，保存在 report_docs/att/ 并追加到附件清单）。"""
    await _get_report_or_404(rid, db, _can)
    obj = await _get_doc_or_404(rid, did, db)
    data = await file.read()
    if len(data) > get_settings().MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="附件超过大小限制（10MB）")
    return await _save_doc_attach(obj, data, file.filename, file.content_type or "", db)


class AttachB64In(BaseModel):
    """附件 JSON 上传体：base64 内容 + 文件名（规避部分网络对 multipart 的拦截）。"""
    name: Optional[str] = None
    file: str
    mime: Optional[str] = None


@router.post("/reports/{rid}/docs/{did}/attach-json", response_model=DocOut)
async def upload_doc_attach_json(
    rid: int, did: int, data: AttachB64In,
    db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.report.write")),
):
    """上传报告附件（JSON + base64）。"""
    await _get_report_or_404(rid, db, _can)
    obj = await _get_doc_or_404(rid, did, db)
    raw = _b64decode(data.file)
    if not raw:
        raise HTTPException(status_code=400, detail="空文件")
    if len(raw) > get_settings().MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="附件超过大小限制（10MB）")
    return await _save_doc_attach(obj, raw, data.name, data.mime or "", db)


@router.delete("/reports/{rid}/docs/{did}/attach/{idx:path}", response_model=DocOut)
async def remove_doc_attach(
    rid: int, did: int, idx: str,
    db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.report.write")),
):
    """删除报告的一个附件（按清单下标）。"""
    try:
        i = int(idx)
    except ValueError:
        raise HTTPException(status_code=404, detail="附件不存在")
    await _get_report_or_404(rid, db, _can)
    obj = await _get_doc_or_404(rid, did, db)
    atts = _parse_attach(obj.attach_json)
    if i < 0 or i >= len(atts):
        raise HTTPException(status_code=404, detail="附件不存在")
    _remove_att_file(atts.pop(i).get("path"))
    obj.attach_json = json.dumps(atts, ensure_ascii=False)
    await db.commit()
    await db.refresh(obj)
    return _doc_out(obj)


# ---------- OCR ----------
@router.post("/reports/ocr")
async def ocr_recognize(file: UploadFile = File(...)):
    """上传报告图片，调用本地 RapidOCR 服务识别文本行。"""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    return await _call_ocr(data)


@router.post("/reports/ocr-json")
async def ocr_recognize_json(data: ImageB64In):
    """OCR 识别（JSON + base64，规避部分网络对 multipart 的拦截）。"""
    raw = _b64decode(data.image)
    if not raw:
        raise HTTPException(status_code=400, detail="空文件")
    return await _call_ocr(raw)


async def _call_ocr(data: bytes):
    b64 = base64.b64encode(data).decode()
    body = json.dumps({"image": b64}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8080/ocr",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = await asyncio.to_thread(urllib.request.urlopen, req, timeout=180)
        return json.loads(resp.read().decode("utf-8"))
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"OCR 服务不可用：{ex}")


def _parse_dt(s: Optional[str]):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None