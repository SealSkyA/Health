"""AI 模型配置 REST API。"""
import asyncio
import json
import urllib.request
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.routers.auth import require_perm
from app.models.ai_models import AiModel
from app.models.user import User

router = APIRouter()


# ---------- Schemas ----------
class AiModelIn(BaseModel):
    alias: Optional[str] = None
    name: str
    vendor: Optional[str] = None
    addr: Optional[str] = None
    api_key: Optional[str] = None
    enabled: bool = True


class AiModelOut(BaseModel):
    id: int
    alias: Optional[str] = None
    name: str
    vendor: Optional[str] = None
    addr: Optional[str] = None
    api_key: Optional[str] = None
    enabled: bool = True
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# ---------- CRUD ----------
@router.get("/ai-models", response_model=list[AiModelOut])
async def list_models(
    q: str = Query("", description="搜索模型名称/服务商"),
    vendor: str = Query("", description="服务商"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AiModel).order_by(AiModel.id.desc())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(AiModel.name.like(like) | AiModel.vendor.like(like) | AiModel.alias.like(like))
    if vendor:
        stmt = stmt.where(AiModel.vendor == vendor)
    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    return res.scalars().all()


@router.post("/ai-models", response_model=AiModelOut, status_code=201)
async def create_model(data: AiModelIn, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.ai.write"))):
    obj = AiModel(alias=data.alias, name=data.name, vendor=data.vendor, addr=data.addr,
                  api_key=data.api_key, enabled=data.enabled)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.get("/ai-models/total-count")
async def total_count(db: AsyncSession = Depends(get_db)):
    n = await db.scalar(select(func.count()).select_from(AiModel))
    return {"total": n or 0}


@router.put("/ai-models/{mid}", response_model=AiModelOut)
async def update_model(mid: int, data: AiModelIn, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.ai.write"))):
    res = await db.execute(select(AiModel).where(AiModel.id == mid))
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="模型不存在")
    obj.alias = data.alias
    obj.name = data.name
    obj.vendor = data.vendor
    obj.addr = data.addr
    obj.api_key = data.api_key
    obj.enabled = data.enabled
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/ai-models/{mid}", status_code=204)
async def delete_model(mid: int, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.ai.write"))):
    res = await db.execute(select(AiModel).where(AiModel.id == mid))
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="模型不存在")
    await db.delete(obj)
    await db.commit()


@router.post("/ai-models/batch-delete", status_code=204)
async def batch_delete_models(ids: list[int], db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.ai.write"))):
    """批量删除 AI 模型配置。"""
    if not ids:
        return
    res = await db.execute(select(AiModel).where(AiModel.id.in_(ids)))
    for obj in res.scalars().all():
        await db.delete(obj)
    await db.commit()


class FetchModelsIn(BaseModel):
    """拉取模型请求：接入地址 + API KEY（Ollama 本地可留空）。"""
    addr: str
    api_key: Optional[str] = None


@router.post("/ai-models/fetch-models")
async def fetch_models(data: FetchModelsIn):
    """调用 OpenAI 兼容接口 GET {addr}/models 拉取可用模型列表。"""
    addr = (data.addr or "").strip().rstrip("/")
    if not addr:
        raise HTTPException(status_code=400, detail="请先填写接入地址")
    url = f"{addr}/models"
    headers = {"Authorization": f"Bearer {data.api_key.strip()}"} if (data.api_key or "").strip() else {}
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        resp = await asyncio.to_thread(urllib.request.urlopen, req, timeout=30)
        body = json.loads(resp.read().decode("utf-8"))
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"获取模型失败：{ex}")

    ids = []
    if isinstance(body, list):
        ids = [m.get("id") or m.get("name") or str(m) for m in body]
    elif isinstance(body, dict):
        if isinstance(body.get("data"), list):
            ids = [m.get("id") or m.get("name") or str(m) for m in body["data"]]
        elif isinstance(body.get("models"), list):
            ids = [m.get("id") or m.get("name") or str(m) for m in body["models"]]
        elif isinstance(body.get("model_ids"), list):
            ids = body["model_ids"]
    ids = [str(i).strip() for i in ids if str(i).strip()]
    if not ids:
        raise HTTPException(status_code=400, detail=f"接口未返回模型列表（{str(body)[:160]}）")
    return {"models": ids, "count": len(ids)}
