"""租户路由：OCI 租户配置的 CRUD + 连通性测试。

私钥 PEM 以明文传入、经 Fernet 加密后入库，读取接口永不返回私钥。
连通性测试走真实 OCI 调用：identity.list_availability_domains。
"""
import logging

from fastapi import APIRouter, Depends
from oci.exceptions import ConnectTimeout, RequestException, ServiceError
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.audit import write_log
from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services.oci_factory import encrypt_private_key, get_identity_client, invalidate_tenant_cache

router = APIRouter(prefix="/tenants", tags=["租户配置"])

log = logging.getLogger(__name__)


class TenantCreate(BaseModel):
    name: str
    provider: str = "oci"  # oci / aliyun
    # OCI 字段（provider=oci 时用）
    tenancy_ocid: str = ""
    user_ocid: str = ""
    fingerprint: str = ""
    region: str = "ap-tokyo-1"
    private_key: str = ""  # PEM 明文，仅写入时传入
    # 阿里云字段（provider=aliyun 时用）
    access_key_id: str = ""
    access_key_secret: str = ""  # 明文，仅写入时传入
    aliyun_region: str = "cn-hangzhou"
    proxy: str | None = None
    account_type: str = ""  # free / paid，手动标记（OCI 无 API 可查）


class TenantUpdate(BaseModel):
    name: str | None = None
    tenancy_ocid: str | None = None
    user_ocid: str | None = None
    fingerprint: str | None = None
    region: str | None = None
    private_key: str | None = None  # 传入则更新加密私钥
    access_key_id: str | None = None      # 阿里云：传入则更新
    access_key_secret: str | None = None  # 阿里云：传入则更新
    aliyun_region: str | None = None      # 阿里云：传入则更新
    proxy: str | None = None
    account_type: str | None = None


def _to_out(t: models.Tenant) -> dict:
    out = {
        "id": t.id,
        "name": t.name,
        "provider": getattr(t, "provider", None) or "oci",
        "tenancy_ocid": t.tenancy_ocid,
        "user_ocid": t.user_ocid,
        "fingerprint": t.fingerprint,
        "region": t.region,
        "proxy": t.proxy,
        "account_type": getattr(t, "account_type", "") or "",
        "test_status": getattr(t, "test_status", "") or "",
        "last_tested_at": t.last_tested_at.isoformat() if getattr(t, "last_tested_at", None) else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }
    # 阿里云：返回脱敏后的 AccessKey ID 供列表展示（Secret 永不返回）
    if (getattr(t, "provider", None) or "") == "aliyun" and getattr(t, "credentials_enc", None):
        try:
            from ..providers import decrypt_credentials

            ak = (decrypt_credentials(t.credentials_enc) or {}).get("access_key_id", "")
            out["access_key_id_masked"] = (ak[:4] + "****" + ak[-4:]) if len(ak) > 8 else ("****" if ak else "")
        except Exception:
            out["access_key_id_masked"] = ""
    return out


@router.get("/providers", summary="已注册云厂商列表")
def list_providers(_user: models.User = Depends(get_current_user)):
    from ..providers import list_providers as _lp
    return ok(_lp())


@router.get("/{tenant_id}/regions", summary="地域列表（按云厂商分发，实时）")
def tenant_regions(
    tenant_id: int,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    from ..providers import get_provider
    from ..providers.base import ProviderError
    tenant = db.get(models.Tenant, tenant_id)
    if tenant is None:
        return err(2001, "租户不存在", status=404)
    try:
        provider = get_provider(tenant)
        return ok([r.to_dict() for r in provider.list_regions()])
    except ProviderError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("地域列表查询异常 tenant_id=%s", tenant_id)
        return err(3100, f"查询失败：{str(exc)[:200]}", status=500)


@router.get("", summary="租户列表")
def list_tenants(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    tenants = db.query(models.Tenant).order_by(models.Tenant.id).all()
    return ok([_to_out(t) for t in tenants])


@router.post("", summary="新增租户（云账号）")
def create_tenant(
    body: TenantCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    from ..providers import encrypt_credentials, get_provider_class
    if body.provider not in ("oci", "aliyun") or get_provider_class(body.provider) is None:
        return err(2002, f"不支持的云厂商：{body.provider}", status=400)
    if body.provider == "aliyun":
        if not body.access_key_id or not body.access_key_secret:
            return err(2002, "阿里云 AccessKey ID / Secret 不能为空", status=400)
        creds = {
            "access_key_id": body.access_key_id.strip(),
            "access_key_secret": body.access_key_secret.strip(),
            "region_id": (body.aliyun_region or "cn-hangzhou").strip(),
        }
        tenant = models.Tenant(
            name=body.name,
            provider="aliyun",
            credentials_enc=encrypt_credentials(creds),
            # 兼容老字段：填占位，实际走 credentials_enc
            tenancy_ocid="", user_ocid="", fingerprint="",
            region=creds["region_id"],
            private_key_ciphertext="",
            proxy=body.proxy,
            account_type=body.account_type or "",
        )
    else:
        if not all([body.tenancy_ocid, body.user_ocid, body.fingerprint, body.private_key]):
            return err(2002, "OCI 租户信息不完整", status=400)
        creds = {
            "tenancy_ocid": body.tenancy_ocid.strip(),
            "user_ocid": body.user_ocid.strip(),
            "fingerprint": body.fingerprint.strip(),
            "private_key": body.private_key,
            "region": (body.region or "ap-tokyo-1").strip(),
        }
        tenant = models.Tenant(
            name=body.name,
            provider="oci",
            credentials_enc=encrypt_credentials(creds),
            tenancy_ocid=creds["tenancy_ocid"],
            user_ocid=creds["user_ocid"],
            fingerprint=creds["fingerprint"],
            region=creds["region"],
            private_key_ciphertext=encrypt_private_key(body.private_key),
            proxy=body.proxy,
            account_type=body.account_type or "",
        )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    write_log(db, user.id, "tenant.create", f"新增云账号 {tenant.name}（{tenant.provider}/{tenant.region}）")
    return ok(_to_out(tenant))


@router.post("/batch", summary="批量新增租户（逐个校验，返回每条结果）")
def batch_create_tenants(
    body: list[TenantCreate],
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if not body:
        return err(2002, "租户列表为空", status=400)
    if len(body) > 50:
        return err(2002, "单次最多批量添加 50 个租户", status=400)
    results = []
    for item in body:
        try:
            # 每条用 savepoint 隔离，单条失败不影响其他
            with db.begin_nested():
                tenant = models.Tenant(
                    name=item.name,
                    tenancy_ocid=item.tenancy_ocid,
                    user_ocid=item.user_ocid,
                    fingerprint=item.fingerprint,
                    region=item.region,
                    private_key_ciphertext=encrypt_private_key(item.private_key),
                    proxy=item.proxy,
                    account_type=item.account_type or "",
                )
                db.add(tenant)
                db.flush()
            results.append({"ok": True, "name": item.name, "id": tenant.id})
            write_log(db, user.id, "tenant.create", f"批量新增租户 {tenant.name}（{tenant.region}）")
        except Exception as exc:
            results.append({"ok": False, "name": item.name, "error": str(exc)[:200]})
    db.commit()
    ok_count = sum(1 for r in results if r["ok"])
    return ok({"total": len(results), "success": ok_count, "failed": len(results) - ok_count, "results": results})


@router.get("/{tenant_id}", summary="租户详情")
def get_tenant(tenant_id: int, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    tenant = db.get(models.Tenant, tenant_id)
    if tenant is None:
        return err(2001, "租户不存在", status=404)
    return ok(_to_out(tenant))


@router.put("/{tenant_id}", summary="更新租户")
def update_tenant(
    tenant_id: int,
    body: TenantUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    tenant = db.get(models.Tenant, tenant_id)
    if tenant is None:
        return err(2001, "租户不存在", status=404)
    data = body.model_dump(exclude_unset=True)
    if "private_key" in data:
        tenant.private_key_ciphertext = encrypt_private_key(data.pop("private_key"))
    # 阿里云凭证更新：合并进 credentials_enc
    aliyun_keys = {k: data.pop(k) for k in ("access_key_id", "access_key_secret", "aliyun_region") if k in data}
    if aliyun_keys:
        from ..providers import decrypt_credentials, encrypt_credentials
        try:
            creds = decrypt_credentials(tenant.credentials_enc) if tenant.credentials_enc else {}
        except Exception:
            creds = {}
        if aliyun_keys.get("access_key_id"):
            creds["access_key_id"] = aliyun_keys["access_key_id"].strip()
        if aliyun_keys.get("access_key_secret"):
            creds["access_key_secret"] = aliyun_keys["access_key_secret"].strip()
        if aliyun_keys.get("aliyun_region"):
            creds["region_id"] = aliyun_keys["aliyun_region"].strip()
            tenant.region = creds["region_id"]
        tenant.credentials_enc = encrypt_credentials(creds)
    for key, value in data.items():
        setattr(tenant, key, value)
    db.commit()
    invalidate_tenant_cache(tenant_id)  # 配置变更，失效缓存的 OCI client
    write_log(db, user.id, "tenant.update", f"更新租户 {tenant.name}")
    return ok(_to_out(tenant))


@router.delete("/{tenant_id}", summary="删除租户")
def delete_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    tenant = db.get(models.Tenant, tenant_id)
    if tenant is None:
        return err(2001, "租户不存在", status=404)
    db.delete(tenant)
    db.commit()
    invalidate_tenant_cache(tenant_id)
    write_log(db, user.id, "tenant.delete", f"删除租户 {tenant.name}")
    return ok(msg="删除成功")


from ..services import free_tier_service
from ..services import account_detect_service


@router.post("/{tenant_id}/detect-account-type", summary="启发式检测账号类型（免费/付费，仅供参考）")
def detect_account_type(
    tenant_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    tenant = db.get(models.Tenant, tenant_id)
    if tenant is None:
        return err(2001, "租户不存在", status=404)
    try:
        result = account_detect_service.detect_account_type(tenant)
    except Exception as exc:
        log.exception("账号类型检测异常 tenant_id=%s", tenant_id)
        return err(3100, f"检测失败：{str(exc)[:200]}", status=500)
    # 检测结论自动写入（用户仍可手动修改）
    detected = result.get("detected") or ""
    if detected in ("free", "paid"):
        try:
            tenant.account_type = detected
            db.commit()
        except Exception:
            db.rollback()
    write_log(db, user.id, "tenant.detect_account_type", f"检测租户 {tenant.name} 账号类型：{detected}")
    return ok(result)


@router.post("/{tenant_id}/test", summary="连通性测试（按云厂商分发）")
def test_tenant(
    tenant_id: int,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    from datetime import datetime, timezone

    from ..providers import get_provider
    from ..providers.base import ProviderError

    tenant = db.get(models.Tenant, tenant_id)
    if tenant is None:
        return err(2001, "租户不存在", status=404)

    def _mark(ok_: bool):
        # 测试结果持久化，避免刷新页面后丢失
        try:
            tenant.last_tested_at = datetime.now(timezone.utc)
            tenant.test_status = "success" if ok_ else "failed"
            db.commit()
        except Exception:
            db.rollback()

    try:
        provider = get_provider(tenant)
    except ProviderError as exc:
        _mark(False)
        return err(exc.code, f"连通性测试失败：{exc.message}", status=exc.http_status)
    try:
        result = provider.test_connection()
    except ProviderError as exc:
        _mark(False)
        return err(exc.code, f"连通性测试失败：{exc.message}", status=exc.http_status)
    except Exception as exc:  # 兜底：未知异常不抛 500
        _mark(False)
        return err(3103, f"连通性测试失败：{str(exc)[:200]}", status=502)
    _mark(True)
    return ok({"reachable": True, "provider": provider.provider_id,
               "region": tenant.region, "detail": result.get("detail", "")})
