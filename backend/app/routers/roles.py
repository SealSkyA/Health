"""角色与权限管理 REST API：角色 CRUD + 权限点清单（仅拥有「权限管理」页权限者可操作）。"""
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal, get_db
from app.core.perms import PERM_ALL, PERM_GROUPS
from app.models.roles import Role, RolePerm
from app.models.user import User
from app.routers.auth import get_current_user, require_perm

router = APIRouter()

_CODE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{1,31}$")
ADMIN_CODE = "admin"
VIEWER_CODE = "viewer"


class RoleOut(BaseModel):
    code: str
    name: str
    desc: Optional[str] = None
    is_system: bool = False
    perms: list[str] = []
    user_count: int = 0


class RoleIn(BaseModel):
    code: str
    name: str
    desc: Optional[str] = None
    perms: list[str] = []


class RoleUpdateIn(BaseModel):
    name: str
    desc: Optional[str] = None
    perms: list[str] = []


async def _role_perms(db: AsyncSession, code: str) -> list[str]:
    rows = await db.execute(select(RolePerm.perm).where(RolePerm.role_code == code))
    return list(rows.scalars().all())


def _norm_perms(perms: list[str]) -> list[str]:
    out = []
    for p in perms:
        if p not in PERM_ALL:
            raise HTTPException(status_code=400, detail=f"未知权限点：{p}")
        if p not in out:
            out.append(p)
    return out


# ---------- 权限点清单 ----------
@router.get("/permissions")
async def permissions_defs(_user: User = Depends(get_current_user)):
    """权限点定义（登录即可读，供前端渲染勾选框）。"""
    return PERM_GROUPS


# ---------- 角色 CRUD ----------
@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    _can: User = Depends(require_perm("page.perms")),
):
    roles = (await db.execute(select(Role).order_by(Role.id))).scalars().all()
    out = []
    for r in roles:
        if r.code == ADMIN_CODE:
            perms, uc = PERM_ALL, await db.scalar(
                select(func.count()).select_from(User).where(User.role == ADMIN_CODE))
        else:
            perms, uc = await _role_perms(db, r.code), await db.scalar(
                select(func.count()).select_from(User).where(User.role == r.code))
        out.append(RoleOut(code=r.code, name=r.name, desc=r.desc,
                           is_system=r.is_system, perms=perms, user_count=uc or 0))
    return out


@router.post("/roles", response_model=RoleOut, status_code=201)
async def create_role(
    data: RoleIn,
    db: AsyncSession = Depends(get_db),
    _can: User = Depends(require_perm("page.perms")),
):
    code = data.code.strip()
    if not _CODE_RE.match(code):
        raise HTTPException(status_code=400, detail="角色编码需为字母开头、2~32 位字母数字下划线")
    if code in (ADMIN_CODE, VIEWER_CODE):
        raise HTTPException(status_code=400, detail="该角色编码为系统保留")
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="角色名称不能为空")
    exist = await db.scalar(select(Role).where(Role.code == code))
    if exist:
        raise HTTPException(status_code=400, detail="角色编码已存在")
    perms = _norm_perms(list(dict.fromkeys(data.perms)))
    db.add(Role(code=code, name=name, desc=data.desc, is_system=False))
    await db.flush()
    for p in perms:
        db.add(RolePerm(role_code=code, perm=p))
    await db.commit()
    return RoleOut(code=code, name=name, desc=data.desc, is_system=False,
                   perms=perms, user_count=0)


@router.put("/roles/{code}", response_model=RoleOut)
async def update_role(
    code: str,
    data: RoleUpdateIn,
    db: AsyncSession = Depends(get_db),
    _can: User = Depends(require_perm("page.perms")),
):
    r = await db.scalar(select(Role).where(Role.code == code))
    if not r:
        raise HTTPException(status_code=404, detail="角色不存在")
    if r.code == ADMIN_CODE:
        raise HTTPException(status_code=400, detail="超级管理员角色拥有全部权限，不可修改")
    if r.is_system:
        raise HTTPException(status_code=400, detail="内置角色不可修改，请新建自定义角色")
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="角色名称不能为空")
    r.name = name
    r.desc = data.desc
    perms = _norm_perms(list(dict.fromkeys(data.perms)))
    await db.execute(RolePerm.__table__.delete().where(RolePerm.role_code == r.code))
    for p in perms:
        db.add(RolePerm(role_code=r.code, perm=p))
    await db.commit()
    uc = await db.scalar(select(func.count()).select_from(User).where(User.role == r.code)) or 0
    return RoleOut(code=r.code, name=r.name, desc=r.desc, is_system=r.is_system,
                   perms=perms, user_count=uc)


@router.delete("/roles/{code}", status_code=204)
async def delete_role(
    code: str,
    db: AsyncSession = Depends(get_db),
    _can: User = Depends(require_perm("page.perms")),
):
    r = await db.scalar(select(Role).where(Role.code == code))
    if not r:
        raise HTTPException(status_code=404, detail="角色不存在")
    if r.is_system:
        raise HTTPException(status_code=400, detail="内置角色不可删除")
    uc = await db.scalar(select(func.count()).select_from(User).where(User.role == code)) or 0
    if uc:
        raise HTTPException(status_code=400, detail="该角色下仍有用户，请先调整用户角色")
    await db.execute(RolePerm.__table__.delete().where(RolePerm.role_code == code))
    await db.delete(r)
    await db.commit()