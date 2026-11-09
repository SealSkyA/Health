"""启动时写入默认数据：默认管理员、内置角色（admin 超管 / viewer 只读）。"""
import hashlib
import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.core.perms import VIEWER_DEFAULT
from app.models.roles import Role, RolePerm
from app.models.user import User

logger = logging.getLogger("3healthtrends")


async def seed_defaults():
    settings = get_settings()
    async with AsyncSessionLocal() as db:
        # 1) 默认管理员账号
        res = await db.execute(select(User).where(User.username == "admin"))
        admin = res.scalar_one_or_none()
        hashed = hashlib.sha256(settings.ADMIN_PASSWORD.encode()).hexdigest()
        if admin is None:
            db.add(User(username="admin", nickname="超级管理员", role="admin",
                        hashed_password=hashed))
            await db.commit()
            logger.info("Seeded default admin (username=admin)")
        elif admin.hashed_password != hashed:
            # 密码已变化：刷新为 .env 中 ADMIN_PASSWORD 对应的哈希
            admin.hashed_password = hashed
            await db.commit()
            logger.info("Admin password refreshed from .env")
        else:
            logger.info("Admin exists, skip seed")

        # 2) 内置角色：admin（超管，全权不落库）+ viewer（只读，默认五个页面可见）
        for code, name, desc, perms in (
            ("admin", "超级管理员", "系统内置角色：拥有全部权限", []),
            ("viewer", "只读", "系统内置角色：可查看业务数据，不可修改", VIEWER_DEFAULT),
        ):
            role = await db.scalar(select(Role).where(Role.code == code))
            if role is None:
                db.add(Role(code=code, name=name, desc=desc, is_system=True))
                if perms:
                    for p in perms:
                        db.add(RolePerm(role_code=code, perm=p))
                await db.commit()
                logger.info("Seeded built-in role: %s", code)
            else:
                # 保持内置角色名称/描述一致
                role.name, role.desc = name, desc
                role.is_system = True
                if code == "viewer" and perms:
                    # 内置只读角色自愈：权限点严格对齐 VIEWER_DEFAULT
                    # （多出的写/管理权限一律移除，避免被误改后永久残留提权）
                    cur = (await db.execute(
                        select(RolePerm).where(RolePerm.role_code == code))).scalars().all()
                    exist = {p.perm for p in cur}
                    want = set(perms)
                    for row in cur:
                        if row.perm not in want:
                            await db.delete(row)
                    for p in perms:
                        if p not in exist:
                            db.add(RolePerm(role_code=code, perm=p))
                await db.commit()
                logger.info("Role exists, ensure builtin: %s", code)