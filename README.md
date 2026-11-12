# zy-panel · 多云服务器管理面板

自托管的多云服务器管理面板：一个界面管理 Oracle Cloud (OCI) 与阿里云（国内版 / 国际版）的实例、网络、存储与费用。架构按多厂商注册表设计，后续可扩展 AWS / GCP / Azure。

当前版本：后端 `0.4.14` · 前端 `0.4.22`（前后端独立版本号，见系统设置页）。

## 技术栈

| 部分 | 技术 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · SQLAlchemy 2.0 · SQLite · APScheduler · OCI Python SDK · Aliyun Python SDK |
| 前端 | React 19 · Ant Design 5 · Vite · TypeScript · ECharts · Framer Motion |
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

- **多云租户**：OCI（API 密钥）/ 阿里云（AccessKey，国内 + 国际）统一接入，租户级隔离；租户详情页含资源概览、配额快照、免费额度、费用、最近操作记录，右上角可切换租户
- **账号类型检测**：OCI 免费/付费号启发式检测（Limits 配额判定 + 试用期费用识别），阿里云不分免费/付费
- **区域订阅**：OCI 租户订阅新区域（主区域外需先申请提额，默认上限 1 个）
- **实例管理**：跨 compartment 查询、电源操作、改 Shape、终止、详情 9 Tab（配置/网络/存储/监视/控制台历史…）；实例页支持阿里云地域切换
- **抢机 / 抢占式**：OCI 抢机任务（重试/限流/断点续跑/多 AD 轮询/从引导卷启动）、阿里云抢占式实例任务、新建按量付费实例
- **网络**：换公网 IP、一键放行所有端口、附加 IPv6、一键 500M 下行加速、EIP、安全组、Cloudflare DNS 联动
- **存储**：引导卷/数据卷/云盘管理、快照、对象存储（含预签名 URL）、卷扩容
- **阿里云专区**：RAM 用户管理、安全组、VPC / 交换机、OSS 对象存储、RDS 数据库、全局流量监控、费用（余额 + 当月账单）
- **可观测**：分钟级流量、峰值带宽、IP 归属地世界地图、免费额度统计、费用分析（OCI 用量 / 阿里云 BSS）
- **运维**：Web SSH 终端、Serial Console（含单用户模式重置系统密码）、IAM 用户管理、Autonomous Database
- **自动化**：定时巡检、每日健康报告、Telegram 通知 + TG 机器人运维（/start 按钮菜单：配置/任务/测活/流量/监控/日志/AI 聊天/SSH/版本/MFA/VNC/备份/IP 黑名单/防御模式/创建实例/引导卷）、审计日志、加密备份恢复
- **更新**：系统设置 → 从 GitHub 仓库拉取更新并自动重启（支持公开/私有仓库）；前端热更新（CI 构建 dist 后一键应用，无需重启后端）
- **动效**：页面切换上浮、卡片依次出现、骨架屏、按钮与卡片悬停微交互（系统开启减弱动效时自动禁用）

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
npm run build # tsc + vite 构建
```

版本号纪律：每次修改都换版本号，后端 `backend/app/VERSION`、前端 `frontend/src/version.ts`，各改各升。

## 目录结构

```
zy-panel/
├── backend/          # FastAPI 后端（/api/v1）
│   └── app/
│       ├── core/       # 配置 / 鉴权 / 响应信封 / 审计
│       ├── db/         # SQLAlchemy 模型与会话
│       ├── providers/  # 多云厂商注册表（oci / aliyun）
│       ├── routers/    # HTTP 路由（25 个模块，241 个接口）
│       ├── services/   # 业务逻辑
│       ├── workers/    # 后台任务（抢机/换 IP/抢占式/定时任务）
│       └── ws/         # WebSocket 推送管理
├── frontend/         # React + Ant Design
│   └── src/
│       ├── api/        # 按模块分的接口封装
│       ├── components/ # 通用组件（含动效 motion.tsx）
│       ├── layouts/    # 主布局（侧边栏/顶栏/内容区）
│       ├── pages/      # 各功能页
│       ├── providers/  # 云厂商注册表（前端）
│       ├── router/     # 路由表
│       ├── stores/     # 状态管理
│       └── theme/      # 三主题（亮色/暗色/未来主义）
├── docs/             # 架构文档与接口文档
└── docker-compose.yml
```

## 接口约定

- 统一前缀 `/api/v1`，统一响应信封 `{"code":0,"msg":"ok","data":...}`（code 0 为成功）
- 认证：`POST /api/v1/auth/login` 返回 `{token, user}`，其余接口带 `Authorization: Bearer <token>`；登录防爆破（同 IP 15 分钟失败 5 次锁定 15 分钟）
- 完整接口清单：见 [docs/api.md](docs/api.md)（按模块分组，241 个接口，2026-11-12 统计）
- 实时通道：`/ws/logs`（审计日志流，需 token）、`/ws/terminal`（Web SSH）、`/ws/console`（串行控制台）

## 安全提醒

- 生产部署前务必修改默认账号，并配置固定的 `SECRET_KEY` / `FERNET_KEY`
- 建议内网使用，或经反向代理配置 HTTPS 后再暴露到公网
