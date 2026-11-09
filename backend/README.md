# 壹健康 · 检查报告管理系统 — 后端

FastAPI + uvicorn + SQLAlchemy(async) + aiomysql + MySQL。

## 本地运行

```bash
python -m venv venv
venv\Scripts\activate        # Linux: source venv/bin/activate
pip install -r requirements.txt

# 准备数据库（本地或服务器 MySQL）
# mysql -uroot -p -e "CREATE DATABASE 3healthtrends CHARACTER SET utf8mb4;"

cp .env.example .env         # 按需修改 DB_PASSWORD 等
uvicorn app.main:app --host 127.0.0.1 --port 35000 --reload
```

启动时自动建表并写入默认管理员 `admin`（密码取 `.env` 的 `ADMIN_PASSWORD`）。

## 接口

- `GET /api/health` — 存活探针（含 DB 连通）
- `POST /api/auth/login` — 登录，返回 token
- `GET/POST /api/med-records` — 开方（处方）列表/新增，一次开方含多种药品明细
- `GET/DELETE /api/med-records/{id}`
- `GET /api/med-records/total-count`

OpenAPI 文档：`/docs`

## 目录

```
app/
├── main.py            # 入口
├── core/              # config / db / seed
├── models/            # SQLAlchemy 模型（user / med_records）
├── routers/           # 业务路由
├── schemas/           # Pydantic 模型
└── services/          # 业务逻辑（MinIO/OnlyOffice 等预留）
```

> 只读依赖当前环境的 Python 3.10+。生产环境一并复用同机「即刻提醒」的部署模式
> （systemd + nginx + 前端产物由后端托管），见 `../deployment/`。