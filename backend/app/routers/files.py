"""文件存储 REST API：元数据入库，对象存 MinIO。"""
import base64
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.routers.auth import require_perm
from app.models.files import StoredFile
from app.models.user import User

router = APIRouter()


def _minio_client():
    from minio import Minio
    s = get_settings()
    if not s.MINIO_ACCESS_KEY or not s.MINIO_SECRET_KEY:
        raise HTTPException(status_code=503, detail="MinIO 未配置")
    return Minio(
        s.MINIO_ENDPOINT,
        access_key=s.MINIO_ACCESS_KEY,
        secret_key=s.MINIO_SECRET_KEY,
        secure=False,
    )


def _ensure_bucket(client, bucket: str):
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


# ---------- Schemas ----------
class FileOut(BaseModel):
    id: int
    filename: str
    object_key: str
    content_type: Optional[str] = None
    size: int = 0
    bucket: Optional[str] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# ---------- CRUD ----------
def _scope(user: User):
    """数据隔离条件：admin 全量；其他用户只见自己上传的（存量 user_id=NULL 归 admin）。"""
    return None if user.role == "admin" else StoredFile.user_id == user.id


@router.get("/files", response_model=list[FileOut])
async def list_files(
    q: str = Query("", description="搜索文件名"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _can: User = Depends(require_perm("page.files")),
):
    stmt = select(StoredFile).order_by(StoredFile.id.desc())
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(StoredFile.filename.like(like))
    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    return res.scalars().all()


@router.get("/files/total-count")
async def total_count(db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("page.files"))):
    stmt = select(func.count()).select_from(StoredFile)
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    n = await db.scalar(stmt)
    return {"total": n or 0}


@router.post("/files", response_model=FileOut, status_code=201)
async def upload_file(file: UploadFile = File(...), db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.files.write"))):
    """上传到 MinIO 并记录元数据。"""
    s = get_settings()
    client = _minio_client()
    _ensure_bucket(client, s.MINIO_BUCKET)

    data = await file.read()
    if len(data) > s.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="文件超过大小限制")
    return await _store_file(client, data, file.filename, file.content_type, db, _can)


class FileB64In(BaseModel):
    """文件 JSON 上传体：data URL 或纯 base64（规避部分网络对 multipart 的拦截）。"""
    data: str
    filename: Optional[str] = None
    content_type: Optional[str] = None


@router.post("/files-json", response_model=FileOut, status_code=201)
async def upload_file_json(body: FileB64In, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.files.write"))):
    """上传到 MinIO（JSON + base64）。"""
    s = get_settings()
    client = _minio_client()
    _ensure_bucket(client, s.MINIO_BUCKET)

    raw = _b64decode(body.data)
    if len(raw) > s.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="文件超过大小限制")
    return await _store_file(client, raw, body.filename, body.content_type, db, _can)


async def _store_file(client, data: bytes, filename, content_type, db: AsyncSession, user: User):
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    import io, uuid
    ext = os.path.splitext(filename or "")[1]
    object_key = f"files/{uuid.uuid4().hex}{ext}"
    client.put_object(
        get_settings().MINIO_BUCKET, object_key, io.BytesIO(data), length=len(data),
        content_type=content_type or "application/octet-stream",
    )
    obj = StoredFile(
        user_id=user.id,
        filename=filename or object_key,
        object_key=object_key,
        content_type=content_type,
        size=len(data),
        bucket=get_settings().MINIO_BUCKET,
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


def _b64decode(s: str) -> bytes:
    txt = (s or "").strip()
    if txt.startswith("data:"):
        txt = txt.split(",", 1)[-1]
    try:
        return base64.b64decode(txt, validate=False)
    except Exception:
        raise HTTPException(status_code=400, detail="文件编码无效")


@router.get("/files/{fid}/download")
async def download_file(fid: int, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("page.files"))):
    """从 MinIO 下载文件，以字节流返回。"""
    stmt = select(StoredFile).where(StoredFile.id == fid)
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    res = await db.execute(stmt)
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="文件不存在")
    client = _minio_client()
    try:
        resp = client.get_object(obj.bucket, obj.object_key)
    except Exception:
        raise HTTPException(status_code=404, detail="文件对象不存在")
    content = resp.read()
    resp.close()
    resp.release_conn()
    return Response(
        content=content,
        media_type=obj.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{obj.filename}"'},
    )


@router.delete("/files/{fid}", status_code=204)
async def delete_file(fid: int, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.files.write"))):
    stmt = select(StoredFile).where(StoredFile.id == fid)
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    res = await db.execute(stmt)
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="文件不存在")
    # 删 MinIO 对象
    client = _minio_client()
    try:
        client.remove_object(obj.bucket, obj.object_key)
    except Exception:
        pass  # 元数据删除优先，对象删除失败不阻断
    await db.delete(obj)
    await db.commit()


@router.post("/files/batch-delete", status_code=204)
async def batch_delete_files(ids: list[int], db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.files.write"))):
    """批量删除文件：按 id 列表删除元数据与 MinIO 对象。"""
    if not ids:
        return
    stmt = select(StoredFile).where(StoredFile.id.in_(ids))
    _sc = _scope(_can)
    if _sc is not None:
        stmt = stmt.where(_sc)
    res = await db.execute(stmt)
    objs = res.scalars().all()
    client = _minio_client()
    for obj in objs:
        try:
            client.remove_object(obj.bucket, obj.object_key)
        except Exception:
            pass
    for obj in objs:
        await db.delete(obj)
    await db.commit()


class FolderIn(BaseModel):
    name: str


@router.post("/files/new-folder", status_code=201)
async def create_folder(data: FolderIn, db: AsyncSession = Depends(get_db), _can: User = Depends(require_perm("op.files.write"))):
    """在 MinIO 创建一个空文件夹（对象键以 / 结尾），并入库一条元数据。"""
    import uuid
    s = get_settings()
    client = _minio_client()
    _ensure_bucket(client, s.MINIO_BUCKET)

    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="文件夹名称不能为空")

    object_key = f"folders/{uuid.uuid4().hex}/{name}/"
    client.put_object(s.MINIO_BUCKET, object_key, b"", length=0,
                      content_type="application/x-directory")

    obj = StoredFile(
        user_id=_can.id,
        filename=name, object_key=object_key,
        content_type="folder", size=0, bucket=s.MINIO_BUCKET,
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj
