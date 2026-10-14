"""实例路由：实例列表/详情/电源操作/改名/改配/终止。

列表、详情、电源操作、改名、改 shape、终止已接入真实 OCI 调用。
"""
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import instance_service, instance_tabs_service
from ..services.instance_service import OciApiError
from ..services.oci_factory import get_compute_client, get_network_client, get_blockstorage_client

log = logging.getLogger(__name__)

router = APIRouter(prefix="/instances", tags=["实例管理"])


class PowerAction(BaseModel):
    tenant_id: int
    action: str  # start | stop | reboot


class RenameIn(BaseModel):
    tenant_id: int
    display_name: str


class ShapeIn(BaseModel):
    tenant_id: int
    shape: str
    ocpus: float | None = None
    memory_in_gbs: float | None = None


class TerminateIn(BaseModel):
    tenant_id: int
    preserve_boot_volume: bool = True


class TenantIdIn(BaseModel):
    tenant_id: int


def _get_tenant_or_404(db: Session, tenant_id: int):
    tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
    if tenant is None:
        return None
    return tenant


def _handle_oci(exc: OciApiError):
    return err(exc.code, exc.message, status=exc.http_status)


@router.get("", summary="实例列表（多云分发）")
def list_instances(
    tenant_id: int = Query(description="租户 ID（必填）"),
    state: str | None = Query(default=None, description="按状态筛选，如 RUNNING"),
    search: str | None = Query(default=None, description="按名称/IP 模糊搜索"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=50, ge=1, le=200, description="每页条数"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from ..providers import get_provider
    from ..providers.base import ProviderError

    tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    provider_id = getattr(tenant, "provider", None) or "oci"
    if provider_id != "oci":
        # 非 OCI 走 Provider 归一化接口
        try:
            provider = get_provider(tenant)
            items = [i.to_dict() for i in provider.list_instances()]
        except ProviderError as exc:
            return err(exc.code, exc.message, status=exc.http_status)
        except Exception as exc:
            log.exception("查询实例列表未知异常 tenant_id=%s", tenant_id)
            return err(3100, f"查询实例失败：{str(exc)[:200]}", status=500)
        if state:
            items = [i for i in items if i["status"] == state.upper()]
        if search:
            kw = search.lower()
            items = [i for i in items
                     if kw in (i["name"] or "").lower() or kw in (i["public_ip"] or "").lower()]
        total = len(items)
        start, end = (page - 1) * page_size, page * page_size
        return ok({"total": total, "items": items[start:end], "provider": provider_id})
    try:
        items = instance_service.list_instances(tenant)
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:  # 兜底：未知异常不暴露堆栈
        log.exception("查询实例列表未知异常 tenant_id=%s", tenant_id)
        return err(3100, f"查询实例失败：{str(exc)[:200]}", status=500)

    if state:
        items = [i for i in items if i["lifecycle_state"] == state.upper()]
    if search:
        kw = search.lower()
        items = [
            i
            for i in items
            if kw in (i["display_name"] or "").lower() or kw in (i["public_ip"] or "").lower()
        ]
    total = len(items)
    start = (page - 1) * page_size
    return ok({"items": items[start : start + page_size], "total": total, "page": page, "page_size": page_size})


@router.get("/{instance_id}", summary="实例详情（多云分发）")
def get_instance(
    instance_id: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _get_tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    provider_id = getattr(tenant, "provider", None) or "oci"
    if provider_id != "oci":
        from ..providers import get_provider
        from ..providers.base import ProviderError
        try:
            provider = get_provider(tenant)
            return ok(provider.get_instance(instance_id).to_dict())
        except ProviderError as exc:
            return err(exc.code, exc.message, status=exc.http_status)
        except Exception:
            log.exception("获取实例详情未知异常 tenant_id=%s", tenant_id)
            return err(3100, "获取实例详情失败", status=500)
    try:
        return ok(instance_service.get_instance_detail(tenant, instance_id))
    except OciApiError as exc:
        return _handle_oci(exc)
    except Exception:
        log.exception("获取实例详情未知异常 tenant_id=%s", tenant_id)
        return err(3100, "获取实例详情失败", status=500)


@router.post("/{instance_id}/power", summary="电源操作：start/stop/reboot（多云分发）")
def power_instance(instance_id: str, body: PowerAction, _user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.action not in ("start", "stop", "reboot"):
        return err(3002, "action 仅支持 start/stop/reboot", status=400)
    tenant = _get_tenant_or_404(db, body.tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    provider_id = getattr(tenant, "provider", None) or "oci"
    if provider_id != "oci":
        from ..providers import get_provider
        from ..providers.base import PowerAction as PAction, ProviderError
        try:
            provider = get_provider(tenant)
            provider.power_instance(instance_id, PAction(body.action))
            return ok({"instance_id": instance_id, "action": body.action})
        except ProviderError as exc:
            return err(exc.code, exc.message, status=exc.http_status)
        except Exception:
            log.exception("电源操作未知异常 tenant_id=%s", body.tenant_id)
            return err(3100, "电源操作失败", status=500)
    try:
        return ok(instance_service.power_instance(tenant, instance_id, body.action))
    except OciApiError as exc:
        return _handle_oci(exc)
    except Exception:
        log.exception("电源操作未知异常 tenant_id=%s", body.tenant_id)
        return err(3100, "电源操作失败", status=500)


@router.put("/{instance_id}/name", summary="改实例名")
def rename_instance(instance_id: str, body: RenameIn, _user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not body.display_name.strip():
        return err(3002, "display_name 不能为空", status=400)
    tenant = _get_tenant_or_404(db, body.tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(instance_service.rename_instance(tenant, instance_id, body.display_name.strip()))
    except OciApiError as exc:
        return _handle_oci(exc)
    except Exception:
        log.exception("改名未知异常 tenant_id=%s", body.tenant_id)
        return err(3100, "修改实例名称失败", status=500)


@router.put("/{instance_id}/shape", summary="改实例配置 shape（实例需关机）")
def update_shape(instance_id: str, body: ShapeIn, _user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    tenant = _get_tenant_or_404(db, body.tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    if not body.shape or not body.shape.strip():
        return err(3002, "shape 不能为空", status=400)
    if "Flex" in body.shape and (body.ocpus is None or body.memory_in_gbs is None):
        return err(3002, "Flex 机型必须指定 OCPU 数和内存大小", status=400)
    try:
        return ok(instance_service.change_shape(tenant, instance_id, body.shape.strip(), body.ocpus, body.memory_in_gbs))
    except OciApiError as exc:
        return _handle_oci(exc)
    except Exception:
        log.exception("改 Shape 未知异常 tenant_id=%s", body.tenant_id)
        return err(3100, "更改实例 Shape 失败", status=500)


@router.post("/{instance_id}/terminate", summary="终止实例（二次确认由前端 Popconfirm 完成）")
def terminate_instance(instance_id: str, body: TerminateIn, _user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    tenant = _get_tenant_or_404(db, body.tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(instance_service.terminate_instance(tenant, instance_id, body.preserve_boot_volume))
    except OciApiError as exc:
        return _handle_oci(exc)
    except Exception:
        log.exception("终止实例未知异常 tenant_id=%s", body.tenant_id)
        return err(3100, "终止实例失败", status=500)


# ============================================================ 实例详情 Tab 接口
def _tab_ctx(db: Session, tenant_id: int, instance_id: str):
    """Tab 接口通用上下文：tenant + compute/network/blockstorage client + instance。"""
    tenant = _get_tenant_or_404(db, tenant_id)
    if tenant is None:
        return None, err(3004, "租户不存在", status=404)
    try:
        compute = get_compute_client(tenant)
        network = get_network_client(tenant)
        try:
            blockstorage = get_blockstorage_client(tenant)
        except ValueError:
            blockstorage = None
        inst = compute.get_instance(instance_id).data
    except OciApiError as exc:
        return None, _handle_oci(exc)
    except Exception as exc:
        return None, err(3100, f"查询失败：{str(exc)[:200]}", status=500)
    return {"tenant": tenant, "compute": compute, "network": network,
            "blockstorage": blockstorage, "inst": inst}, None


@router.get("/{instance_id}/tabs/detail-extra", summary="详细信息 Tab：启动选项/映像/容量类型")
def tab_detail_extra(instance_id: str, tenant_id: int = Query(description="租户 ID（必填）"),
                     _user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx, err_resp = _tab_ctx(db, tenant_id, instance_id)
    if err_resp:
        return err_resp
    try:
        return ok(instance_tabs_service.get_detail_extra(ctx["inst"], ctx["compute"]))
    except Exception:
        log.exception("详细信息 Tab 查询异常")
        return err(3100, "查询失败", status=500)


@router.get("/{instance_id}/tabs/network", summary="网络 Tab：路由表/FQDN/附加 VNIC")
def tab_network(instance_id: str, tenant_id: int = Query(description="租户 ID（必填）"),
                _user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx, err_resp = _tab_ctx(db, tenant_id, instance_id)
    if err_resp:
        return err_resp
    try:
        vnic_full = instance_service._get_primary_vnic_full(
            ctx["network"], ctx["compute"], instance_id, ctx["inst"].compartment_id)
        return ok(instance_tabs_service.get_network_tab(
            ctx["network"], ctx["compute"], instance_id, ctx["inst"].compartment_id, vnic_full))
    except Exception:
        log.exception("网络 Tab 查询异常")
        return err(3100, "查询失败", status=500)


@router.get("/{instance_id}/tabs/storage", summary="存储 Tab：引导卷/数据卷扩展信息")
def tab_storage(instance_id: str, tenant_id: int = Query(description="租户 ID（必填）"),
                _user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx, err_resp = _tab_ctx(db, tenant_id, instance_id)
    if err_resp:
        return err_resp
    try:
        return ok(instance_tabs_service.get_storage_tab(
            ctx["compute"], ctx["blockstorage"], ctx["inst"].compartment_id,
            instance_id, ctx["inst"].availability_domain,
            image_id=getattr(ctx["inst"], "image_id", None)))
    except Exception:
        log.exception("存储 Tab 查询异常")
        return err(3100, "查询失败", status=500)


@router.get("/{instance_id}/tabs/security", summary="安全 Tab：安全列表规则明细")
def tab_security(instance_id: str, tenant_id: int = Query(description="租户 ID（必填）"),
                 _user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx, err_resp = _tab_ctx(db, tenant_id, instance_id)
    if err_resp:
        return err_resp
    try:
        vnic_full = instance_service._get_primary_vnic_full(
            ctx["network"], ctx["compute"], instance_id, ctx["inst"].compartment_id)
        return ok(instance_tabs_service.get_security_tab(ctx["network"], vnic_full))
    except Exception:
        log.exception("安全 Tab 查询异常")
        return err(3100, "查询失败", status=500)


@router.get("/{instance_id}/tabs/management", summary="管理 Tab：维护事件")
def tab_management(instance_id: str, tenant_id: int = Query(description="租户 ID（必填）"),
                   _user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx, err_resp = _tab_ctx(db, tenant_id, instance_id)
    if err_resp:
        return err_resp
    try:
        return ok(instance_tabs_service.get_management_tab(
            ctx["compute"], ctx["inst"].compartment_id, instance_id))
    except Exception:
        log.exception("管理 Tab 查询异常")
        return err(3100, "查询失败", status=500)


@router.get("/{instance_id}/tabs/agent-plugins", summary="管理 Tab：Cloud Agent 插件")
def tab_agent_plugins(instance_id: str, tenant_id: int = Query(description="租户 ID（必填）"),
                      _user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx, err_resp = _tab_ctx(db, tenant_id, instance_id)
    if err_resp:
        return err_resp
    try:
        return ok(instance_tabs_service.get_agent_plugins(
            ctx["tenant"], ctx["inst"].compartment_id, instance_id))
    except Exception:
        log.exception("Agent 插件查询异常")
        return err(3100, "查询失败", status=500)


@router.get("/{instance_id}/tabs/work-requests", summary="工作请求 Tab")
def tab_work_requests(instance_id: str, tenant_id: int = Query(description="租户 ID（必填）"),
                      _user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx, err_resp = _tab_ctx(db, tenant_id, instance_id)
    if err_resp:
        return err_resp
    try:
        return ok(instance_tabs_service.get_work_requests(
            ctx["tenant"], ctx["inst"].compartment_id, instance_id))
    except Exception:
        log.exception("工作请求查询异常")
        return err(3100, "查询失败", status=500)


@router.get("/{instance_id}/tabs/metrics", summary="监视 Tab：CPU/内存/磁盘/网络指标")
def tab_metrics(instance_id: str, tenant_id: int = Query(description="租户 ID（必填）"),
                hours: int = Query(default=6, ge=1, le=72, description="回看小时数"),
                _user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx, err_resp = _tab_ctx(db, tenant_id, instance_id)
    if err_resp:
        return err_resp
    try:
        return ok(instance_tabs_service.get_instance_metrics(ctx["tenant"], instance_id, hours))
    except Exception:
        log.exception("监视 Tab 查询异常")
        return err(3100, "查询失败", status=500)


@router.post("/{instance_id}/console-history/capture", summary="截取控制台历史")
def capture_console_history(instance_id: str, body: TenantIdIn,
                            _user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx, err_resp = _tab_ctx(db, body.tenant_id, instance_id)
    if err_resp:
        return err_resp
    try:
        return ok(instance_tabs_service.capture_console_history(ctx["compute"], instance_id))
    except OciApiError as exc:
        return _handle_oci(exc)
    except Exception:
        log.exception("截取控制台历史异常")
        return err(3100, "截取失败", status=500)


@router.get("/{instance_id}/console-history/{history_id}/content", summary="获取控制台历史内容")
def get_console_history_content(instance_id: str, history_id: str,
                                tenant_id: int = Query(description="租户 ID（必填）"),
                                _user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx, err_resp = _tab_ctx(db, tenant_id, instance_id)
    if err_resp:
        return err_resp
    try:
        return ok(instance_tabs_service.get_console_history_content(ctx["compute"], history_id))
    except OciApiError as exc:
        return _handle_oci(exc)
    except Exception:
        log.exception("获取控制台历史内容异常")
        return err(3100, "获取失败", status=500)


# ============================================================ 实例操作扩展
class CustomImageIn(BaseModel):
    tenant_id: int
    display_name: str


@router.post("/{instance_id}/custom-image", summary="创建定制映像（实例需关机）")
def create_custom_image(instance_id: str, body: CustomImageIn,
                        user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..core.audit import write_log
    ctx, err_resp = _tab_ctx(db, body.tenant_id, instance_id)
    if err_resp:
        return err_resp
    try:
        result = instance_tabs_service.create_custom_image(
            ctx["compute"], ctx["inst"].compartment_id, instance_id, body.display_name)
        write_log(db, user.id, "instance.custom_image", f"实例 {instance_id} 创建定制映像 {body.display_name}")
        return ok(result)
    except OciApiError as exc:
        return _handle_oci(exc)
    except Exception:
        log.exception("创建定制映像异常")
        return err(3100, "创建失败", status=500)


class ChangeCompartmentIn(BaseModel):
    tenant_id: int
    compartment_id: str


@router.post("/{instance_id}/change-compartment", summary="移动实例到其他 compartment")
def change_compartment(instance_id: str, body: ChangeCompartmentIn,
                       user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..core.audit import write_log
    ctx, err_resp = _tab_ctx(db, body.tenant_id, instance_id)
    if err_resp:
        return err_resp
    try:
        result = instance_tabs_service.change_instance_compartment(
            ctx["compute"], instance_id, body.compartment_id)
        write_log(db, user.id, "instance.change_compartment", f"实例 {instance_id} 移动到 {body.compartment_id}")
        return ok(result)
    except OciApiError as exc:
        return _handle_oci(exc)
    except Exception:
        log.exception("移动实例异常")
        return err(3100, "移动失败", status=500)


class DiagnosticIn(BaseModel):
    tenant_id: int
    action: str  # SENDDIAGNOSTICINTERRUPT | DIAGNOSTICREBOOT


@router.post("/{instance_id}/diagnostic", summary="诊断操作：发送诊断中断 / 诊断重启")
def diagnostic(instance_id: str, body: DiagnosticIn,
               user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..core.audit import write_log
    ctx, err_resp = _tab_ctx(db, body.tenant_id, instance_id)
    if err_resp:
        return err_resp
    try:
        result = instance_tabs_service.diagnostic_action(ctx["compute"], instance_id, body.action)
        write_log(db, user.id, "instance.diagnostic", f"实例 {instance_id} 诊断操作 {body.action}")
        return ok(result)
    except OciApiError as exc:
        return _handle_oci(exc)
    except Exception:
        log.exception("诊断操作异常")
        return err(3100, "操作失败", status=500)


class RunCommandIn(BaseModel):
    tenant_id: int
    content: str  # shell 脚本内容
    display_name: str = ""


@router.post("/{instance_id}/run-command", summary="在实例上运行命令（需 Cloud Agent）")
def run_command(instance_id: str, body: RunCommandIn,
                user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..core.audit import write_log
    ctx, err_resp = _tab_ctx(db, body.tenant_id, instance_id)
    if err_resp:
        return err_resp
    try:
        result = instance_tabs_service.run_instance_command(
            ctx["tenant"], ctx["inst"].compartment_id, instance_id, body.content, body.display_name)
        write_log(db, user.id, "instance.run_command", f"实例 {instance_id} 运行命令 {result.get('id')}")
        return ok(result)
    except OciApiError as exc:
        return _handle_oci(exc)
    except Exception:
        log.exception("运行实例命令异常")
        return err(3100, "执行失败", status=500)


@router.get("/{instance_id}/run-command/{command_id}", summary="查询实例命令执行结果")
def get_run_command(instance_id: str, command_id: str,
                    tenant_id: int = Query(description="租户 ID（必填）"),
                    _user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    ctx, err_resp = _tab_ctx(db, tenant_id, instance_id)
    if err_resp:
        return err_resp
    try:
        return ok(instance_tabs_service.get_command_execution(ctx["tenant"], command_id))
    except OciApiError as exc:
        return _handle_oci(exc)
    except Exception:
        log.exception("查询命令执行结果异常")
        return err(3100, "查询失败", status=500)
