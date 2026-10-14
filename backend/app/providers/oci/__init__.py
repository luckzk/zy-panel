"""OCI Provider：适配现有 instance_service 等，不重写。"""
from __future__ import annotations

from ..base import (
    Capability,
    CloudInstance,
    CloudProvider,
    CloudRegion,
    PowerAction,
    ProviderError,
    ProviderStatus,
)
from ...services import instance_service
from ...services.instance_service import OciApiError


def _to_provider_error(exc: OciApiError) -> ProviderError:
    return ProviderError(exc.code, exc.message, exc.http_status)


OCI_STATUS_MAP = {
    "RUNNING": ProviderStatus.RUNNING,
    "STOPPED": ProviderStatus.STOPPED,
    "STOPPING": ProviderStatus.STOPPING,
    "STARTING": ProviderStatus.STARTING,
    "TERMINATED": ProviderStatus.TERMINATED,
    "TERMINATING": ProviderStatus.TERMINATED,
    "CREATING_IMAGE": ProviderStatus.PENDING,
    "PROVISIONING": ProviderStatus.PENDING,
}


class OciProvider(CloudProvider):
    provider_id = "oci"
    display_name = "Oracle Cloud"
    capabilities = {
        Capability.INSTANCES,
        Capability.VOLUMES,
        Capability.SECURITY_GROUPS,
        Capability.IMAGES,
        Capability.MONITORING,
        Capability.SNAPSHOTS,
        Capability.SPOT,            # 抢机
        Capability.SERIAL_CONSOLE,
    }

    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except OciApiError as exc:
            raise _to_provider_error(exc)

    @staticmethod
    def _to_instance(d: dict) -> CloudInstance:
        return CloudInstance(
            id=d.get("ocid") or d.get("id") or "",
            name=d.get("name") or "",
            provider="oci",
            region=d.get("region") or "",
            zone=d.get("availability_domain") or d.get("ad") or "",
            status=OCI_STATUS_MAP.get((d.get("status") or "").upper(), ProviderStatus.UNKNOWN),
            spec=d.get("shape") or "",
            cpu=d.get("ocpus"),
            memory_gb=d.get("memory_gb") or d.get("memoryGb"),
            public_ip=d.get("public_ip") or d.get("publicIp"),
            private_ip=d.get("private_ip") or d.get("privateIp"),
            created_at=d.get("created_at") or d.get("createdAt"),
            tags=d.get("freeform_tags") or {},
            raw=d,
        )

    def list_instances(self) -> list[CloudInstance]:
        self.require(Capability.INSTANCES)
        items = self._call(instance_service.list_instances, self.tenant)
        return [self._to_instance(d) for d in items]

    def get_instance(self, instance_id: str) -> CloudInstance:
        self.require(Capability.INSTANCES)
        d = self._call(instance_service.get_instance_detail, self.tenant, instance_id)
        return self._to_instance(d)

    def power_instance(self, instance_id: str, action: PowerAction) -> None:
        self.require(Capability.INSTANCES)
        mapping = {
            PowerAction.START: "start",
            PowerAction.STOP: "stop",
            PowerAction.REBOOT: "reboot",
        }
        self._call(instance_service.power_instance, self.tenant, instance_id, mapping[action])

    def list_regions(self) -> list[CloudRegion]:
        import oci as _oci
        regions = []
        for r in _oci.regions.REGIONS:
            if "-gov-" in r or "-dcc-" in r:
                continue
            regions.append(CloudRegion(id=r, name=r, provider="oci"))
        return regions

    def test_connection(self) -> dict:
        from ...services.oci_factory import get_identity_client
        try:
            client = get_identity_client(self.tenant)
            ads = client.list_availability_domains(self.credentials["tenancy_ocid"]).data
            return {"ok": True, "detail": f"可用域 {len(ads)} 个"}
        except Exception as exc:
            raise ProviderError(3104, f"OCI 连通性测试失败：{str(exc)[:200]}", 502)


from .. import register as _register

_register(OciProvider)
