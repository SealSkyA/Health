"""系统设置 REST API：键值对存储。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.routers.auth import require_perm
from app.models.app_settings import AppSetting
from app.models.user import User

router = APIRouter()

# 允许的默认设置键（用于前端回填）
DEFAULTS = {
    "system_name": "壹健康 · 检查报告管理系统",
    "version": "V1.0.0",
    "timezone": "Asia/Shanghai (UTC+8)",
    "data_unit": "公制 (国际单位)",
    "report_signature": "壹健康体检中心",
    "sms_notify": "true",
    "highlight_abnormal": "true",
    "ai_summary": "false",
}


class SettingsOut(BaseModel):
    system_name: str
    version: str
    timezone: str
    data_unit: str
    report_signature: str
    sms_notify: bool
    highlight_abnormal: bool
    ai_summary: bool


class SettingsIn(BaseModel):
    system_name: str
    version: str
    timezone: str
    data_unit: str
    report_signature: str
    sms_notify: bool
    highlight_abnormal: bool
    ai_summary: bool


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("1", "true", "yes", "on")


@router.get("/settings", response_model=SettingsOut)
async def get_settings(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(AppSetting))
    rows = {r.key: r.value for r in res.scalars().all()}
    return {
        "system_name": rows.get("system_name", DEFAULTS["system_name"]),
        "version": rows.get("version", DEFAULTS["version"]),
        "timezone": rows.get("timezone", DEFAULTS["timezone"]),
        "data_unit": rows.get("data_unit", DEFAULTS["data_unit"]),
        "report_signature": rows.get("report_signature", DEFAULTS["report_signature"]),
        "sms_notify": _to_bool(rows.get("sms_notify", DEFAULTS["sms_notify"])),
        "highlight_abnormal": _to_bool(rows.get("highlight_abnormal", DEFAULTS["highlight_abnormal"])),
        "ai_summary": _to_bool(rows.get("ai_summary", DEFAULTS["ai_summary"])),
    }


@router.put("/settings", response_model=SettingsOut)
async def save_settings(data: SettingsIn, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.settings.write"))):
    mapping = {
        "system_name": data.system_name,
        "version": data.version,
        "timezone": data.timezone,
        "data_unit": data.data_unit,
        "report_signature": data.report_signature,
        "sms_notify": "true" if data.sms_notify else "false",
        "highlight_abnormal": "true" if data.highlight_abnormal else "false",
        "ai_summary": "true" if data.ai_summary else "false",
    }
    for key, val in mapping.items():
        row = await db.execute(select(AppSetting).where(AppSetting.key == key))
        obj = row.scalar_one_or_none()
        if obj:
            obj.value = val
        else:
            db.add(AppSetting(key=key, value=val))
    await db.commit()
    return await get_settings(db)
