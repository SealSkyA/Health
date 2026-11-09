# 壹健康 · 检查报告管理系统

前后端分离应用。**部署目标**：生产服务器 `192.168.58.52` → `/home/3HealthTrends/`。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.10+ / FastAPI / uvicorn / SQLAlchemy(async) |
| 前端 | Vue3 / Vite / Vue Router / Axios |
| 数据库 | MySQL 8（仅本机，本地开发可用 SQLite 回退） |
| 对象存储 | MinIO（预留） |
| 文档 | OnlyOffice（预留） |

## 目录

```
backend/      FastAPI 后端（app/main.py 为入口）
frontend/     Vue3 前端（src/ 源码）
deployment/   systemd / nginx 部署配置
docs/         运维参考
```

## 本地开发

```bash
# 后端（默认 MySQL，本地可用 sqlite）
cd backend
python -m venv venv
# Windows: venv\Scripts\activate ; Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 修改 DB_DRIVER=sqlite 可本地跑 SQLite
uvicorn app.main:app --host 127.0.0.1 --port 35000 --reload

# 前端（另开一个终端）
cd frontend
npm install
npm run dev                    # http://localhost:5173 (已配置 /api 代理到 35000)
```

启动后后端自动建表并 seed 默认管理员 `admin`（密码取 `.env` 的 `ADMIN_PASSWORD`）。

## 已实现功能（骨架）

- 8 个页面（首页/报告模板/AI配置/检查报告/用药记录/文件存储/个人中心/系统设置），新拟物风格（亮/暗/跟随系统主题）
- **用药记录**：一次开方多药模型，列表 + 新增弹窗（可增删多种药品明细），对接后端 REST
- 认证：`POST /api/auth/login` 返回 JWT
- 健康检查：`GET /api/health`

## 待实施

- 报告模板 / 检查报告 / AI 配置 / 文件存储 的后端 CRUD 与 MinIO/OnlyOffice 接入
- 部署到 `/home/3HealthTrends/`（见 `deployment/` 与 `docs/`）

> ⚠️ 含服务器凭据的运维文档见 `docs/`，机密等级高，禁止公开外传。