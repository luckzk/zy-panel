# 多云架构设计（oci-panel）

> 目标：OCI（现有）+ 阿里云（在建）+ AWS / GCP / Azure（未来）在一个面板内融合管理。
> 调研结论（2026-10-13）：CloudExplorer、行云管家、Morpheus 等主流产品一律采用"融合列表 + 云厂商列/筛选 + 统一详情模板按云条件渲染"，顶层切换只出现在二级钻取页。本设计遵循该模式。

## 1. 设计原则

1. **OCI 零回归**：现有 141 个路由继续工作，OCI 作为第一个 Provider 适配器接入，不重写。
2. **加厂商 = 加模块 + 注册一行**：AWS / GCP / Azure 后续接入不改核心代码。
3. **归一化只做最小公共面**：实例列表/详情/电源、安全组、卷等基础资源归一化；厂商特有功能（OCI 抢机、一键 500M、串行控制台、阿里云抢占式）走厂商命名空间，不硬塞进抽象层。
4. **凭证统一加密存储**：Tenant 一张表，一个 Fernet 加密 JSON 字段装各厂商凭证，加厂商不加表字段。
5. **前端 schema 驱动**：厂商元数据（名称/颜色/凭证表单/详情 Tab）走注册表，加厂商不改表单和列表代码。

## 2. 后端分层

```
backend/app/providers/
├── __init__.py      # PROVIDER_REGISTRY: {"oci": OciProvider, "aliyun": AliyunProvider, ...}
│                    # get_provider(tenant) -> CloudProvider
├── base.py          # CloudProvider ABC、归一化 DTO、Capability、ProviderError
├── oci/             # OciProvider：适配现有 service（instance_service 等），不重写
│   ├── __init__.py
│   ├── instances.py
│   ├── volumes.py
│   └── network.py
├── aliyun/          # AliyunProvider：新写
│   ├── __init__.py
│   ├── client.py    # AcsClient 工厂（凭证解密 + region endpoint）
│   └── instances.py
├── aws/             # 未来：boto3
├── gcp/             # 未来：google-cloud-*
└── azure/           # 未来：azure-identity + mgmt SDK
```

### 2.1 base.py 核心定义

```python
class ProviderStatus(str, Enum):
    PENDING, RUNNING, STOPPING, STOPPED, STARTING, TERMINATED, UNKNOWN

class Capability(str, Enum):
    INSTANCES, VOLUMES, SECURITY_GROUPS, IMAGES,
    MONITORING, SNAPSHOTS, EIP, SPOT, SERIAL_CONSOLE

@dataclass
class CloudInstance:          # 归一化实例 DTO
    id: str                   # 厂商原生 ID（OCID / InstanceId / i-xxx）
    name: str
    provider: str             # "oci" | "aliyun" | "aws" ...
    region: str
    zone: str                 # AD / 可用区 / AZ，统一叫 zone
    status: ProviderStatus    # 各厂商自己映射
    spec: str                 # Shape / 实例规格 / InstanceType
    cpu: float | None
    memory_gb: float | None
    public_ip: str | None
    private_ip: str | None
    created_at: str | None
    tags: dict
    raw: dict                 # 厂商原生对象（详情 Tab 按需取用，不归一化）

# 同理：CloudVolume、CloudSecurityGroup、CloudImage、CloudRegion

class CloudProvider(ABC):
    provider_id: str                          # "oci"
    display_name: str                         # "Oracle Cloud"
    capabilities: set[Capability]              # 声明支持的能力

    # --- 核心能力（各厂商实现） ---
    def list_instances(self) -> list[CloudInstance]: ...
    def get_instance(self, instance_id: str) -> CloudInstance: ...
    def power_instance(self, instance_id: str, action: PowerAction) -> None: ...
    def list_volumes(self) -> list[CloudVolume]: ...
    def list_security_groups(self) -> list[CloudSecurityGroup]: ...
    def list_regions(self) -> list[CloudRegion]: ...
    def test_connection(self) -> None: ...    # 连通性测试，失败抛 ProviderError

    def supports(self, cap: Capability) -> bool:
        return cap in self.capabilities

class ProviderError(Exception):
    code: int       # 映射到现有业务码体系（如 3104 超时）
    message: str
```

### 2.2 凭证模型

Tenant 表变更：

| 字段 | 类型 | 说明 |
|---|---|---|
| provider | varchar(16) | oci / aliyun / aws / gcp / azure，默认 oci |
| credentials_enc | text | Fernet 加密的 JSON，各厂商 schema 不同 |

各厂商 credentials JSON schema：

```json
// oci
{"tenancy_ocid": "...", "user_ocid": "...", "fingerprint": "...", "private_key": "...", "region": "..."}
// aliyun
{"access_key_id": "...", "access_key_secret": "...", "region_id": "..."}
// aws（未来）
{"access_key_id": "...", "secret_access_key": "...", "region": "..."}
// gcp（未来）
{"project_id": "...", "service_account_json": "{...}"}
// azure（未来）
{"tenant_id": "...", "client_id": "...", "client_secret": "...", "subscription_id": "..."}
```

迁移：现有 OCI 租户的 5 个明文字段打包进 `credentials_enc`，`provider='oci'`，原字段保留一版后删除。迁移脚本幂等。

### 2.3 路由分发模式

```python
# routers/instances.py（改造后）
@router.get("", summary="实例列表（多云）")
def list_instances(tenant_id: int = Query(...), ...):
    tenant = _get_tenant_or_404(db, tenant_id)
    provider = get_provider(tenant)                       # 按 tenant.provider 查注册表
    if not provider.supports(Capability.INSTANCES):
        return err(3501, f"{provider.display_name} 不支持实例管理", status=501)
    try:
        items = provider.list_instances()
    except ProviderError as e:
        return err(e.code, e.message, status=e.http_status)
    return ok([asdict(i) for i in items])
```

**厂商特有功能不走归一化**，保留独立命名空间（现有 OCI 路由即视为 `oci` 命名空间）：

```
/api/v1/instances/...            # 归一化（分发）
/api/v1/oci/boost/...            # OCI 特有（一键 500M）
/api/v1/oci/snatch/...           # OCI 特有（抢机；现有路由保持兼容，内部校验 provider=='oci'）
/api/v1/aliyun/spot/...          # 阿里云特有（抢占式任务，未来）
```

### 2.4 后台任务与共享服务

- 调度器、通知、审计、备份、登录/MFA **保持厂商无关**，只认 `tenant_id`。
- snatch_worker 这类任务 worker 按 tenant 取 provider：`provider.supports(Capability.SPOT)` 才执行；OCI 抢机逻辑与阿里云抢占式逻辑各写在自家 provider 里，worker 只做调度（重试/间隔/停止条件复用）。

### 2.5 状态映射表（各 provider 自带）

```python
# aliyun/instances.py
STATUS_MAP = {
    "Pending": ProviderStatus.PENDING,
    "Running": ProviderStatus.RUNNING,
    "Starting": ProviderStatus.STARTING,
    "Stopping": ProviderStatus.STOPPING,
    "Stopped": ProviderStatus.STOPPED,
}
# oci/instances.py
STATUS_MAP = {
    "RUNNING": ProviderStatus.RUNNING,
    "STOPPED": ProviderStatus.STOPPED,
    "STOPPING": ProviderStatus.STOPPING,
    ...
}
```

## 3. 前端设计

```
frontend/src/providers/
├── registry.ts     # PROVIDERS 注册表
└── types.ts
```

```ts
// registry.ts
export const PROVIDERS: Record<string, ProviderMeta> = {
  oci: {
    id: 'oci', name: 'Oracle Cloud', short: 'OCI', color: '#C74634',
    credentialFields: [
      { key: 'tenancy_ocid', label: 'Tenancy OCID', required: true },
      { key: 'user_ocid', label: 'User OCID', required: true },
      { key: 'fingerprint', label: '指纹', required: true },
      { key: 'private_key', label: '私钥 PEM', type: 'textarea', required: true },
      { key: 'region', label: 'Region', type: 'region-select', required: true },
    ],
    detailTabs: ['detail', 'network', 'storage', 'security', 'management', 'osmgmt', 'monitor', 'work', 'tags'],
  },
  aliyun: {
    id: 'aliyun', name: '阿里云', short: 'ALI', color: '#FF6A00',
    credentialFields: [
      { key: 'access_key_id', label: 'AccessKey ID', required: true },
      { key: 'access_key_secret', label: 'AccessKey Secret', type: 'password', required: true },
      { key: 'region_id', label: 'Region', type: 'region-select', required: true },
    ],
    detailTabs: ['detail', 'network', 'disk', 'security', 'monitor'],
  },
};
```

- **租户表单**：按 `credentialFields` schema 动态渲染，加厂商只加配置。
- **实例列表**：归一化列（名称/状态/规格/公私网 IP/区域/创建时间）+ `provider` 列（徽标+筛选）。
- **详情页**：Tab 框架复用，按 `detailTabs` 渲染；每个 Tab 组件内部按 provider 取数（`api/instance_tabs.ts` 按 provider 拆文件）。
- **显示层**："租户"改称"云账号"（仅文案，DB 表名不动）。

## 4. 迁移路线（每批独立发包）

| 批 | 内容 | 验收 |
|---|---|---|
| A | base.py + 注册表 + Tenant 凭证迁移脚本 + OciProvider 适配器（包装现有 service，行为不变） | OCI 现有功能全回归 |
| B | 路由逐个切分发：instances / volumes / network / security 先行，其余保持 | 列表页多出 provider 列，OCI 数据不变 |
| C | 前端 provider 注册表 + 租户表单 schema 驱动 + 详情页 Tab 注册表 | 能录入"假"阿里云租户（连通性测试失败但表单可用） |
| D | AliyunProvider 实现 INSTANCES / SECURITY_GROUPS / REGIONS | 真实 AK 跑通 ECS 列表/详情/开关机 |
| E | 阿里云磁盘/快照/EIP/监控；后续 AWS/GCP/Azure 照 D 模式接入 | — |

## 5. 测试策略

- **Conformance 测试**：同一套断言跑所有 provider（list/get/power 返回归一化 DTO、状态枚举合法、分页/空值处理），需真实账号，标记为集成测试。
- **OCI 回归**：批 A/B 完成后，用现有迪拜租户跑一遍只读接口全量（沿用 2026-10-12 的只读测试清单）。

## 6. 刻意不做的事

- 不做跨云编排（一次操作同时动多朵云）。
- 不做统一计费口径（各云账单口径/币种不同，Dashboard 只聚合资源数量，费用分云展示）。
- 不把厂商特有功能硬归一化（归一化层只收敛最小公共面）。
- 国际版/国内版阿里云不做账号类型区分，region 实时拉取天然区分；BSS 费用接口 endpoint 差异在 aliyun provider 内部处理。
