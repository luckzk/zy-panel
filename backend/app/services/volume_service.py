"""引导卷服务：真实 OCI Block Storage 调用。"""
import logging
import time

import oci
from oci.exceptions import ConnectTimeout, ServiceError

from . import oci_factory

log = logging.getLogger(__name__)

# detach 后等待卸载完成的最长秒数
DETACH_WAIT_TIMEOUT_SEC = 90


class OciApiError(Exception):
    """可直接映射为接口错误码的 OCI 调用异常。"""

    def __init__(self, code: int, message: str, http_status: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _translate(exc: ServiceError, op: str) -> OciApiError:
    """把 OCI ServiceError 翻译为面向用户的错误码（与 instance_service 保持一致）。"""
    status = exc.status or 502
    if status == 401:
        return OciApiError(3101, f"{op}失败：OCI 认证失败，请检查租户的 API 密钥、私钥与指纹是否匹配", 502)
    if status == 429:
        return OciApiError(3102, f"{op}失败：OCI 接口限流，请稍后重试", 502)
    if status == 404:
        return OciApiError(3103, f"{op}失败：资源不存在 ({exc.code})", 502)
    return OciApiError(3103, f"{op}失败：[{exc.code}] {exc.message}", 502)


def _paginate(list_fn, **kwargs) -> list:
    """通用的 OCI 列表分页收集（opc-next-page）。"""
    items: list = []
    page = None
    while True:
        resp = list_fn(page=page, **kwargs) if page else list_fn(**kwargs)
        items.extend(resp.data)
        page = resp.headers.get("opc-next-page")
        if not page:
            break
    return items


def _client(tenant):
    try:
        return oci_factory.get_blockstorage_client(tenant)
    except ValueError as exc:
        raise OciApiError(3101, f"租户配置异常：{exc}", 502) from exc


def _compute_client(tenant):
    try:
        return oci_factory.get_compute_client(tenant)
    except ValueError as exc:
        raise OciApiError(3101, f"租户配置异常：{exc}", 502) from exc


def _to_out(bv, instance_map: dict, instance_name_map: dict) -> dict:
    iid = instance_map.get(bv.id)
    return {
        "id": bv.id,
        "display_name": bv.display_name,
        "size_in_gbs": bv.size_in_gbs,
        "lifecycle_state": bv.lifecycle_state,
        "availability_domain": getattr(bv, "availability_domain", None),
        "instance_id": iid,
        "instance_name": instance_name_map.get(iid, "") if iid else "",
        "time_created": bv.time_created.isoformat() if getattr(bv, "time_created", None) else None,
    }


def list_boot_volumes(tenant, compartment_id: str) -> list[dict]:
    """列出 compartment 下全部引导卷，并补全挂载实例。"""
    client = _client(tenant)
    try:
        volumes = _paginate(client.list_boot_volumes, compartment_id=compartment_id)
    except (ConnectTimeout,) as exc:
        raise OciApiError(3104, f"查询引导卷失败：连接 OCI 超时（{exc}）", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "查询引导卷") from exc

    # 一次查全 compartment 的挂载关系，避免逐卷请求
    # 注意：引导卷挂载必须用 list_boot_volume_attachments（必填 availability_domain），
    # list_volume_attachments 查的是数据卷，混用会导致挂载实例列为空
    instance_map: dict[str, str | None] = {}
    try:
        compute = oci_factory.get_compute_client(tenant)
        ads = {getattr(bv, "availability_domain", None) for bv in volumes}
        ads.discard(None)
        for ad in ads:
            atts = _paginate(
                compute.list_boot_volume_attachments,
                availability_domain=ad,
                compartment_id=compartment_id,
            )
            for a in atts:
                vid = getattr(a, "boot_volume_id", None)
                if vid:
                    instance_map[vid] = getattr(a, "instance_id", None)
    except Exception:
        log.warning("查询 boot volume attachments 失败，挂载实例列将为空", exc_info=True)
    # 实例名称映射（展示用）
    instance_name_map: dict[str, str] = {}
    try:
        compute = oci_factory.get_compute_client(tenant)
        insts = _paginate(compute.list_instances, compartment_id=compartment_id)
        for inst in insts:
            instance_name_map[inst.id] = getattr(inst, "display_name", "") or ""
    except Exception:
        log.warning("查询实例列表失败，挂载实例名称将为空", exc_info=True)
    return [_to_out(bv, instance_map, instance_name_map) for bv in volumes]


def _block_volume_to_out(bv, instance_map: dict, instance_name_map: dict) -> dict:
    iid = instance_map.get(bv.id)
    return {
        "id": bv.id,
        "display_name": bv.display_name,
        "size_in_gbs": bv.size_in_gbs,
        "lifecycle_state": bv.lifecycle_state,
        "availability_domain": getattr(bv, "availability_domain", None),
        "instance_id": iid,
        "instance_name": instance_name_map.get(iid, "") if iid else "",
        "time_created": bv.time_created.isoformat() if getattr(bv, "time_created", None) else None,
    }


def list_block_volumes(tenant, compartment_id: str) -> list[dict]:
    """列出 compartment 下全部数据卷，并补全挂载实例。"""
    client = _client(tenant)
    try:
        volumes = _paginate(client.list_volumes, compartment_id=compartment_id)
    except (ConnectTimeout,) as exc:
        raise OciApiError(3104, f"查询数据卷失败：连接 OCI 超时（{exc}）", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "查询数据卷") from exc

    # 数据卷挂载用 list_volume_attachments（无需 AD）
    instance_map: dict[str, str | None] = {}
    try:
        compute = oci_factory.get_compute_client(tenant)
        atts = _paginate(compute.list_volume_attachments, compartment_id=compartment_id)
        for a in atts:
            vid = getattr(a, "volume_id", None)
            if vid:
                instance_map[vid] = getattr(a, "instance_id", None)
    except Exception:
        log.warning("查询 volume attachments 失败，挂载实例列将为空", exc_info=True)
    instance_name_map: dict[str, str] = {}
    try:
        compute = oci_factory.get_compute_client(tenant)
        insts = _paginate(compute.list_instances, compartment_id=compartment_id)
        for inst in insts:
            instance_name_map[inst.id] = getattr(inst, "display_name", "") or ""
    except Exception:
        log.warning("查询实例列表失败，挂载实例名称将为空", exc_info=True)
    return [_block_volume_to_out(bv, instance_map, instance_name_map) for bv in volumes]


def get_boot_volume(tenant, volume_id: str) -> dict:
    """引导卷详情。"""
    client = _client(tenant)
    try:
        resp = client.get_boot_volume(volume_id)
    except (ConnectTimeout,) as exc:
        raise OciApiError(3104, f"查询引导卷详情失败：连接 OCI 超时（{exc}）", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "查询引导卷详情") from exc
    return _to_out(resp.data, {}, {})


def resize_boot_volume(tenant, volume_id: str, size_in_gbs: int) -> dict:
    """引导卷扩容（OCI 只允许调大）。"""
    current = get_boot_volume(tenant, volume_id)
    if size_in_gbs <= (current["size_in_gbs"] or 0):
        raise OciApiError(3103, f"扩容失败：目标大小（{size_in_gbs}GB）必须大于当前大小（{current['size_in_gbs']}GB）", 400)
    client = _client(tenant)
    details = oci.core.models.UpdateBootVolumeDetails(size_in_gbs=size_in_gbs)
    try:
        client.update_boot_volume(volume_id, details)
    except (ConnectTimeout,) as exc:
        raise OciApiError(3104, f"扩容引导卷失败：连接 OCI 超时（{exc}）", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "扩容引导卷") from exc
    log.info("引导卷 %s 已扩容至 %sGB", volume_id, size_in_gbs)
    return get_boot_volume(tenant, volume_id)


def resize_block_volume(tenant, volume_id: str, size_in_gbs: int) -> dict:
    """数据卷扩容（OCI 只允许调大）。"""
    client = _client(tenant)
    try:
        current = client.get_volume(volume_id).data
    except ServiceError as exc:
        raise _translate(exc, "查询数据卷") from exc
    if size_in_gbs <= (current.size_in_gbs or 0):
        raise OciApiError(3103, f"扩容失败：目标大小（{size_in_gbs}GB）必须大于当前大小（{current.size_in_gbs}GB）", 400)
    details = oci.core.models.UpdateVolumeDetails(size_in_gbs=size_in_gbs)
    try:
        client.update_volume(volume_id, details)
    except (ConnectTimeout,) as exc:
        raise OciApiError(3104, f"扩容数据卷失败：连接 OCI 超时（{exc}）", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "扩容数据卷") from exc
    log.info("数据卷 %s 已扩容至 %sGB", volume_id, size_in_gbs)
    return {"id": volume_id, "size_in_gbs": size_in_gbs}


def _get_raw_volume(tenant, volume_id: str):
    """取引导卷原始对象（含 compartment_id / availability_domain）。"""
    client = _client(tenant)
    try:
        return client.get_boot_volume(volume_id).data
    except (ConnectTimeout,) as exc:
        raise OciApiError(3104, f"查询引导卷失败：连接 OCI 超时（{exc}）", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "查询引导卷") from exc


def _list_volume_attachments(compute, compartment_id: str, volume_id: str) -> list:
    """查某卷的全部挂载关系。"""
    try:
        atts = _paginate(compute.list_volume_attachments, compartment_id=compartment_id, volume_id=volume_id)
    except (ConnectTimeout,) as exc:
        raise OciApiError(3104, f"查询卷挂载关系失败：连接 OCI 超时（{exc}）", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "查询卷挂载关系") from exc
    return [a for a in atts if getattr(a, "volume_id", None) == volume_id]


def _instance_lifecycle(compute, instance_id: str) -> str:
    try:
        return compute.get_instance(instance_id).data.lifecycle_state
    except (ConnectTimeout,) as exc:
        raise OciApiError(3104, f"查询实例状态失败：连接 OCI 超时（{exc}）", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "查询实例状态") from exc


def _wait_detached(compute, attachment_id: str, timeout_sec: int = DETACH_WAIT_TIMEOUT_SEC) -> None:
    """等待卸载完成（DETACHED），超时抛错。"""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            state = getattr(compute.get_volume_attachment(attachment_id).data, "lifecycle_state", "")
        except ServiceError as exc:
            # 404 说明 attachment 记录已消失，视为卸载完成
            if (exc.status or 0) == 404:
                return
            raise _translate(exc, "查询卸载状态") from exc
        if state == "DETACHED":
            return
        time.sleep(5)
    raise OciApiError(3103, "等待卷卸载超时，卸载可能仍在进行中，请稍后重试", 502)


def rescue_boot_volume(tenant, volume_id: str, rescue_instance_id: str) -> dict:
    """救援：把引导卷挂载到救援实例上拷数据。

    流程：查卷 -> 校验救援实例（存在、未终止、同 AD）-> 若卷正挂载在运行中实例上则拒绝 ->
    detach 旧挂载并等待 -> 以 paravirtualized 方式挂载到救援实例。
    """
    compute = _compute_client(tenant)
    vol = _get_raw_volume(tenant, volume_id)
    vol_ad = getattr(vol, "availability_domain", None)
    compartment_id = vol.compartment_id

    # 救援目标实例校验
    try:
        rescue_inst = compute.get_instance(rescue_instance_id).data
    except (ConnectTimeout,) as exc:
        raise OciApiError(3104, f"查询救援实例失败：连接 OCI 超时（{exc}）", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "查询救援实例") from exc
    if rescue_inst.lifecycle_state == "TERMINATED":
        raise OciApiError(3103, "救援失败：救援目标实例已终止", 400)
    if vol_ad and getattr(rescue_inst, "availability_domain", None) != vol_ad:
        raise OciApiError(
            3103,
            f"救援失败：卷与救援实例不在同一可用域（卷：{vol_ad}，实例：{rescue_inst.availability_domain}）",
            400,
        )

    # 处理现有挂载
    atts = _list_volume_attachments(compute, compartment_id, volume_id)
    for att in atts:
        inst_id = getattr(att, "instance_id", None)
        if inst_id == rescue_instance_id:
            raise OciApiError(3103, "该卷已挂载在救援目标实例上，无需重复操作", 400)
        state = _instance_lifecycle(compute, inst_id) if inst_id else "UNKNOWN"
        if state == "RUNNING":
            raise OciApiError(
                3103,
                f"救援失败：该卷正挂载在运行中的实例（{inst_id[-12:] if inst_id else '?'}）上，请先关机再救援",
                400,
            )
        log.info("救援：正在卸载卷 %s 的旧挂载 %s", volume_id, att.id)
        try:
            compute.detach_volume(att.id)
        except ServiceError as exc:
            raise _translate(exc, "卸载旧挂载") from exc
        _wait_detached(compute, att.id)

    # 挂载到救援实例
    details = oci.core.models.AttachParavirtualizedVolumeDetails(
        instance_id=rescue_instance_id, volume_id=volume_id
    )
    try:
        resp = compute.attach_volume(details)
    except (ConnectTimeout,) as exc:
        raise OciApiError(3104, f"挂载救援卷失败：连接 OCI 超时（{exc}）", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "挂载救援卷") from exc
    att = resp.data
    log.info("救援：卷 %s 已挂载到实例 %s（attachment %s）", volume_id, rescue_instance_id, att.id)
    return {
        "volume_id": volume_id,
        "rescue_instance_id": rescue_instance_id,
        "attachment_id": att.id,
        "lifecycle_state": getattr(att, "lifecycle_state", None),
    }


def unrescue_volume(tenant, volume_id: str) -> dict:
    """解除救援：卸载该卷的全部挂载。"""
    compute = _compute_client(tenant)
    vol = _get_raw_volume(tenant, volume_id)
    atts = _list_volume_attachments(compute, vol.compartment_id, volume_id)
    if not atts:
        raise OciApiError(3103, "该卷当前未挂载在任何实例上，无需解除", 400)
    detached = []
    for att in atts:
        log.info("解除救援：正在卸载卷 %s 的挂载 %s", volume_id, att.id)
        try:
            compute.detach_volume(att.id)
        except ServiceError as exc:
            raise _translate(exc, "卸载卷挂载") from exc
        _wait_detached(compute, att.id)
        detached.append(att.id)
    return {"volume_id": volume_id, "detached_attachments": detached, "count": len(detached)}
