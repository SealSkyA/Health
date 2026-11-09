"""认证：登录、当前用户、资料更新、修改密码、登录记录、Token 校验。"""
import base64
import os
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal, get_db
from app.core.perms import PERM_ALL
from app.models.login_logs import LoginLog
from app.models.roles import Role, RolePerm
from app.models.user import User

router = APIRouter()
settings = get_settings()


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    nickname: str | None = None
    phone: str | None = None
    email: str | None = None
    org: str | None = None
    avatar: str | None = None       # 头像静态相对路径（/static/avatars/x.jpg）
    role: str = "admin"

    class Config:
        from_attributes = True


class ProfileIn(BaseModel):
    nickname: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    org: Optional[str] = None


class AvatarB64In(BaseModel):
    data: str                                  # data URL 或纯 base64
    filename: Optional[str] = None
    content_type: Optional[str] = None


# 允许的头像扩展名与 content-type 映射
_AVATAR_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def _pick_image_ext(filename: Optional[str], content_type: Optional[str]) -> str:
    ext = os.path.splitext((filename or "").lower())[1]
    if ext in _AVATAR_EXTS:
        return ".jpg" if ext == ".jpeg" else ext
    ct = (content_type or "").lower()
    for e, m in ((".jpg", "image/jpeg"), (".png", "image/png"), (".gif", "image/gif"),
                 (".webp", "image/webp"), (".bmp", "image/bmp")):
        if ct == m:
            return e
    return ".jpg"


def _b64decode(s: str) -> bytes:
    txt = (s or "").strip()
    if txt.startswith("data:"):
        txt = txt.split(",", 1)[-1]
    try:
        return base64.b64decode(txt, validate=False)
    except Exception:
        return b""


def _remove_avatar_file(rel: Optional[str]):
    """删除旧头像文件（只允许 uploads/avatars 下的相对路径）。"""
    if not rel:
        return
    p = rel.replace("\\", "/")
    if ".." in p or p.startswith("/") or ":" in p or not p.startswith("avatars/"):
        return
    fp = os.path.join(get_settings().UPLOAD_DIR, p)
    try:
        if os.path.isfile(fp):
            os.remove(fp)
    except OSError:
        pass


async def _require_user(request: Request, db: AsyncSession) -> User:
    token = _token_from(request)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    return await _get_user_by_token(db, token)


class ChangePwdIn(BaseModel):
    old_password: str
    new_password: str


class LoginLogOut(BaseModel):
    id: int
    ip: Optional[str] = None
    device: Optional[str] = None
    status: str = "成功"
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


def sign_token(sub: str) -> str:
    payload = {
        "sub": sub,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _hash(pw: str) -> str:
    import hashlib
    return hashlib.sha256(pw.encode()).hexdigest()


async def _get_user_by_token(db: AsyncSession, token: str) -> User:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except Exception:
        raise HTTPException(status_code=401, detail="无效或过期的 Token")
    username = payload.get("sub")
    res = await db.execute(select(User).where(User.username == username))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="账号已停用")
    return user


def _token_from(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


async def get_current_user(request: Request) -> User:
    """依赖：要求已登录且账号启用，返回当前用户。

    注：函数体内自行开启会话而非声明 db 子依赖，规避当前 FastAPI 版本
    对「依赖函数再声明 Depends(get_db)」的展开失败（AsyncSession 被误判为字段）。
    """
    token = _token_from(request)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    async with AsyncSessionLocal() as db:
        return await _get_user_by_token(db, token)


async def require_admin(request: Request) -> User:
    """依赖：要求当前用户为管理员（role=admin）。"""
    user = await get_current_user(request)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可执行此操作")
    return user


def require_perm(perm: str):
    """依赖工厂：要求当前用户拥有指定权限点；admin 超管恒放行。

    注：依赖函数仅声明 request 参数（不自建 db 子依赖），规避当前 FastAPI
    版本对函数依赖展开的错误。
    """

    async def _check(request: Request) -> User:
        user = await get_current_user(request)
        if user.role == "admin":
            return user
        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(RolePerm).where(RolePerm.role_code == user.role, RolePerm.perm == perm)
            )
        if not row:
            raise HTTPException(status_code=403, detail="无权限执行此操作")
        return user

    return _check


async def user_has_perm(db: AsyncSession, user: User, perm: str) -> bool:
    """纯权限判定（无 HTTP 依赖，供 AI 工具等内部调用）：admin 恒放行，否则查角色权限表。"""
    if user.role == "admin":
        return True
    row = await db.scalar(
        select(RolePerm).where(RolePerm.role_code == user.role, RolePerm.perm == perm)
    )
    return row is not None


@router.get("/my-permissions")
async def my_permissions(request: Request):
    """当前用户角色与权限点列表（登录即可）。"""
    user = await get_current_user(request)
    async with AsyncSessionLocal() as db:
        rows = await db.execute(select(RolePerm.perm).where(RolePerm.role_code == user.role))
        perms = list(rows.scalars().all())
        role = await db.scalar(select(Role).where(Role.code == user.role))
        role_name = role.name if role else user.role
    if user.role == "admin":
        perms = PERM_ALL
    return {"role": user.role, "role_name": role_name, "perms": perms}


@router.post("/login", response_model=dict)
async def login(data: LoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    """登录：校验口令、签发 JWT、记录登录日志。"""
    res = await db.execute(select(User).where(User.username == data.username))
    user = res.scalar_one_or_none()

    # 记录登录日志（成功/失败）
    ip = request.client.host if request else "127.0.0.1"
    # 经 nginx 反代取 X-Forwarded-For
    xff = request.headers.get("X-Forwarded-For") if request else None
    if xff:
        ip = xff.split(",")[0].strip()
    device = (request.headers.get("User-Agent") or "")[:120] if request else ""

    if not user:
        db.add(LoginLog(username=data.username, ip=ip, device=device, status="失败"))
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户或密码错误")

    if user.hashed_password != _hash(data.password):
        db.add(LoginLog(user_id=user.id, username=user.username, ip=ip, device=device, status="失败"))
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户或密码错误")

    if not user.is_active:
        db.add(LoginLog(user_id=user.id, username=user.username, ip=ip, device=device, status="失败"))
        await db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用，请联系管理员")

    db.add(LoginLog(user_id=user.id, username=user.username, ip=ip, device=device, status="成功"))
    await db.commit()

    return {"access_token": sign_token(user.username), "token_type": "bearer",
            "user": UserOut.model_validate(user).model_dump()}


@router.get("/me", response_model=UserOut)
async def me(request: Request, db: AsyncSession = Depends(get_db)):
    token = _token_from(request)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user = await _get_user_by_token(db, token)
    return user


@router.put("/profile", response_model=UserOut)
async def update_profile(data: ProfileIn, request: Request, db: AsyncSession = Depends(get_db)):
    token = _token_from(request)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user = await _get_user_by_token(db, token)
    if data.nickname is not None:
        user.nickname = data.nickname
    if data.phone is not None:
        user.phone = data.phone
    if data.email is not None:
        user.email = data.email
    if data.org is not None:
        user.org = data.org
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/change-password")
async def change_password(data: ChangePwdIn, request: Request, db: AsyncSession = Depends(get_db)):
    token = _token_from(request)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user = await _get_user_by_token(db, token)
    if user.hashed_password != _hash(data.old_password):
        raise HTTPException(status_code=400, detail="原密码错误")
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="新密码至少 8 位")
    user.hashed_password = _hash(data.new_password)
    await db.commit()
    return {"detail": "密码已修改"}


@router.post("/avatar", response_model=UserOut)
async def upload_avatar(
    file: UploadFile = File(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """上传当前用户头像（覆盖旧图），保存到 uploads/avatars/。"""
    user = await _require_user(request, db)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="头像不超过 2MB")
    ext = _pick_image_ext(file.filename, file.content_type)
    d = os.path.join(get_settings().UPLOAD_DIR, "avatars")
    os.makedirs(d, exist_ok=True)
    _remove_avatar_file(user.avatar)
    name = f"{user.id}{ext}"
    with open(os.path.join(d, name), "wb") as fh:
        fh.write(data)
    user.avatar = f"avatars/{name}"
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/avatar-json", response_model=UserOut)
async def upload_avatar_json(data: AvatarB64In, request: Request, db: AsyncSession = Depends(get_db)):
    """上传头像（base64，规避部分网络对 multipart 的拦截）。"""
    user = await _require_user(request, db)
    raw = _b64decode(data.data)
    if not raw:
        raise HTTPException(status_code=400, detail="图片编码无效")
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="头像不超过 2MB")
    ext = _pick_image_ext(data.filename, data.content_type)
    d = os.path.join(get_settings().UPLOAD_DIR, "avatars")
    os.makedirs(d, exist_ok=True)
    _remove_avatar_file(user.avatar)
    name = f"{user.id}{ext}"
    with open(os.path.join(d, name), "wb") as fh:
        fh.write(raw)
    user.avatar = f"avatars/{name}"
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/avatar", response_model=UserOut)
async def delete_avatar(request: Request, db: AsyncSession = Depends(get_db)):
    """移除当前用户头像，回退为昵称首字。"""
    user = await _require_user(request, db)
    _remove_avatar_file(user.avatar)
    user.avatar = None
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/login-logs", response_model=list[LoginLogOut])
async def login_logs(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _can: User = Depends(require_perm("page.users")),
):
    res = await db.execute(select(LoginLog).order_by(LoginLog.id.desc()).limit(limit))
    return res.scalars().all()
