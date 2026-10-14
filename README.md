# zy-panel · 多云服务器管理面板

自托管的多云服务器管理面板：一个界面管理 Oracle Cloud (OCI) 与阿里云（国内版 / 国际版）的实例、网络、存储与费用。架构按多厂商注册表设计，后续可扩展 AWS / GCP / Azure。

## 技术栈

| 部分 | 技术 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · SQLAlchemy 2.0 · SQLite · APScheduler · OCI Python SDK · Aliyun Python SDK |
| 前端 | React 19 · Ant Design 5 · Vite · TypeScript · ECharts |
| 部署 | Docker Compose 一键启动 |

## 快速启动

```bash
cd zy-panel
docker compose up --build -d
```

- 前端：http://localhost:8080（默认账号 `admin` / `admin123`，首次登录后请修改）
- 后端 API 文档：http://localhost:8818/docs

数据文件保存在 `./data/zy-panel.db`（SQLite，备份拷走这一个文件就行）。

生产部署前务必在 `.env` 中设置固定的 `SECRET_KEY` 与 `FERNET_KEY`：

```bash
openssl rand -hex 32  # SECRET_KEY
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # FERNET_KEY
```

注意：更换 `SECRET_KEY` 会使所有登录 Token 失效；更换 `FERNET_KEY` 会使已存的租户密钥无法解密，需重新录入。

## 功能一览

- **多云租户**：OCI（API 密钥）/ 阿里云（AccessKey，国内 + 国际）统一接入，租户级隔离
- **实例管理**：跨 compartment 查询、电源操作、改 Shape、终止、详情 9 Tab（配置/网络/存储/监视/控制台历史…）
- **抢机 / 抢占式**：OCI 抢机任务（重试/限流/断点续跑/多 AD 轮询/从引导卷启动）、阿里云抢占式实例任务
- **网络**：换公网 IP、一键放行所有端口、附加 IPv6、一键 500M 下行加速、EIP、安全组、Cloudflare DNS 联动
- **存储**：引导卷/数据卷/云盘管理、快照、对象存储（含预签名 URL）、卷扩容
- **可观测**：分钟级流量、峰值带宽、IP 归属地世界地图、免费额度统计、费用分析（OCI 用量 / 阿里云 BSS）
- **运维**：Web SSH 终端、Serial Console（含单用户模式重置系统密码）、IAM 用户管理、Autonomous Database
- **自动化**：定时巡检、每日健康报告、Telegram 通知 + TG 机器人运维命令、审计日志、加密备份恢复
- **更新**：系统设置 → 从 GitHub 仓库拉取更新并自动重启（支持公开/私有仓库）

## 本地开发

后端：

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
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
zy-panel/
├── backend/          # FastAPI 后端（/api/v1）
│   └── app/
│       ├── providers/  # 多云厂商注册表（oci / aliyun）
│       ├── routers/    # HTTP 路由
│       ├── services/   # 业务逻辑
│       ├── workers/    # 后台任务（抢机/换 IP/抢占式）
│       └── ws/         # WebSocket 推送
├── frontend/         # React + Ant Design
├── docs/             # 架构文档
└── docker-compose.yml
```

## 接口约定

- 统一前缀 `/api/v1`，统一响应信封 `{"code":0,"msg":"ok","data":...}`（code 0 为成功）
- 认证：`POST /api/v1/auth/login` 返回 `{token, user}`，其余接口带 `Authorization: Bearer <token>`
- 实时通道：`/ws/logs`、`/ws/tasks`、`/ws/terminal`、`/ws/console`

## 安全提醒

- 生产部署前务必修改默认账号，并配置固定的 `SECRET_KEY` / `FERNET_KEY`
- 建议内网使用，或经反向代理配置 HTTPS 后再暴露到公网
