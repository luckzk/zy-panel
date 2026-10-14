"""SQLAlchemy 2.0 数据模型（typed 写法）。

表一览：
- users: 登录用户
- tenants: OCI 租户配置（私钥经 Fernet 加密后存 private_key_ciphertext）
- snatch_tasks: 抢机任务（状态机 pending/running/paused/success/failed 落库，支持断点续跑）
- ip_tasks: 换 IP 任务
- dns_records: Cloudflare DNS 记录本地镜像
- notification_configs: 通知渠道配置（Telegram / 邮件等）
- operation_logs: 操作审计日志
- ip_location_cache: IP 归属地缓存（ip-api.com 批量查询结果，TTL 30 天）
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)  # MFA 预留
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    logs: Mapped[list["OperationLog"]] = relationship(back_populates="user")


class Tenant(Base):
    """云账号配置：OCI 租户 / 阿里云 AK（后续可扩展 AWS/GCP/Azure）。

    provider 决定凭证 schema，凭证统一 Fernet 加密存 credentials_enc。
    """

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))  # 备注名，如 "东京-账号1"
    # 云厂商：oci / aliyun（默认 oci，老数据）
    provider: Mapped[str] = mapped_column(String(16), default="oci")
    # Fernet 加密的凭证 JSON（各厂商 schema 不同，见 docs/multi-cloud-architecture.md）
    credentials_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ---- 以下为 OCI 老字段，保留兼容（新租户走 credentials_enc） ----
    tenancy_ocid: Mapped[str] = mapped_column(String(255))
    user_ocid: Mapped[str] = mapped_column(String(255))
    fingerprint: Mapped[str] = mapped_column(String(64))
    region: Mapped[str] = mapped_column(String(64), default="ap-tokyo-1")
    # 私钥 PEM 经 Fernet 加密后的密文，绝不存明文
    private_key_ciphertext: Mapped[str] = mapped_column(Text)
    proxy: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 连通性测试状态（持久化，避免刷新后丢失）
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    test_status: Mapped[str] = mapped_column(String(16), default="")  # success / failed
    # 账号类型（OCI 无 API 可查，手动标记）：free 免费 / paid 付费
    account_type: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    snatch_tasks: Mapped[list["SnatchTask"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    aliyun_spot_tasks: Mapped[list["AliyunSpotTask"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


class SnatchTask(Base):
    """抢机任务：后台常驻轮询直到创建成功，状态落库支持断点续跑。"""

    __tablename__ = "snatch_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    shape: Mapped[str] = mapped_column(String(128), default="VM.Standard.A1.Flex")
    compartment_id: Mapped[str] = mapped_column(String(255), default="")
    image_id: Mapped[str] = mapped_column(String(255), default="")
    boot_volume_id: Mapped[str] = mapped_column(String(255), default="")  # 从现有引导卷抢机（与 image_id 二选一）
    subnet_id: Mapped[str] = mapped_column(String(255), default="")
    availability_domain: Mapped[str] = mapped_column(String(128), default="")
    availability_domains: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 数组，多 AD 轮询抢机
    # Flex 机型配置（A1.Flex 等必须指定）
    ocpus: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_in_gbs: Mapped[float | None] = mapped_column(Float, nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    assign_public_ip: Mapped[bool] = mapped_column(Boolean, default=True)
    ssh_public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 状态机：pending / running / paused / success / failed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    interval_sec: Mapped[int] = mapped_column(Integer, default=15)  # 轮询间隔
    max_attempts: Mapped[int] = mapped_column(Integer, default=0)  # 0 = 不限
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    recent_logs: Mapped[str | None] = mapped_column(Text, nullable=True)  # 最近尝试日志 JSON 数组（最多 20 条）
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_instance_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="snatch_tasks")


class AliyunSpotTask(Base):
    """阿里云抢占式实例任务：后台轮询创建抢占式实例直到成功（对标 OCI 抢机）。"""

    __tablename__ = "aliyun_spot_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    region_id: Mapped[str] = mapped_column(String(64), default="")
    zone_id: Mapped[str] = mapped_column(String(64), default="")
    instance_type: Mapped[str] = mapped_column(String(64), default="")
    image_id: Mapped[str] = mapped_column(String(64), default="")
    vswitch_id: Mapped[str] = mapped_column(String(64), default="")
    security_group_id: Mapped[str] = mapped_column(String(64), default="")
    spot_strategy: Mapped[str] = mapped_column(String(32), default="SpotWithPriceLimit")  # SpotWithPriceLimit / SpotAsPriceGo
    spot_price_limit: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 最高出价（美元/小时）
    system_disk_category: Mapped[str] = mapped_column(String(32), default="cloud_essd")
    system_disk_size: Mapped[int] = mapped_column(Integer, default=40)
    bandwidth_out: Mapped[int] = mapped_column(Integer, default=5)
    instance_name: Mapped[str] = mapped_column(String(128), default="panel-spot")
    # 状态机：pending / running / paused / success / failed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    interval_sec: Mapped[int] = mapped_column(Integer, default=60)
    max_attempts: Mapped[int] = mapped_column(Integer, default=0)  # 0 = 不限
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    recent_logs: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_instance_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="aliyun_spot_tasks")


class ScheduledTask(Base):
    """定时任务：cron 表达式驱动的实例电源操作 / 换 IP。"""

    __tablename__ = "scheduled_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    task_type: Mapped[str] = mapped_column(String(32))  # power_on / power_off / reboot / change_ip
    instance_id: Mapped[str] = mapped_column(String(255))
    cron_expr: Mapped[str] = mapped_column(String(64))  # 标准 5 段 cron
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # success / failed
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class IpTask(Base):
    """换 IP 任务：按 CIDR 偏好更换实例公网 IP，可联动更新 DNS。"""

    __tablename__ = "ip_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    instance_id: Mapped[str] = mapped_column(String(255))
    preferred_cidrs: Mapped[str] = mapped_column(Text, default="[]")  # JSON 数组字符串
    update_dns: Mapped[bool] = mapped_column(Boolean, default=False)
    # 状态机：pending / running / success / failed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    old_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)  # CIDR 偏好未命中时的重换次数
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dns_updated: Mapped[bool] = mapped_column(Boolean, default=False)  # DNS 联动是否完成
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class DnsRecord(Base):
    """Cloudflare DNS 记录本地镜像。"""

    __tablename__ = "dns_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    zone_name: Mapped[str] = mapped_column(String(255))  # 如 example.com
    name: Mapped[str] = mapped_column(String(255))  # 如 www.example.com
    type: Mapped[str] = mapped_column(String(16), default="A")
    content: Mapped[str] = mapped_column(String(255))
    ttl: Mapped[int] = mapped_column(Integer, default=1)  # 1 = 自动
    proxied: Mapped[bool] = mapped_column(Boolean, default=False)
    cf_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)  # Cloudflare 侧 ID
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class NotificationConfig(Base):
    """通知渠道配置：telegram / email 等，config_json 存渠道参数。"""

    __tablename__ = "notification_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(32))  # telegram / email
    name: Mapped[str] = mapped_column(String(128), default="")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SystemSetting(Base):
    """系统键值配置：Cloudflare API Token 等。secret 置 1 时 value 经 Fernet 加密存储。"""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class OperationLog(Base):
    """操作审计日志：记录关键操作的 who / what / when。"""

    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(128))  # 如 snatch.start / instance.terminate
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    user: Mapped["User | None"] = relationship(back_populates="logs")


class IpLocationCache(Base):
    """IP 归属地缓存：ip-api.com 批量查询结果，TTL 30 天，过期后重新查询。"""

    __tablename__ = "ip_location_cache"

    ip: Mapped[str] = mapped_column(String(64), primary_key=True)
    country: Mapped[str | None] = mapped_column(String(128), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    isp: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ConsoleConnection(Base):
    """串行控制台连接：OCI Instance Console Connection，私钥 Fernet 加密存储。"""

    __tablename__ = "console_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    instance_id: Mapped[str] = mapped_column(String(255), nullable=False)
    instance_name: Mapped[str] = mapped_column(String(255), default="")
    connection_ocid: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    region: Mapped[str] = mapped_column(String(64), default="")
    private_key_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="CREATING")  # CREATING/ACTIVE/FAILED
    error: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
