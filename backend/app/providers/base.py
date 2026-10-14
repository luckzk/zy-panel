"""多云 Provider 抽象层。

设计原则（见 docs/multi-cloud-architecture.md）：
- 归一化只做最小公共面：实例/卷/安全组/镜像/地域的基础查询与操作。
- 厂商特有功能（OCI 抢机/500M/串行控制台、阿里云抢占式等）不进抽象层，
  各走各的命名空间路由。
- 加厂商 = 在 providers/ 下新建模块 + 注册一行，不改核心。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum


class ProviderStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    TERMINATED = "TERMINATED"
    UNKNOWN = "UNKNOWN"


class PowerAction(str, Enum):
    START = "start"
    STOP = "stop"
    REBOOT = "reboot"


class Capability(str, Enum):
    INSTANCES = "instances"
    VOLUMES = "volumes"
    SECURITY_GROUPS = "security_groups"
    IMAGES = "images"
    MONITORING = "monitoring"
    SNAPSHOTS = "snapshots"
    EIP = "eip"
    SPOT = "spot"  # 抢占式/抢机类能力
    SERIAL_CONSOLE = "serial_console"
    RAM = "ram"  # 子用户（RAM/IAM）管理


class ProviderError(Exception):
    """Provider 层统一异常，code 对接现有业务码体系。"""

    def __init__(self, code: int, message: str, http_status: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


# ------------------------------------------------------------------ 归一化 DTO
@dataclass
class CloudInstance:
    """归一化实例。各厂商把原生字段映射过来；raw 保留原生对象供详情 Tab 按需取用。"""

    id: str                # 厂商原生 ID：OCID / InstanceId / i-xxx
    name: str
    provider: str          # "oci" | "aliyun" | ...
    region: str
    zone: str              # AD / 可用区 / AZ，统一叫 zone
    status: ProviderStatus
    spec: str              # Shape / 实例规格 / InstanceType
    cpu: float | None = None
    memory_gb: float | None = None
    public_ip: str | None = None
    private_ip: str | None = None
    created_at: str | None = None
    tags: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class CloudVolume:
    id: str
    name: str
    provider: str
    region: str
    zone: str
    size_gb: int | None
    status: str
    volume_type: str | None = None
    attached_instance_id: str | None = None
    attached_instance_name: str | None = None
    created_at: str | None = None
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CloudSecurityGroup:
    id: str
    name: str
    provider: str
    region: str
    description: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CloudRegion:
    id: str
    name: str               # 中文名 / LocalName
    provider: str

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ 抽象基类
class CloudProvider(ABC):
    """所有云厂商 Provider 的基类。"""

    provider_id: str = ""
    display_name: str = ""
    capabilities: set[Capability] = set()

    def __init__(self, tenant):
        self.tenant = tenant
        self.credentials: dict = {}

    def supports(self, cap: Capability) -> bool:
        return cap in self.capabilities

    def require(self, cap: Capability) -> None:
        if not self.supports(cap):
            raise ProviderError(3501, f"{self.display_name} 不支持该功能", 501)

    # -- 核心能力（子类按需实现，不支持的不实现，调用前用 supports 检查） --
    def list_regions(self) -> list[CloudRegion]:
        raise NotImplementedError

    def test_connection(self) -> dict:
        """连通性测试，返回 {"ok": True, "detail": ...}，失败抛 ProviderError。"""
        raise NotImplementedError

    def list_instances(self, region_id: str | None = None) -> list[CloudInstance]:
        raise NotImplementedError

    def get_instance(self, instance_id: str) -> CloudInstance:
        raise NotImplementedError

    def power_instance(self, instance_id: str, action: PowerAction) -> None:
        raise NotImplementedError

    def list_volumes(self) -> list[CloudVolume]:
        raise NotImplementedError

    def list_security_groups(self) -> list[CloudSecurityGroup]:
        raise NotImplementedError
