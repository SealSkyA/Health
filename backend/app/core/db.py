"""SQLAlchemy 异步引擎与会话。"""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url(),
    echo=False,
    # 说明：SQLAlchemy 2.0.35 + aiomysql 下 pool_pre_ping 会因 ping() 缺少
    # reconnect 参数而报错，故关闭 pre_ping，仅依赖 pool_recycle 回收失效连接。
    pool_pre_ping=False,
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    """FastAPI 依赖：每请求一个会话。"""
    async with AsyncSessionLocal() as session:
        yield session