"""应用入口：uvicorn app.main:app"""
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.db import engine, Base
from app.core.migrate import ensure_user_id_columns
from app.core.seed import seed_defaults
from app.routers import health, auth, med_records, templates, reports, ai_models, files, ai  # noqa: F401
from app.routers import settings as settings_router  # noqa: F401
from app.routers import users  # noqa: F401
from app.routers import roles  # noqa: F401

# 显式导入模型，确保 Base.metadata 注册全部表（用于 create_all）
from app.models import user as _m_user  # noqa: F401
from app.models import med_records as _m_med  # noqa: F401
from app.models import ai_analyses as _m_ai_ana  # noqa: F401
from app.models import templates as _m_tpl  # noqa: F401
from app.models import reports as _m_rpt  # noqa: F401
from app.models import ai_models as _m_ai  # noqa: F401
from app.models import files as _m_files  # noqa: F401
from app.models import login_logs as _m_logs  # noqa: F401
from app.models import app_settings as _m_settings  # noqa: F401
from app.models import ai_sessions as _m_ai_sessions  # noqa: F401
from app.models import ai_agent_tasks as _m_ai_tasks  # noqa: F401
from app.models import roles as _m_roles  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("3healthtrends")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时建表（生产用 Alembic 迁移，这里骨架阶段自动建表便于本地验证）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_user_id_columns()
    await seed_defaults()
    logger.info("DB ready. App=%s tz=%s", settings.APP_NAME, settings.TIMEZONE)
    yield
    await engine.dispose()


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 业务路由：统一挂 /api 下，auth 单独带命名空间 /api/auth
app.include_router(health.router, prefix=settings.API_PREFIX, tags=["health"])
app.include_router(med_records.router, prefix=settings.API_PREFIX, tags=["med-records"])
app.include_router(auth.router, prefix=f"{settings.API_PREFIX}/auth", tags=["auth"])
app.include_router(templates.router, prefix=settings.API_PREFIX, tags=["templates"])
app.include_router(reports.router, prefix=settings.API_PREFIX, tags=["reports"])
app.include_router(ai_models.router, prefix=settings.API_PREFIX, tags=["ai-models"])
app.include_router(ai.router, prefix=settings.API_PREFIX, tags=["ai"])
app.include_router(files.router, prefix=settings.API_PREFIX, tags=["files"])
app.include_router(settings_router.router, prefix=settings.API_PREFIX, tags=["settings"])
app.include_router(users.router, prefix=f"{settings.API_PREFIX}/users", tags=["users"])
app.include_router(roles.router, prefix=settings.API_PREFIX, tags=["roles"])

# 前端构建产物由后端托管（部署及本地打包后）
app.mount("/static", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")