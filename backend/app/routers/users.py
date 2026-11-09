"""用户管理：列表、新增、编辑、重置密码、启停、删除（拥有「用户管理」页权限者可操作）。"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.roles import Role
from app.models.user import User
from app.routers.auth import _hash, get_current_user, require_perm

router = APIRouter()


class UserAdminOut(BaseModel):
    id: int
    username: str
    nickname: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    org: Optional[str] = None
    role: str = "admin"
    is_active: bool = True
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserCreateIn(BaseModel):
    username: str
    password: str
    nickname: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    org: Optional[str] = None
    role: str = "viewer"


class UserUpdateIn(BaseModel):
    nickname: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    org: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None  # 留空表示不重置密码


async def _norm_role(db: AsyncSession, role: Optional[str]) -> Optional[str]:
    """校验角色编码存在于角色表，返回规范化值。"""
    if role is None:
        return None
    row = await db.scalar(select(Role).where(Role.code == role))
    if not row:
        raise HTTPException(status_code=400, detail="角色不存在")
    return role


@router.get("", response_model=list[UserAdminOut])
async def list_users(
    request: Request,
    q: str = Query("", description="搜索用户名/昵称/手机/机构"),
    db: AsyncSession = Depends(get_db),
    _can: User = Depends(require_perm("page.users")),
):
    stmt = select(User).order_by(User.id)
    qq = q.strip()
    if qq:
        like = f"%{qq}%"
        stmt = stmt.where(or_(
            User.username.like(like), User.nickname.like(like),
            User.phone.like(like), User.org.like(like),
        ))
    res = await db.execute(stmt)
    return res.scalars().all()


@router.post("", response_model=UserAdminOut, status_code=201)
async def create_user(
    data: UserCreateIn,
    db: AsyncSession = Depends(get_db),
    _can: User = Depends(require_perm("page.users")),
):
    username = data.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 位")
    exist = await db.scalar(select(User).where(User.username == username))
    if exist:
        raise HTTPException(status_code=400, detail="用户名已存在")
    role = await _norm_role(db, data.role) or "viewer"
    u = User(
        username=username,
        hashed_password=_hash(data.password),
        nickname=data.nickname,
        phone=data.phone,
        email=data.email,
        org=data.org,
        role=role,
        is_active=True,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@router.put("/{uid}", response_model=UserAdminOut)
async def update_user(
    uid: int,
    data: UserUpdateIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _can: User = Depends(require_perm("page.users")),
):
    me = await get_current_user(request)
    u = await db.get(User, uid)
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")

    body = data.model_dump(exclude_unset=True)

    # 资料/角色字段（显式提交才生效，允许置空）
    for f in ("nickname", "phone", "email", "org"):
        if f in body:
            setattr(u, f, body[f])
    if "role" in body:
        u.role = await _norm_role(db, body["role"])

    # 停用/角色变更防呆：不能把自己停用或降权
    if u.id == me.id and (body.get("is_active") is False or (u.id == me.id and "role" in body and u.role != "admin")):
        raise HTTPException(status_code=400, detail="不能停用或降权当前登录账号")

    # 最后一个启用管理员不能被停用/删除
    if body.get("is_active") is False and u.role == "admin":
        cnt = await db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True), User.role == "admin"))
        if (cnt or 0) <= 1:
            raise HTTPException(status_code=400, detail="至少保留一个启用的管理员账号")

    if "is_active" in body:
        u.is_active = bool(body["is_active"])
    if body.get("password"):
        if len(body["password"]) < 8:
            raise HTTPException(status_code=400, detail="新密码至少 8 位")
        u.hashed_password = _hash(body["password"])

    await db.commit()
    await db.refresh(u)
    return u


@router.delete("/{uid}", status_code=204)
async def delete_user(
    uid: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _can: User = Depends(require_perm("page.users")),
):
    me = await get_current_user(request)
    u = await db.get(User, uid)
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if u.id == me.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")
    if u.role == "admin" and u.is_active:
        cnt = await db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True), User.role == "admin"))
        if (cnt or 0) <= 1:
            raise HTTPException(status_code=400, detail="至少保留一个启用的管理员账号")
    await db.delete(u)
    await db.commit()