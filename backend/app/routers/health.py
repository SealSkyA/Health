"""健康检查与元信息。"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db

router = APIRouter()


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    """存活探针：验证进程与数据库连通。"""
    db_ok = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_ok = "error"
    return {"status": "ok", "db": db_ok, "app": get_settings().APP_NAME}


@router.get("/meta")
async def meta():
    return {"name": get_settings().APP_NAME, "version": "0.1.0"}