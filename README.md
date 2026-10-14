# OCI 云服务器管理面板（oci-panel）

重写自 [oci-helper](https://github.com/Yohann0617/oci-helper) 的 Oracle Cloud (OCI) 三方管理面板，
前后端分离架构。

## 技术栈

| 部分 | 技术 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · SQLAlchemy 2.0 · SQLite · APScheduler · OCI Python SDK |
| 前端 | React 19 · Ant Design 5 · Vite 8 · TypeScript · zustand · ECharts |
| 部署 | Docker Compose 一键启动 |

## 快速启动

```bash
cd oci-panel
docker compose up --build -d
```

- 前端：http://localhost:8080（默认账号 `admin` / `admin123`）
- 后端 API 文档：http://localhost:8818/docs

数据文件保存在 `./data/oci-panel.db`（SQLite，备份拷走这一个文件就行）。

## 本地开发

后端：

```bash
cd backend
pip install -e .
uvicorn app.main:app --port 8818 --reload
```

前端：

```bash
cd frontend
npm install
npm run dev   # 默认代理 /api/v1 与 /ws 到 localhost:8818
```

## 目录结构

```
oci-panel/
├── backend/          # FastAPI 后端（/api/v1）
│   └── app/
│       ├── routers/  # auth、tenants、instances、snatch、network…
│       ├── services/ # OCI client 工厂（租户私钥 Fernet 加密存储）
│       ├── workers/  # 抢机/换 IP 后台任务（APScheduler + asyncio）
│       └── ws/       # WebSocket 推送（任务进度、实时日志）
├── frontend/         # React + Ant Design（11 个页面，支持暗黑模式）
├── data/             # SQLite 数据（自动创建，git 忽略）
└── docker-compose.yml
```

## 接口约定

- 统一前缀 `/api/v1`，统一响应信封 `{"code":0,"msg":"ok","data":...}`（code 0 为成功）
- 认证：`POST /api/v1/auth/login` 返回 `{token, user}`，其余接口带 `Authorization: Bearer <token>`
- 实时通道：`/ws/logs`、`/ws/tasks`

## 安全提醒

- 生产部署前务必设置固定的 `SECRET_KEY` 与 `FERNET_KEY`（见 `backend/README.md` 生成方式），
  当前默认值仅适合本地开发。
- 建议局域网使用或经 Nginx 反向代理配置 HTTPS 后再暴露。

## 当前状态

脚手架阶段：登录鉴权、租户/抢机任务/DNS 的落库逻辑真实可用；
实例列表、抢机核心 `launch_instance`、换 IP、安全组等 OCI 强相关调用为桩逻辑，
代码中以中文 `TODO` 标出，按 P0 优先级逐个接入真实 OCI SDK 调用。
