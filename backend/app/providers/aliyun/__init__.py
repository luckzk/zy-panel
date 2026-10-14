"""阿里云 Provider：基于 aliyun-python-sdk-*（旧版 SDK，生态成熟）。"""
from __future__ import annotations

import json
import logging

from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.request import CommonRequest

from .. import register
from ..base import (
    Capability,
    CloudInstance,
    CloudProvider,
    CloudRegion,
    CloudSecurityGroup,
    PowerAction,
    ProviderError,
    ProviderStatus,
)

log = logging.getLogger(__name__)

# ECS 实例状态 -> 归一化状态
STATUS_MAP = {
    "Pending": ProviderStatus.PENDING,
    "Running": ProviderStatus.RUNNING,
    "Starting": ProviderStatus.STARTING,
    "Stopping": ProviderStatus.STOPPING,
    "Stopped": ProviderStatus.STOPPED,
}


def _text(v) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return ""


class AliyunProvider(CloudProvider):
    provider_id = "aliyun"
    display_name = "阿里云"
    capabilities = {
        Capability.INSTANCES,
        Capability.VOLUMES,
        Capability.SECURITY_GROUPS,
        Capability.IMAGES,
        Capability.MONITORING,
        Capability.SNAPSHOTS,
        Capability.EIP,
        Capability.SPOT,  # 抢占式实例
    }

    # ---------------- 客户端 ----------------
    def _client(self, region_id: str | None = None) -> tuple[AcsClient, str]:
        ak = self.credentials.get("access_key_id", "")
        sk = self.credentials.get("access_key_secret", "")
        region = region_id or self.credentials.get("region_id") or "cn-hangzhou"
        if not ak or not sk:
            raise ProviderError(3101, "阿里云 AK/SK 未配置", 502)
        return AcsClient(ak, sk, region), region

    def _do(self, client_region: tuple[AcsClient, str], action: str, params: dict | None = None,
            version: str = "2014-05-26", product: str = "Ecs",
            method: str = "POST") -> dict:
        """通用 RPC 调用，返回解析后的 dict。"""
        client, default_region = client_region
        req = CommonRequest()
        # 跨 region 时用目标 region 的 endpoint
        region = (params or {}).pop("_region", None) or default_region
        req.set_domain(f"{product.lower()}.{region}.aliyuncs.com")
        req.set_version(version)
        req.set_action_name(action)
        req.set_method(method)
        req.set_protocol_type("https")
        req.set_accept_format("json")
        for k, v in (params or {}).items():
            if v is not None:
                req.add_query_param(k, str(v))
        try:
            raw = client.do_action_with_exception(req)
        except Exception as exc:
            raise ProviderError(3104, f"阿里云 API 调用失败 [{action}]：{str(exc)[:200]}", 502)
        try:
            return json.loads(_text(raw))
        except ValueError as exc:
            raise ProviderError(3104, f"阿里云 API 返回解析失败 [{action}]：{exc}", 502)

    def _ecs(self, action: str, params: dict | None = None, region: str | None = None) -> dict:
        client = self._client(region or self.credentials.get("region_id"))
        p = dict(params or {})
        if region:
            p["_region"] = region
        return self._do(client, action, p, version="2014-05-26", product="Ecs")

    # ---------------- 基础能力 ----------------
    def test_connection(self) -> dict:
        try:
            resp = self._ecs("DescribeRegions", {})
            n = len(resp.get("Regions", {}).get("Region", []))
            return {"ok": True, "detail": f"DescribeRegions 成功，可见地域 {n} 个"}
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(3104, f"阿里云连通性测试失败：{str(exc)[:200]}", 502)

    def list_regions(self) -> list[CloudRegion]:
        resp = self._ecs("DescribeRegions", {})
        out = []
        for r in resp.get("Regions", {}).get("Region", []):
            rid = r.get("RegionId", "")
            out.append(CloudRegion(id=rid, name=r.get("LocalName") or rid, provider="aliyun"))
        return out

    # ---------------- 实例 ----------------
    @staticmethod
    def _to_instance(it: dict) -> CloudInstance:
        nets = it.get("PublicIpAddress") or {}
        pub_ips = nets.get("IpAddress") or []
        priv_nets = it.get("InnerIpAddress") or {}
        priv_ips = priv_nets.get("IpAddress") or []
        # 新版返回里也可能直接有字段
        pub = (pub_ips[0] if pub_ips else None) or it.get("EipAddress", {}).get("IpAddress")
        priv = (priv_ips[0] if priv_ips else None) or it.get("VpcAttributes", {}).get("PrivateIpAddress")
        vpc = it.get("VpcAttributes") or {}
        return CloudInstance(
            id=it.get("InstanceId", ""),
            name=it.get("InstanceName") or it.get("InstanceId", ""),
            provider="aliyun",
            region=it.get("RegionId", ""),
            zone=it.get("ZoneId", ""),
            status=STATUS_MAP.get(it.get("Status", ""), ProviderStatus.UNKNOWN),
            spec=it.get("InstanceType", ""),
            cpu=it.get("Cpu"),
            memory_gb=(it.get("Memory") / 1024) if it.get("Memory") else None,
            public_ip=pub,
            private_ip=priv,
            created_at=it.get("CreationTime"),
            tags={t.get("TagKey"): t.get("TagValue") for t in it.get("Tags", {}).get("Tag", [])},
            raw={**it, "_vpc_id": vpc.get("VpcId"), "_vswitch_id": vpc.get("VSwitchId")},
        )

    def list_instances(self, region_id: str | None = None) -> list[CloudInstance]:
        self.require(Capability.INSTANCES)
        region = region_id or self.credentials.get("region_id") or ""
        items: list[dict] = []
        page, size = 1, 50
        while True:
            resp = self._ecs("DescribeInstances", {
                "RegionId": region, "PageNumber": page, "PageSize": size,
            }, region=region)
            batch = resp.get("Instances", {}).get("Instance", [])
            items.extend(batch)
            total = int(resp.get("TotalCount", 0))
            if page * size >= total or not batch:
                break
            page += 1
        return [self._to_instance(it) for it in items]

    def get_instance(self, instance_id: str) -> CloudInstance:
        self.require(Capability.INSTANCES)
        region = self.credentials.get("region_id") or ""
        resp = self._ecs("DescribeInstances", {
            "RegionId": region, "InstanceIds": f'["{instance_id}"]',
        }, region=region)
        batch = resp.get("Instances", {}).get("Instance", [])
        if not batch:
            raise ProviderError(3404, f"实例不存在：{instance_id}", 404)
        return self._to_instance(batch[0])

    def power_instance(self, instance_id: str, action: PowerAction) -> None:
        self.require(Capability.INSTANCES)
        region = self.credentials.get("region_id") or ""
        mapping = {
            PowerAction.START: "StartInstance",
            PowerAction.STOP: "StopInstance",
            PowerAction.REBOOT: "RebootInstance",
        }
        params: dict = {"RegionId": region, "InstanceId": instance_id}
        if action == PowerAction.STOP:
            params["StoppedMode"] = "StopCharging"  # 停机不收费（按量实例）
        self._ecs(mapping[action], params, region=region)

    # ---------------- 镜像管理 ----------------
    def list_images(self) -> list[dict]:
        self.require(Capability.IMAGES)
        region = self.credentials.get("region_id") or ""
        items: list[dict] = []
        page, size = 1, 50
        while True:
            resp = self._ecs("DescribeImages", {
                "RegionId": region, "ImageOwnerAlias": "self",
                "PageNumber": page, "PageSize": size,
            }, region=region)
            batch = resp.get("Images", {}).get("Image", [])
            items.extend(batch)
            total = int(resp.get("TotalCount", 0))
            if page * size >= total or not batch:
                break
            page += 1
        out = []
        for im in items:
            out.append({
                "id": im.get("ImageId", ""),
                "name": im.get("ImageName") or im.get("ImageId", ""),
                "os_name": im.get("OSName", ""),
                "os_type": im.get("OSType", ""),
                "architecture": im.get("Architecture", ""),
                "size_gb": im.get("Size"),
                "status": im.get("Status", ""),
                "created_at": im.get("CreationTime", ""),
                "description": im.get("Description", ""),
            })
        return out

    def list_public_images(self, os_type: str = "linux") -> list[dict]:
        """公共镜像（用于创建实例/抢占式任务时选择）。"""
        region = self.credentials.get("region_id") or ""
        items: list[dict] = []
        page, size = 1, 50
        while True:
            resp = self._ecs("DescribeImages", {
                "RegionId": region, "ImageOwnerAlias": "system",
                "OSType": os_type, "PageNumber": page, "PageSize": size,
            }, region=region)
            batch = resp.get("Images", {}).get("Image", [])
            items.extend(batch)
            total = int(resp.get("TotalCount", 0))
            if page * size >= total or not batch or page >= 4:  # 公共镜像太多，只取前 200
                break
            page += 1
        out = []
        for im in items:
            out.append({
                "id": im.get("ImageId", ""),
                "name": im.get("ImageName") or im.get("ImageId", ""),
                "os_name": im.get("OSName", ""),
                "architecture": im.get("Architecture", ""),
                "size_gb": im.get("Size"),
            })
        return out

    def create_image(self, instance_id: str | None = None, snapshot_id: str | None = None,
                     name: str = "", description: str = "") -> dict:
        self.require(Capability.IMAGES)
        region = self.credentials.get("region_id") or ""
        params: dict = {"RegionId": region, "ImageName": name or f"panel-image-{instance_id or snapshot_id}"}
        if description:
            params["Description"] = description
        if instance_id:
            params["InstanceId"] = instance_id
        elif snapshot_id:
            params["SnapshotId"] = snapshot_id
        else:
            raise ProviderError(3400, "必须指定 instance_id 或 snapshot_id")
        resp = self._ecs("CreateImage", params, region=region)
        return {"image_id": resp.get("ImageId", "")}

    def delete_image(self, image_id: str) -> None:
        self.require(Capability.IMAGES)
        region = self.credentials.get("region_id") or ""
        self._ecs("DeleteImage", {"RegionId": region, "ImageId": image_id}, region=region)

    # ---------------- 费用（BSS） ----------------
    # 国内站 business.aliyuncs.com；国际站账号调国内站报 AuthSiteFail，需切
    # business.ap-southeast-1.aliyuncs.com（官方文档 BSS OpenAPI 国际站 endpoint）。
    _BSS_DOMAINS = ("business.aliyuncs.com", "business.ap-southeast-1.aliyuncs.com")

    def _bss(self, action: str, params: dict | None = None) -> dict:
        """BSS 通用调用：国内站优先，AuthSiteFail 时自动切换国际站 endpoint 重试。"""
        from aliyunsdkcore.request import CommonRequest
        import json as _json
        region = self.credentials.get("region_id") or ""
        client, _ = self._client(region)
        last_exc: Exception | None = None
        for domain in self._BSS_DOMAINS:
            req = CommonRequest()
            req.set_domain(domain)
            req.set_version("2017-12-14")
            req.set_action_name(action)
            req.set_method("POST")
            req.set_protocol_type("https")
            req.set_accept_format("json")
            for k, v in (params or {}).items():
                if v is not None:
                    req.add_query_param(k, str(v))
            try:
                raw = client.do_action_with_exception(req)
                return _json.loads(raw.decode("utf-8", errors="replace"))
            except Exception as exc:
                if "AuthSiteFail" not in str(exc):
                    raise ProviderError(3104, f"阿里云 BSS 调用失败 [{action}]：{str(exc)[:200]}", 502)
                last_exc = exc
                log.info("BSS %s 在 %s 返回 AuthSiteFail，切换国际站 endpoint 重试", action, domain)
        raise ProviderError(3104, f"阿里云 BSS 调用失败 [{action}]：{str(last_exc)[:200]}", 502)

    def get_account_balance(self) -> dict:
        """账户余额（BSS QueryAccountBalance）。"""
        data = self._bss("QueryAccountBalance")
        d = data.get("Data", {})
        return {
            "available_amount": d.get("AvailableAmount", ""),
            "credit_amount": d.get("CreditAmount", ""),
            "currency": d.get("Currency", "CNY"),
            "mybank_credit_amount": d.get("MybankCreditAmount", ""),
        }

    def get_month_bill(self) -> dict:
        """当月账单汇总（BSS DescribeInstanceBill 按产品分组）。"""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        cycle = now.strftime("%Y-%m")
        data = self._bss("DescribeInstanceBill", {
            "BillingCycle": cycle,
            "PageNum": 1,
            "PageSize": 200,
            "IsGroupByProduct": "true",
        })
        d = data.get("Data", {})
        raw_items = d.get("Items", [])
        # Items 可能是 list 或 {"Item": [...]}
        items = raw_items if isinstance(raw_items, list) else raw_items.get("Item", [])
        products = []
        total = 0.0
        for it in items:
            amt = float(it.get("PretaxAmount", 0) or 0)
            total += amt
            products.append({
                "product": it.get("ProductName", ""),
                "product_code": it.get("ProductCode", ""),
                "amount": round(amt, 2),
                "currency": it.get("Currency", "CNY"),
            })
        products.sort(key=lambda x: -x["amount"])
        return {"billing_cycle": d.get("BillingCycle", cycle), "total": round(total, 2), "products": products}

    # ---------------- 抢占式实例任务支持 ----------------
    def list_instance_types(self, zone_id: str = "") -> list[dict]:
        """可用实例规格（用于抢占式任务选择）。"""
        region = self.credentials.get("region_id") or ""
        params: dict = {"RegionId": region}
        if zone_id:
            params["ZoneId"] = zone_id
        resp = self._ecs("DescribeInstanceTypes", params, region=region)
        out = []
        for t in resp.get("InstanceTypes", {}).get("InstanceType", []):
            out.append({
                "id": t.get("InstanceTypeId", ""),
                "cpu": t.get("CpuCoreCount"),
                "memory_gb": t.get("MemorySize"),
                "family": t.get("InstanceTypeFamily", ""),
            })
        return out

    def list_vswitches(self, zone_id: str = "") -> list[dict]:
        """交换机列表（创建实例需要 VSwitchId）。"""
        region = self.credentials.get("region_id") or ""
        params: dict = {"RegionId": region, "PageSize": 50}
        if zone_id:
            params["ZoneId"] = zone_id
        resp = self._ecs("DescribeVSwitches", params, region=region)
        out = []
        for v in resp.get("VSwitches", {}).get("VSwitch", []):
            out.append({
                "id": v.get("VSwitchId", ""),
                "name": v.get("VSwitchName") or v.get("VSwitchId", ""),
                "zone_id": v.get("ZoneId", ""),
                "cidr": v.get("CidrBlock", ""),
                "vpc_id": v.get("VpcId", ""),
            })
        return out

    def run_spot_instance(self, spec: dict) -> dict:
        """创建抢占式实例（单次尝试）。spec 字段见抢占式任务模型。"""
        self.require(Capability.SPOT)
        region = self.credentials.get("region_id") or ""
        params: dict = {
            "RegionId": spec["region_id"],
            "ZoneId": spec.get("zone_id", ""),
            "ImageId": spec["image_id"],
            "InstanceType": spec["instance_type"],
            "VSwitchId": spec["vswitch_id"],
            "SecurityGroupId": spec["security_group_id"],
            "InstanceChargeType": "PostPaid",
            "SpotStrategy": spec.get("spot_strategy", "SpotWithPriceLimit"),
            "InstanceName": spec.get("instance_name", "panel-spot"),
            "SystemDisk.Category": spec.get("system_disk_category", "cloud_essd"),
            "SystemDisk.Size": spec.get("system_disk_size", 40),
            "InternetMaxBandwidthOut": spec.get("bandwidth_out", 5),
            "PasswordInherit": "true",
            "MinAmount": 1,
            "MaxAmount": 1,
        }
        if spec.get("spot_strategy", "SpotWithPriceLimit") == "SpotWithPriceLimit":
            params["SpotPriceLimit"] = spec.get("spot_price_limit", "")
        # 清理空值
        params = {k: v for k, v in params.items() if v != "" and v is not None}
        resp = self._ecs("RunInstances", params, region=region)
        ids = resp.get("InstanceIdSets", {}).get("InstanceIdSet", [])
        return {"instance_ids": ids}

    # ---------------- 安全组 ----------------    def list_security_groups(self, region_id: str | None = None) -> list[CloudSecurityGroup]:
        self.require(Capability.SECURITY_GROUPS)
        region = region_id or self.credentials.get("region_id") or ""
        resp = self._ecs("DescribeSecurityGroups", {"RegionId": region}, region=region)
        out = []
        for sg in resp.get("SecurityGroups", {}).get("SecurityGroup", []):
            out.append(CloudSecurityGroup(
                id=sg.get("SecurityGroupId", ""),
                name=sg.get("SecurityGroupName") or sg.get("SecurityGroupId", ""),
                provider="aliyun",
                region=region,
                description=sg.get("Description") or "",
                raw=sg,
            ))
        return out

    # ---------------- 磁盘（对标卷管理） ----------------
    def list_volumes(self, region_id: str | None = None) -> list[CloudVolume]:
        from ..base import CloudVolume
        self.require(Capability.VOLUMES)
        region = region_id or self.credentials.get("region_id") or ""
        items: list[dict] = []
        page, size = 1, 50
        while True:
            resp = self._ecs("DescribeDisks", {
                "RegionId": region, "PageNumber": page, "PageSize": size,
            }, region=region)
            batch = resp.get("Disks", {}).get("Disk", [])
            items.extend(batch)
            total = int(resp.get("TotalCount", 0))
            if page * size >= total or not batch:
                break
            page += 1
        out = []
        for d in items:
            out.append(CloudVolume(
                id=d.get("DiskId", ""),
                name=d.get("DiskName") or d.get("DiskId", ""),
                provider="aliyun",
                region=region,
                zone=d.get("ZoneId", ""),
                size_gb=d.get("Size"),
                status=d.get("Status", ""),
                volume_type=d.get("Category", ""),
                attached_instance_id=d.get("InstanceId") or None,
                attached_instance_name=None,
                created_at=d.get("CreationTime"),
                raw=d,
            ))
        return out

    def resize_disk(self, disk_id: str, new_size_gb: int) -> None:
        self.require(Capability.VOLUMES)
        region = self.credentials.get("region_id") or ""
        self._ecs("ResizeDisk", {
            "RegionId": region, "DiskId": disk_id, "NewSize": new_size_gb,
        }, region=region)

    # ---------------- 快照（对标定制映像） ----------------
    def list_snapshots(self, disk_id: str | None = None) -> list[dict]:
        self.require(Capability.SNAPSHOTS)
        region = self.credentials.get("region_id") or ""
        params: dict = {"RegionId": region, "PageSize": 50}
        if disk_id:
            params["DiskId"] = disk_id
        resp = self._ecs("DescribeSnapshots", params, region=region)
        out = []
        for s in resp.get("Snapshots", {}).get("Snapshot", []):
            out.append({
                "id": s.get("SnapshotId", ""),
                "name": s.get("SnapshotName") or s.get("SnapshotId", ""),
                "disk_id": s.get("SourceDiskId", ""),
                "disk_name": s.get("SourceDiskName", ""),
                "size_gb": s.get("SourceDiskSize"),
                "status": s.get("Status", ""),
                "progress": s.get("Progress", ""),
                "created_at": s.get("CreationTime", ""),
                "usage": s.get("Usage", ""),
            })
        return out

    def create_snapshot(self, disk_id: str, name: str = "") -> dict:
        self.require(Capability.SNAPSHOTS)
        region = self.credentials.get("region_id") or ""
        resp = self._ecs("CreateSnapshot", {
            "RegionId": region, "DiskId": disk_id,
            "SnapshotName": name or f"panel-{disk_id[-8:]}",
        }, region=region)
        return {"snapshot_id": resp.get("SnapshotId", "")}

    def delete_snapshot(self, snapshot_id: str) -> None:
        self.require(Capability.SNAPSHOTS)
        region = self.credentials.get("region_id") or ""
        self._ecs("DeleteSnapshot", {"RegionId": region, "SnapshotId": snapshot_id}, region=region)

    # ---------------- EIP（对标换公网 IP） ----------------
    def list_eips(self) -> list[dict]:
        self.require(Capability.EIP)
        region = self.credentials.get("region_id") or ""
        resp = self._ecs("DescribeEipAddresses", {"RegionId": region}, region=region)
        out = []
        for e in resp.get("EipAddresses", {}).get("EipAddress", []):
            out.append({
                "id": e.get("AllocationId", ""),
                "ip": e.get("IpAddress", ""),
                "status": e.get("Status", ""),
                "instance_id": e.get("InstanceId", ""),
                "instance_type": e.get("InstanceType", ""),
                "bandwidth": e.get("Bandwidth", ""),
                "internet_charge_type": e.get("InternetChargeType", ""),
                "created_at": e.get("CreationTime", ""),
            })
        return out

    def allocate_eip(self, bandwidth: int = 5) -> dict:
        self.require(Capability.EIP)
        region = self.credentials.get("region_id") or ""
        resp = self._ecs("AllocateEipAddress", {
            "RegionId": region, "Bandwidth": bandwidth,
            "InternetChargeType": "PayByTraffic",
        }, region=region)
        return {"allocation_id": resp.get("AllocationId", ""), "ip": resp.get("EipAddress", "")}

    def associate_eip(self, allocation_id: str, instance_id: str) -> None:
        self.require(Capability.EIP)
        region = self.credentials.get("region_id") or ""
        self._ecs("AssociateEipAddress", {
            "RegionId": region, "AllocationId": allocation_id, "InstanceId": instance_id,
        }, region=region)

    def unassociate_eip(self, allocation_id: str, instance_id: str) -> None:
        self.require(Capability.EIP)
        region = self.credentials.get("region_id") or ""
        self._ecs("UnassociateEipAddress", {
            "RegionId": region, "AllocationId": allocation_id, "InstanceId": instance_id,
        }, region=region)

    def release_eip(self, allocation_id: str) -> None:
        self.require(Capability.EIP)
        region = self.credentials.get("region_id") or ""
        self._ecs("ReleaseEipAddress", {"RegionId": region, "AllocationId": allocation_id}, region=region)

    # ---------------- 监控（CMS，对标监视 Tab） ----------------
    def get_instance_metrics(self, instance_id: str, hours: int = 6) -> list[dict]:
        """CMS DescribeMetricList：CPU/内存/内外网带宽。"""
        from datetime import datetime, timedelta, timezone
        self.require(Capability.MONITORING)
        region = self.credentials.get("region_id") or ""
        client, _ = self._client(region)
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=max(1, min(hours, 72)))
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        metrics = [
            ("cpu_total", "CPU 使用率", "%"),
            ("memory_usedutilization", "内存使用率", "%"),
            ("intranet_in", "内网入带宽", "bit/s"),
            ("intranet_out", "内网出带宽", "bit/s"),
            ("internet_in", "公网入带宽", "bit/s"),
            ("internet_out", "公网出带宽", "bit/s"),
        ]
        charts = []
        for metric, title, _unit in metrics:
            try:
                points = [{"time": t, "value": v}
                          for t, v in self._cms_metric(client, region, instance_id, metric, start, end, fmt)]
                charts.append({"metric": metric, "title": title, "points": points})
            except Exception as exc:
                log.warning("阿里云指标 %s 查询失败: %s", metric, exc)
                charts.append({"metric": metric, "title": title, "points": [],
                               "error": str(exc)[:150]})
        return charts

    def _cms_metric(self, client, region: str, instance_id: str, metric: str,
                   start, end, fmt: str) -> list[tuple]:
        from aliyunsdkcore.request import CommonRequest
        req = CommonRequest()
        req.set_domain(f"metrics.{region}.aliyuncs.com")
        req.set_version("2019-01-01")
        req.set_action_name("DescribeMetricList")
        req.set_method("POST")
        req.set_protocol_type("https")
        req.set_accept_format("json")
        req.add_query_param("Namespace", "acs_ecs_dashboard")
        req.add_query_param("MetricName", metric)
        req.add_query_param("Dimensions", f'[{{"instanceId": "{instance_id}"}}]')
        req.add_query_param("StartTime", start.strftime(fmt))
        req.add_query_param("EndTime", end.strftime(fmt))
        req.add_query_param("Period", "3600")
        import json as _json
        raw = client.do_action_with_exception(req)
        data = _json.loads(raw.decode("utf-8", errors="replace"))
        datapoints = _json.loads(data.get("Datapoints", "[]"))
        out = []
        for dp in datapoints:
            # CMS 返回 {"timestamp": 169..., "Minimum": x, "Average": y, "Maximum": z}
            ts = dp.get("timestamp")
            val = dp.get("Average", dp.get("Maximum", dp.get("Minimum")))
            if ts is not None and val is not None:
                from datetime import datetime as _dt, timezone as _tz
                t = _dt.fromtimestamp(ts / 1000, tz=_tz.utc).strftime("%Y-%m-%d %H:%M")
                out.append((t, round(float(val), 2)))
        out.sort(key=lambda x: x[0])
        return out


register(AliyunProvider)
