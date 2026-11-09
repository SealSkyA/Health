"""全局配置：所有值均可通过环境变量覆盖（部署时写入 .env）。"""
from functools import lru_cache
import os

from dotenv import load_dotenv

# backend 根：app/core/config.py 向上三级 = <backend>/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(BASE_DIR, ".env"))


class Settings:
    # 基础
    APP_NAME: str = "壹健康 · 检查报告管理系统"
    API_PREFIX: str = "/api"
    TIMEZONE: str = "Asia/Shanghai"

    # 服务
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "35000"))

    # 安全（部署时必须覆盖为强随机值）
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "change-me")

    # 数据库（MySQL，仅本机 / 开发可切 sqlite）
    DB_DRIVER: str = os.getenv("DB_DRIVER", "mysql")  # mysql | sqlite
    DB_HOST: str = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
    DB_USER: str = os.getenv("DB_USER", "root")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")  # 含特殊字符需 URL 编码
    DB_NAME: str = os.getenv("DB_NAME", "3healthtrends")

    # MinIO（对象存储）
    MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000")
    MINIO_ACCESS_KEY: str = os.getenv("MINIO_ACCESS_KEY", "")
    MINIO_SECRET_KEY: str = os.getenv("MINIO_SECRET_KEY", "")
    MINIO_BUCKET: str = os.getenv("MINIO_BUCKET", "3healthtrends")
    MINIO_PUBLIC_BASE: str = os.getenv("MINIO_PUBLIC_BASE", "/3healthtrends/")

    # OnlyOffice（文档预览/编辑）
    OFFICE_PUBLIC_BASE: str = os.getenv("OFFICE_PUBLIC_BASE", "http://172.17.0.1:8000")
    OFFICE_SERVER_URL: str = os.getenv("OFFICE_SERVER_URL", "http://172.17.0.1:8081")
    OFFICE_SECRET: str = os.getenv("OFFICE_SECRET", "")

    # 上传
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", None) or os.path.join(BASE_DIR, "uploads")
    MAX_UPLOAD_SIZE: int = int(os.getenv("MAX_UPLOAD_SIZE", "10485760"))  # 10MB

    # CORS
    CORS_ORIGINS: list = [
        o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()
    ] or ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:35000"]

    def database_url(self) -> str:
        """构造数据库 URL。sqlite 用于本地开发，mysql 用于生产。"""
        if self.DB_DRIVER == "sqlite":
            return f"sqlite+aiosqlite:///{os.path.join(BASE_DIR, self.DB_NAME + '.db')}"
        from urllib.parse import quote_plus
        return (
            f"mysql+aiomysql://{self.DB_USER}:{quote_plus(self.DB_PASSWORD)}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()