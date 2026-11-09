"""存量表轻量迁移：为已有业务表补充 user_id 列（不动数据）。
兼容 sqlite / mysql 两种方言；部署时随 create_all 之后执行。"""
import logging

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import engine

logger = logging.getLogger("3healthtrends")

# 需要补 user_id 列的表（业务数据按用户隔离；存量数据置 NULL 归 admin 可见）
TABLES = ("reports", "prescriptions", "stored_files", "ai_analyses")

# 需要补的其他列：(表, 列, 类型)
EXTRA_COLUMNS = (
    ("users", "avatar", "VARCHAR(255) NULL"),
    ("report_interests", "doc_id", "INTEGER NULL"),
    ("prescriptions", "note", "TEXT NULL"),
    ("report_docs", "attach_json", "TEXT NULL"),
)


async def _table_columns(driver: str, conn, table: str) -> set[str]:
    if driver == "sqlite":
        rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
        return {r[1] for r in rows}
    rows = (await conn.execute(text(f"SHOW COLUMNS FROM `{table}`"))).fetchall()
    return {r[0] for r in rows}


async def ensure_user_id_columns():
    settings = get_settings()
    driver = settings.DB_DRIVER
    async with engine.begin() as conn:
        for t in TABLES:
            cols = await _table_columns(driver, conn, t)
            if "user_id" in cols:
                continue
            await conn.execute(text(f"ALTER TABLE {t} ADD COLUMN user_id INTEGER NULL"))
            logger.info("migrate: added user_id to %s", t)
        for table, col, ddl in EXTRA_COLUMNS:
            cols = await _table_columns(driver, conn, table)
            if col in cols:
                continue
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
            logger.info("migrate: added %s to %s", col, table)