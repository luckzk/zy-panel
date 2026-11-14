# 接口文档（API 参考）

> 统计时间：2026-11-13；后端 `0.4.18`；共 **243** 个 HTTP 接口 + 3 个 WebSocket 通道。
> 本文档按后端路由代码生成，实时交互式文档见运行中的面板 `http://localhost:8818/docs`（Swagger，以代码为准）。

## 通用约定

- 统一前缀 `/api/v1`，下表路径均为完整路径。
- 统一响应信封：`{"code": 0, "msg": "ok", "data": ...}`，`code` 为 0 表示成功，非 0 为业务错误码（`msg` 为错误说明）。
- 认证：除 `POST /api/v1/auth/login` 外，全部接口需在请求头带 `Authorization: Bearer <token>`。登录防爆破：同 IP 15 分钟内失败 5 次锁定 15 分钟（业务码 `1003`）。
- 租户类接口一般以 `tenant_id` 查询参数指定租户；写操作记审计日志。
- 部分接口为只读聚合（如租户总览、免费额度），各小节独立容错，局部失败不影响整体返回。

## 认证（/api/v1/auth）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/v1/auth/login | 登录，返回 JWT |
| POST | /api/v1/auth/mfa/setup | MFA 绑定：生成密钥与二维码（需登录） |
| POST | /api/v1/auth/mfa/verify | MFA 绑定确认：验证码正确则启用 |
| POST | /api/v1/auth/mfa/disable | 关闭 MFA：验证码正确则解绑 |
| GET | /api/v1/auth/mfa/status | 当前用户 MFA 状态 |
| GET | /api/v1/auth/me | 当前登录用户信息 |
| POST | /api/v1/auth/change-password | 修改当前用户密码 |

## 租户（/api/v1/tenants）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/tenants/providers | 已注册云厂商列表 |
| GET | /api/v1/tenants/{tenant_id}/regions | 地域列表（按云厂商分发，实时） |
| GET | /api/v1/tenants | 租户列表 |
| POST | /api/v1/tenants | 新增租户（云账号） |
| POST | /api/v1/tenants/batch | 批量新增租户（逐个校验，返回每条结果） |
| GET | /api/v1/tenants/{tenant_id} | 租户详情 |
| PUT | /api/v1/tenants/{tenant_id} | 更新租户 |
| DELETE | /api/v1/tenants/{tenant_id} | 删除租户 |
| POST | /api/v1/tenants/{tenant_id}/detect-account-type | 启发式检测账号类型（免费/付费，仅供参考） |
| GET | /api/v1/tenants/{tenant_id}/overview | 租户总览（仅 OCI，只读聚合） |
| GET | /api/v1/tenants/{tenant_id}/recent-operations | 最近操作记录（按租户名匹配审计日志，仅供参考） |
| GET | /api/v1/tenants/{tenant_id}/region-subscriptions | 区域订阅：已订阅 + 可订阅（仅 OCI） |
| POST | /api/v1/tenants/{tenant_id}/region-subscriptions | 订阅新区域（仅 OCI，写操作记审计） |
| POST | /api/v1/tenants/{tenant_id}/test | 连通性测试（按云厂商分发） |

## 实例（/api/v1/instances）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/instances | 实例列表（多云分发，支持 `region_id`） |
| GET | /api/v1/instances/{instance_id} | 实例详情（多云分发） |
| POST | /api/v1/instances/{instance_id}/power | 电源操作：start/stop/reboot（多云分发） |
| PUT | /api/v1/instances/{instance_id}/name | 改实例名 |
| PUT | /api/v1/instances/{instance_id}/shape | 改实例配置 shape（实例需关机） |
| POST | /api/v1/instances/{instance_id}/terminate | 终止实例（二次确认由前端 Popconfirm 完成） |
| GET | /api/v1/instances/{instance_id}/tabs/detail-extra | 详细信息 Tab：启动选项/映像/容量类型 |
| GET | /api/v1/instances/{instance_id}/tabs/network | 网络 Tab：路由表/FQDN/附加 VNIC |
| GET | /api/v1/instances/{instance_id}/tabs/storage | 存储 Tab：引导卷/数据卷扩展信息 |
| GET | /api/v1/instances/{instance_id}/tabs/security | 安全 Tab：安全列表规则明细 |
| GET | /api/v1/instances/{instance_id}/tabs/management | 管理 Tab：维护事件 |
| GET | /api/v1/instances/{instance_id}/tabs/agent-plugins | 管理 Tab：Cloud Agent 插件 |
| GET | /api/v1/instances/{instance_id}/tabs/work-requests | 工作请求 Tab |
| GET | /api/v1/instances/{instance_id}/tabs/metrics | 监视 Tab：CPU/内存/磁盘/网络指标 |
| POST | /api/v1/instances/{instance_id}/console-history/capture | 截取控制台历史 |
| GET | /api/v1/instances/{instance_id}/console-history/{history_id}/content | 获取控制台历史内容 |
| POST | /api/v1/instances/{instance_id}/custom-image | 创建定制映像（实例需关机） |
| POST | /api/v1/instances/{instance_id}/change-compartment | 移动实例到其他 compartment |
| POST | /api/v1/instances/{instance_id}/diagnostic | 诊断操作：发送诊断中断 / 诊断重启 |
| POST | /api/v1/instances/{instance_id}/run-command | 在实例上运行命令（需 Cloud Agent） |
| GET | /api/v1/instances/{instance_id}/run-command/{command_id} | 查询实例命令执行结果 |

## 元数据（/api/v1/meta）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/meta/regions | 全部商业 Region（OCI SDK 权威列表） |
| GET | /api/v1/meta/compartments | Compartment 列表（实时） |
| GET | /api/v1/meta/availability-domains | 可用域 AD 列表（实时） |
| GET | /api/v1/meta/shapes | Shape 列表（实时） |
| GET | /api/v1/meta/images | 镜像列表（实时） |
| GET | /api/v1/meta/subnets | 子网列表（实时） |
| GET | /api/v1/meta/boot-volumes | 引导卷列表（实时，供从现有引导卷抢机） |

## 监控（/api/v1/monitoring）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/monitoring/traffic | 实例流量时序（真实 OCI 指标） |
| GET | /api/v1/monitoring/bandwidth | 实例峰值带宽（近 N 小时出向/入向 Mbps 实测峰值） |
| GET | /api/v1/monitoring/quotas | 租户配额查询（真实 Limits API） |

## 网络（/api/v1/network）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/v1/network/change-ip | 发起换 IP 任务（后台 worker 真实执行） |
| GET | /api/v1/network/ip-tasks | 换 IP 任务列表 |
| GET | /api/v1/network/change-ip-tasks | 换 IP 任务列表（与 /ip-tasks 同义） |
| POST | /api/v1/network/ip-tasks/{task_id}/cancel | 取消换 IP 任务 |
| GET | /api/v1/network/security-rules | 安全列表规则（真实 OCI 查询） |
| POST | /api/v1/network/security-rules | 新增安全规则（真实 OCI 调用） |
| DELETE | /api/v1/network/security-rules/{rule_id} | 删除安全规则（真实 OCI 调用） |
| POST | /api/v1/network/ipv6 | 为实例主 VNIC 附加公网 IPv6（真实 OCI 调用） |
| GET | /api/v1/network/ipv6 | 查询实例主 VNIC 的 IPv6 地址 |

## 安全组（/api/v1/security）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/security/vcns | VCN 列表（真实 OCI 查询） |
| GET | /api/v1/security/rules | 安全列表规则（真实 OCI 查询） |
| POST | /api/v1/security/rules | 新增安全规则（真实 OCI 调用） |
| DELETE | /api/v1/security/rules/{rule_id} | 删除安全规则（真实 OCI 调用） |
| POST | /api/v1/security/open-all-ports | 一键放行所有端口（真实 OCI 调用，危险操作） |

## 卷（/api/v1/volumes）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/volumes | 引导卷列表（真实 OCI 查询） |
| GET | /api/v1/volumes/block | 数据卷列表（真实 OCI 查询） |
| GET | /api/v1/volumes/{volume_id} | 引导卷详情（真实 OCI 查询） |
| POST | /api/v1/volumes/{volume_id}/resize | 引导卷扩容（真实 OCI 调用） |
| POST | /api/v1/volumes/block/{volume_id}/resize | 数据卷扩容（真实 OCI 调用） |
| POST | /api/v1/volumes/{volume_id}/rescue | 救援：挂载引导卷到救援实例 |
| POST | /api/v1/volumes/{volume_id}/unrescue | 解除救援：卸载引导卷的全部挂载 |

## 对象存储（/api/v1/object-storage）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/object-storage/namespace | 获取对象存储 namespace |
| GET | /api/v1/object-storage/buckets | Bucket 列表（真实 OCI 查询） |
| POST | /api/v1/object-storage/buckets | 创建 Bucket |
| DELETE | /api/v1/object-storage/buckets/{name} | 删除 Bucket（需为空） |
| GET | /api/v1/object-storage/objects | 对象列表（真实 OCI 查询） |
| POST | /api/v1/object-storage/objects/upload | 上传对象（单文件上限 50MB） |
| GET | /api/v1/object-storage/objects/download | 下载对象 |
| DELETE | /api/v1/object-storage/objects | 删除对象 |
| POST | /api/v1/object-storage/preauth | 创建预签名 URL（限时分享下载链接） |
| GET | /api/v1/object-storage/preauth | 预签名 URL 列表 |
| DELETE | /api/v1/object-storage/preauth/{par_id} | 吊销预签名 URL |
| GET | /api/v1/object-storage/buckets/{name}/detail | Bucket 详情（含版本控制状态） |
| POST | /api/v1/object-storage/buckets/{name}/versioning | 开关 Bucket 版本控制 |
| GET | /api/v1/object-storage/buckets/{name}/lifecycle | 查询 Bucket 生命周期规则 |
| PUT | /api/v1/object-storage/buckets/{name}/lifecycle | 设置 Bucket 生命周期规则（覆盖） |

## 数据库（/api/v1/databases）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/databases | Autonomous Database 列表 |
| GET | /api/v1/databases/{db_id} | Autonomous Database 详情 |
| POST | /api/v1/databases | 创建 Autonomous Database |
| DELETE | /api/v1/databases/{db_id} | 删除 Autonomous Database |
| POST | /api/v1/databases/{db_id}/start | 启动数据库 |
| POST | /api/v1/databases/{db_id}/stop | 停止数据库 |
| POST | /api/v1/databases/{db_id}/restart | 重启数据库 |
| POST | /api/v1/databases/{db_id}/change-password | 修改数据库管理员密码 |
| POST | /api/v1/databases/{db_id}/wallet | 下载数据库钱包 |

## 费用与免费额度

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/billing/summary | 费用汇总（真实 OCI 用量，支持 `days`） |
| GET | /api/v1/billing/details | 费用明细（真实 OCI 用量） |
| GET | /api/v1/free-tier/summary | 免费额度使用情况汇总（只读，后端缓存 10 分钟） |
| GET | /api/v1/dashboard/overview | 总览聚合（真实数据） |

## IP 归属地（/api/v1/ipinfo）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/ipinfo/map | 全球实例分布（公网 IP 归属地打点） |
| POST | /api/v1/ipinfo/refresh | 强制刷新 IP 归属地缓存 |

## IAM（/api/v1/iam）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/iam/users | 用户列表 |
| POST | /api/v1/iam/users | 创建用户 |
| PUT | /api/v1/iam/users/{user_id} | 更新用户（描述/邮箱） |
| DELETE | /api/v1/iam/users/{user_id} | 删除用户（不可逆） |
| GET | /api/v1/iam/users/{user_id}/api-keys | 某用户的 API 密钥列表 |
| POST | /api/v1/iam/users/{user_id}/api-keys | 上传 API 公钥 |
| DELETE | /api/v1/iam/users/{user_id}/api-keys/{fingerprint} | 删除 API 密钥 |
| GET | /api/v1/iam/groups | 用户组列表 |
| POST | /api/v1/iam/groups | 创建用户组 |
| DELETE | /api/v1/iam/groups/{group_id} | 删除用户组 |
| GET | /api/v1/iam/groups/{group_id}/members | 组成员列表 |
| POST | /api/v1/iam/groups/{group_id}/members | 添加组成员 |
| DELETE | /api/v1/iam/groups/{group_id}/members/{membership_id} | 移除组成员 |
| GET | /api/v1/iam/users/{user_id}/auth-tokens | Auth Token 列表 |
| POST | /api/v1/iam/users/{user_id}/auth-tokens | 创建 Auth Token（明文只返回一次） |
| DELETE | /api/v1/iam/users/{user_id}/auth-tokens/{token_id} | 删除 Auth Token |
| GET | /api/v1/iam/users/{user_id}/secret-keys | Customer Secret Key 列表 |
| POST | /api/v1/iam/users/{user_id}/secret-keys | 创建 Customer Secret Key（明文只返回一次） |
| DELETE | /api/v1/iam/users/{user_id}/secret-keys/{key_id} | 删除 Customer Secret Key |
| GET | /api/v1/iam/users/{user_id}/smtp-credentials | SMTP 凭证列表 |
| POST | /api/v1/iam/users/{user_id}/smtp-credentials | 创建 SMTP 凭证（密码只返回一次） |
| DELETE | /api/v1/iam/users/{user_id}/smtp-credentials/{cred_id} | 删除 SMTP 凭证 |
| GET | /api/v1/iam/users/{user_id}/mfa-devices | MFA TOTP 设备列表 |
| DELETE | /api/v1/iam/users/{user_id}/mfa-devices/{device_id} | 删除 MFA TOTP 设备 |

## 抢机任务（/api/v1/snatch-tasks）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/snatch-tasks | 抢机任务列表 |
| POST | /api/v1/snatch-tasks | 创建抢机任务（初始 pending） |
| GET | /api/v1/snatch-tasks/stats | 抢机统计：状态分布 / 总尝试次数 / 成功率 |
| GET | /api/v1/snatch-tasks/{task_id} | 抢机任务详情 |
| PUT | /api/v1/snatch-tasks/{task_id} | 更新抢机任务（仅 pending/paused 可改配置） |
| DELETE | /api/v1/snatch-tasks/{task_id} | 删除抢机任务 |
| POST | /api/v1/snatch-tasks/{task_id}/start | 启动任务（pending/paused -> running） |
| POST | /api/v1/snatch-tasks/{task_id}/pause | 暂停任务（running -> paused） |
| POST | /api/v1/snatch-tasks/{task_id}/resume | 继续任务（paused -> running） |

## 一键 500M（/api/v1/boost）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/v1/boost/enable | 一键开启下行 500M（后台任务） |
| POST | /api/v1/boost/disable | 关闭下行 500M（后台任务） |
| GET | /api/v1/boost/tasks | 500M 任务列表 |
| GET | /api/v1/boost/tasks/{task_id} | 500M 任务状态 |

## 串行控制台（/api/v1/console）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/v1/console/connections | 创建串行控制台连接（真实 OCI 调用，后台等待 ACTIVE） |
| GET | /api/v1/console/connections | 查询串行控制台连接 |
| DELETE | /api/v1/console/connections/{conn_id} | 删除串行控制台连接 |
| POST | /api/v1/console/reset-password | 串口自动重置系统密码（GRUB 单用户，需硬重启实例） |
| GET | /api/v1/console/reset-password/tasks/{task_id} | 查询串口改密码任务状态 |

## DNS（/api/v1/dns）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/dns/records | DNS 记录列表 |
| POST | /api/v1/dns/records | 新增 DNS 记录（本地落库 + 尝试同步 Cloudflare） |
| PUT | /api/v1/dns/records/{record_id} | 更新 DNS 记录（本地 + 尝试同步 Cloudflare） |
| DELETE | /api/v1/dns/records/{record_id} | 删除 DNS 记录（本地 + 尝试删除远端） |
| POST | /api/v1/dns/records/{record_id}/sync | 手动同步单条记录到 Cloudflare |
| POST | /api/v1/dns/records/pull | 从 Cloudflare 拉取 zone 记录并落库（按 name+type 去重） |
| POST | /api/v1/dns/records/{record_id}/sync-after-ip-change | 换 IP 后更新 DNS（本地 + 同步 Cloudflare） |
| GET | /api/v1/dns/settings/cloudflare | Cloudflare Token 配置状态（不回显 token） |
| PUT | /api/v1/dns/settings/cloudflare | 保存 Cloudflare API Token（加密存储） |

## 通知（/api/v1/notifications）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/notifications | 通知渠道列表 |
| POST | /api/v1/notifications | 创建通知渠道 |
| PUT | /api/v1/notifications/{config_id} | 更新通知渠道（支持部分字段） |
| DELETE | /api/v1/notifications/{config_id} | 删除通知渠道 |
| POST | /api/v1/notifications/{config_id}/test | 发送测试消息 |

## 定时任务（/api/v1/scheduled-tasks）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/scheduled-tasks/task-types | 支持的任务类型 |
| GET | /api/v1/scheduled-tasks | 定时任务列表 |
| POST | /api/v1/scheduled-tasks | 创建定时任务 |
| GET | /api/v1/scheduled-tasks/{task_id} | 定时任务详情 |
| PUT | /api/v1/scheduled-tasks/{task_id} | 更新定时任务 |
| DELETE | /api/v1/scheduled-tasks/{task_id} | 删除定时任务 |
| POST | /api/v1/scheduled-tasks/{task_id}/toggle | 启用 / 禁用定时任务 |
| POST | /api/v1/scheduled-tasks/{task_id}/run-now | 立即执行一次 |

## 巡检（/api/v1/inspection）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/v1/inspection/run | 执行一键巡检 |

## 每日报告（/api/v1/system/daily-report）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/system/daily-report | 每日报告配置 |
| POST | /api/v1/system/daily-report | 更新每日报告配置（仅管理员） |
| POST | /api/v1/system/daily-report/send | 立即发送一次每日报告（仅管理员，测试用） |

## 系统（/api/v1/system）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/system/logs | 操作审计日志 |
| GET | /api/v1/system/backup | 加密备份导出（文件下载） |
| POST | /api/v1/system/restore | 备份恢复（上传加密备份文件） |
| GET | /api/v1/system/version | 版本信息 |
| GET | /api/v1/system/tg-bot | TG 运维机器人配置（含 AI 聊天配置，Key 不返回明文） |
| POST | /api/v1/system/tg-bot | 更新 TG 运维机器人配置（仅管理员，ai_api_key 留空表示不改） |
| GET | /api/v1/system/update/check | 检查更新 |
| POST | /api/v1/system/update/feed | 配置更新源（仅管理员） |
| POST | /api/v1/system/update/apply | 上传更新包并应用（仅管理员） |
| GET | /api/v1/system/update/github/config | GitHub 更新配置 |
| POST | /api/v1/system/update/github/config | 保存 GitHub 更新配置（仅管理员） |
| GET | /api/v1/system/update/github/check | 检查 GitHub 仓库更新 |
| POST | /api/v1/system/update/github/apply | 从 GitHub 拉取并应用更新（仅管理员） |
| GET | /api/v1/system/update/frontend/check | 检查前端 dist 更新（CI 构建） |
| POST | /api/v1/system/update/frontend/apply | 热更前端 dist（仅管理员） |
| GET | /api/v1/system/update/all/check | 一次检查前后端更新 |
| POST | /api/v1/system/update/all/apply | 一键更新前后端（仅管理员，先热更前端再更新后端并重启） |

## 阿里云（/api/v1/aliyun）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/aliyun/disks | 云盘列表 |
| POST | /api/v1/aliyun/disks/{disk_id}/resize | 云盘扩容（只允许调大） |
| GET | /api/v1/aliyun/snapshots | 快照列表 |
| POST | /api/v1/aliyun/snapshots | 创建快照 |
| DELETE | /api/v1/aliyun/snapshots/{snapshot_id} | 删除快照 |
| GET | /api/v1/aliyun/eips | 弹性公网 IP 列表 |
| POST | /api/v1/aliyun/eips | 申请 EIP（按量付费，按流量计费） |
| POST | /api/v1/aliyun/eips/bind | EIP 绑定实例 |
| POST | /api/v1/aliyun/eips/unbind | EIP 解绑实例 |
| DELETE | /api/v1/aliyun/eips/{allocation_id} | 释放 EIP |
| GET | /api/v1/aliyun/instances/{instance_id}/metrics | 实例监控指标（CMS） |
| GET | /api/v1/aliyun/images | 自定义镜像列表 |
| GET | /api/v1/aliyun/images/public | 公共镜像列表（创建实例/抢占式任务用） |
| POST | /api/v1/aliyun/images | 创建自定义镜像（从实例或快照） |
| DELETE | /api/v1/aliyun/images/{image_id} | 删除自定义镜像 |
| GET | /api/v1/aliyun/billing/summary | 费用概览（余额 + 当月账单） |
| GET | /api/v1/aliyun/overview | 租户总览（余额 + 当月账单 + 默认地域资源数，只读） |
| GET | /api/v1/aliyun/instance-types | 实例规格列表 |
| GET | /api/v1/aliyun/spot-tasks | 抢占式任务列表 |
| POST | /api/v1/aliyun/spot-tasks | 创建抢占式任务 |
| POST | /api/v1/aliyun/spot-tasks/{task_id}/start | 启动抢占式任务 |
| POST | /api/v1/aliyun/spot-tasks/{task_id}/pause | 暂停抢占式任务 |
| DELETE | /api/v1/aliyun/spot-tasks/{task_id} | 删除抢占式任务 |
| GET | /api/v1/aliyun/ram/users | RAM 用户列表 |
| POST | /api/v1/aliyun/ram/users | 创建 RAM 用户 |
| DELETE | /api/v1/aliyun/ram/users/{user_name} | 删除 RAM 用户（含其 AccessKey） |
| GET | /api/v1/aliyun/ram/users/{user_name}/keys | RAM 用户 AccessKey 列表 |
| POST | /api/v1/aliyun/ram/users/{user_name}/keys | 为 RAM 用户创建 AccessKey（Secret 仅返回一次） |
| DELETE | /api/v1/aliyun/ram/users/{user_name}/keys/{key_id} | 删除 RAM 用户 AccessKey |
| GET | /api/v1/aliyun/security-groups | 安全组列表 |
| GET | /api/v1/aliyun/security-groups/{sg_id}/rules | 安全组规则列表 |
| POST | /api/v1/aliyun/security-groups/{sg_id}/rules | 添加安全组规则 |
| DELETE | /api/v1/aliyun/security-groups/{sg_id}/rules | 删除安全组规则 |
| POST | /api/v1/aliyun/security-groups | 创建安全组 |
| DELETE | /api/v1/aliyun/security-groups/{sg_id} | 删除安全组 |
| GET | /api/v1/aliyun/vpcs | VPC 列表 |
| POST | /api/v1/aliyun/vpcs | 创建 VPC |
| DELETE | /api/v1/aliyun/vpcs/{vpc_id} | 删除 VPC |
| GET | /api/v1/aliyun/vswitches | 交换机列表 |
| POST | /api/v1/aliyun/vswitches | 创建交换机 |
| DELETE | /api/v1/aliyun/vswitches/{vswitch_id} | 删除交换机 |
| GET | /api/v1/aliyun/oss/buckets | OSS Bucket 列表 |
| POST | /api/v1/aliyun/oss/buckets | 新建 OSS Bucket |
| DELETE | /api/v1/aliyun/oss/buckets/{bucket_name} | 删除 OSS Bucket（仅空桶可删） |
| GET | /api/v1/aliyun/oss/buckets/{bucket_name}/objects | OSS Bucket 文件列表 |
| DELETE | /api/v1/aliyun/oss/buckets/{bucket_name}/objects | 删除 OSS 文件 |
| GET | /api/v1/aliyun/oss/buckets/{bucket_name}/download-url | OSS 文件签名下载 URL |
| POST | /api/v1/aliyun/oss/buckets/{bucket_name}/upload | 上传文件到 OSS Bucket |
| GET | /api/v1/aliyun/rds/instances | RDS 实例列表 |
| GET | /api/v1/aliyun/rds/instances/{db_id} | RDS 实例详情 |
| GET | /api/v1/aliyun/rds/instances/{db_id}/databases | RDS 实例数据库列表 |
| GET | /api/v1/aliyun/rds/instances/{db_id}/accounts | RDS 实例账号列表 |
| GET | /api/v1/aliyun/monitoring/overview | 全局流量监控聚合（多实例带宽总览） |
| POST | /api/v1/aliyun/instances | 新建按量付费实例 |

> 注意：`GET /api/v1/aliyun/vswitches` 在代码中有两个同名同路径的处理器（分别按 `zone_id` 和 `vpc_id` 过滤），FastAPI 按注册顺序匹配，实际生效的始终是第一个（`zone_id` 版），`vpc_id` 版目前走不到，建议合并为一个处理器。
>
> 另：Swagger 里还多一个 `GET /` 健康检查（返回 `{"service": "zy-panel", "version": "0.1.0"}`），不属于 `/api/v1`，未列入上表；注意它返回的版本号是写死的 `0.1.0`，与真实后端版本（`0.4.14`）不一致。

## WebSocket

| 通道 | 说明 |
|---|---|
| /ws/logs | 实时审计日志流，需 `?token=<JWT>` 鉴权（鉴权失败关 4401） |
| /ws/terminal | Web SSH 终端（xterm.js + paramiko 桥接） |
| /ws/console | 串行控制台（PTY + SSH 桥接） |

> 旧 README 曾列出 `/ws/tasks`，经核查代码中不存在该通道，已移除。
