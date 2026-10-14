# OCI 云服务器管理面板 · 前端

基于 **React 19 + Ant Design 5 + Vite + TypeScript** 开发的 OCI 管理面板前端，
对应后端为 Python FastAPI（`../backend`），前后端通过 `/api/v1` REST 接口解耦。

## 技术栈

| 技术 | 版本 | 说明 |
| --- | --- | --- |
| React | 19 | UI 框架 |
| Ant Design | 5 | 组件库（含中文语言包、暗黑模式） |
| Vite | 8 | 构建工具 |
| TypeScript | 6（严格模式） | 类型检查 |
| react-router-dom | 6 | 路由 + 鉴权守卫 |
| zustand | 5 | 轻量状态管理（登录态 / 主题） |
| axios | 1 | HTTP 客户端（统一响应解包） |
| echarts | 6 | 流量图表 |

## 本地启动

```bash
# 1. 安装依赖（Node 20+）
npm install

# 2. 启动开发服务器（http://localhost:5173）
npm run dev
```

开发环境下 `/api/v1` 与 `/ws` 会由 Vite 自动代理到 `http://localhost:8818`（见 `vite.config.ts`），
无需额外配置跨域。

### 环境变量

复制 `.env.example` 为 `.env` 后按需修改：

```bash
cp .env.example .env
```

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `VITE_API_BASE` | `http://localhost:8818` | 后端 API 基地址 |

> 后端未启动时，登录会自动进入**演示模式**（mock 数据），方便预览界面；
> 后端就绪后即走真实接口。

## 构建

```bash
npm run build   # tsc 类型检查 + vite 打包，产物在 dist/
npm run preview # 本地预览构建产物
```

## Docker 部署

```bash
# 构建镜像
docker build -t oci-panel-frontend .

# 运行（需与后端容器同网络，后端服务名须为 oci-panel-backend）
docker run -d -p 80:80 --name oci-panel-frontend oci-panel-frontend
```

生产环境由 nginx 托管静态文件，并将 `/api/v1/` 与 `/ws/` 反代到
`http://oci-panel-backend:8818`（见 `nginx.conf`）。推荐与后端一起用
`docker-compose` 编排（见仓库根目录规划）。

## 目录结构

```
frontend/
├── src/
│   ├── api/client.ts        # axios 实例：baseURL / Bearer token / {code,msg,data} 解包 / 401 跳登录
│   ├── router/index.tsx     # 路由表 + 鉴权守卫
│   ├── layouts/MainLayout.tsx # 侧边栏菜单 + 面包屑 + 暗黑模式切换 + 用户信息
│   ├── stores/
│   │   ├── auth.ts          # zustand：token / 用户信息 / login / logout
│   │   └── theme.ts         # zustand：暗黑模式
│   ├── components/Chart.tsx # ECharts 通用封装
│   ├── mock/data.ts         # mock 数据与业务类型（后端就绪后替换为真实接口）
│   └── pages/               # 11 个业务页面
│       ├── Dashboard.tsx    # 总览：统计卡片 + 流量折线图 + 状态饼图
│       ├── Login.tsx        # 登录：POST /api/v1/auth/login
│       ├── Tenants.tsx      # 租户配置：表格 + 新建/编辑 Modal
│       ├── Instances.tsx    # 实例管理：表格 + 批量启停 + 状态标签
│       ├── SnatchTasks.tsx  # 抢机任务：状态机标签 + 暂停/继续
│       ├── Network.tsx      # 网络/换 IP：换 IP 表单 + 更换记录
│       ├── Security.tsx     # 安全组：规则表格 + 一键放行
│       ├── Volumes.tsx      # 引导卷：表格 + 扩容
│       ├── Monitoring.tsx   # 流量监控：筛选 + 出入流量图表
│       ├── Dns.tsx          # DNS 解析：记录表格 + Modal
│       └── System.tsx       # 系统设置：通知配置 / 备份恢复 / 实时日志
├── nginx.conf               # 生产 nginx 配置（含 /api/v1 与 /ws 反代）
├── Dockerfile               # node:20 构建 + nginx 运行的两阶段构建
└── .env.example             # 环境变量示例
```

## 接口约定（与后端）

- 基地址：`/api/v1`
- 统一响应体：`{ "code": 0, "msg": "ok", "data": {...} }`，`code !== 0` 视为业务失败
- 认证：除登录接口外，请求头携带 `Authorization: Bearer <token>`；401 自动清 token 并跳登录页
- 实时通道：`ws://<host>/ws/logs`（日志）、`ws://<host>/ws/tasks`（任务进度），前端已预留接入点
