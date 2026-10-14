"""系统路由：操作日志、加密备份导出/恢复、版本信息。"""
import io
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.audit import write_log
from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import tg_ops_bot
from ..services import backup_service

router = APIRouter(prefix="/system", tags=["系统"])

# 恢复上传上限 50MB
RESTORE_MAX_BYTES = 50 * 1024 * 1024


def get_admin_user(user: models.User = Depends(get_current_user)) -> models.User:
    """管理员权限校验（deps 里没有现成的 admin 依赖，这里就地实现）。"""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


@router.get("/logs", summary="操作审计日志")
def get_logs(
    limit: int = Query(default=100, le=1000),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    logs = db.query(models.OperationLog).order_by(models.OperationLog.id.desc()).limit(limit).all()
    return ok(
        [
            {
                "id": l.id,
                "user_id": l.user_id,
                "action": l.action,
                "detail": l.detail,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ]
    )


@router.get("/backup", summary="加密备份导出（文件下载）")
def backup(db: Session = Depends(get_db), user: models.User = Depends(get_admin_user)):
    data = backup_service.export_all(db)
    payload = backup_service.encrypt_payload(data)
    total = sum(len(v) for v in data["tables"].values())
    filename = f"zy-panel-backup-{datetime.now():%Y%m%d-%H%M%S}.bin"
    write_log(db, user.id, "system.backup", f"导出加密备份 {filename}，共 {total} 条记录")
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/restore", summary="备份恢复（上传加密备份文件）")
async def restore(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    raw = await file.read()
    if len(raw) > RESTORE_MAX_BYTES:
        return err(7002, f"备份文件过大（上限 {RESTORE_MAX_BYTES // 1024 // 1024}MB）", status=400)
    if not raw:
        return err(7003, "备份文件为空", status=400)
    try:
        data = backup_service.decrypt_payload(raw)
    except ValueError as exc:
        return err(7001, str(exc), status=400)
    try:
        counts = backup_service.import_all(db, data)
    except ValueError as exc:
        return err(7004, f"备份恢复失败：{exc}", status=400)
    restored = sum(counts.values())
    write_log(db, user.id, "system.restore", f"从备份恢复 {restored} 条记录：{counts}")
    return ok({"restored": True, "counts": counts})


@router.get("/version", summary="版本信息")
def version(_user: models.User = Depends(get_current_user)):
    from ..services import update_service

    return ok({"version": update_service.get_current_version(), "name": "zy-panel-backend"})


class TgBotIn(BaseModel):
    enabled: bool
    chat_ids: str = ""  # 逗号分隔的白名单 chat_id，为空则响应所有


@router.get("/tg-bot", summary="TG 运维机器人配置")
def get_tg_bot(user: models.User = Depends(get_admin_user)):
    return ok(tg_ops_bot.get_ops_config())


@router.post("/tg-bot", summary="更新 TG 运维机器人配置（仅管理员）")
def update_tg_bot(
    body: TgBotIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    cfg = tg_ops_bot.set_ops_config(body.enabled, body.chat_ids)
    # 脱敏返回
    cfg = dict(cfg)
    if cfg.get("token"):
        cfg["token"] = "***"
    write_log(db, user.id, "system.tg_bot", f"更新 TG 运维机器人配置：enabled={body.enabled}")
    return ok(cfg)


class UpdateFeedIn(BaseModel):
    feed_url: str = ""  # GitHub Releases API 地址，留空则禁用检查


@router.get("/update/check", summary="检查更新")
def check_update(_user: models.User = Depends(get_current_user)):
    from ..services import update_service

    return ok(update_service.check_update())


@router.post("/update/feed", summary="配置更新源（仅管理员）")
def set_update_feed(
    body: UpdateFeedIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    from ..services import update_service

    url = update_service.set_feed_url(body.feed_url)
    write_log(db, user.id, "system.update_feed", f"配置更新源：{url or '（清空）'}")
    return ok({"feed_url": url})


@router.post("/update/apply", summary="上传更新包并应用（仅管理员）")
async def apply_update(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    from ..services import update_service

    raw = await file.read()
    try:
        result = update_service.apply_update(raw)
    except ValueError as exc:
        return err(7005, f"更新包校验失败：{exc}", status=400)
    except Exception as exc:
        log.exception("应用更新未知异常")
        return err(7006, f"应用更新失败：{str(exc)[:200]}", status=500)
    write_log(db, user.id, "system.update_apply", f"应用更新包 {file.filename}，备份于 {result['backup_dir']}")
    return ok(result)


class GithubConfigIn(BaseModel):
    repo: str = ""            # owner/repo 或完整 URL
    branch: str = "main"
    token: str = ""           # 为空表示不改动已有 Token
    clear_token: bool = False


@router.get("/update/github/config", summary="GitHub 更新配置")
def get_github_config(_user: models.User = Depends(get_current_user)):
    from ..services import update_service

    return ok(update_service.get_github_config())


@router.post("/update/github/config", summary="保存 GitHub 更新配置（仅管理员）")
def set_github_config(
    body: GithubConfigIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    from ..services import update_service

    try:
        cfg = update_service.set_github_config(body.repo, body.branch, body.token, body.clear_token)
    except ValueError as exc:
        return err(7007, str(exc), status=400)
    write_log(db, user.id, "system.update_github_config", f"配置 GitHub 更新源：{cfg['repo']}@{cfg['branch']}")
    return ok(cfg)


@router.get("/update/github/check", summary="检查 GitHub 仓库更新")
def check_github_update(_user: models.User = Depends(get_current_user)):
    from ..services import update_service

    return ok(update_service.github_check())


@router.post("/update/github/apply", summary="从 GitHub 拉取并应用更新（仅管理员）")
def apply_github_update(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    from ..services import update_service

    try:
        result = update_service.github_apply()
    except ValueError as exc:
        return err(7008, str(exc), status=400)
    except Exception as exc:
        log.exception("从 GitHub 更新未知异常")
        return err(7009, f"从 GitHub 更新失败：{str(exc)[:200]}", status=500)
    gh = result.get("github", {})
    write_log(
        db, user.id, "system.update_github_apply",
        f"从 GitHub {gh.get('repo')}@{gh.get('branch')} 更新至 {gh.get('sha')}，备份于 {result['backup_dir']}",
    )
    return ok(result)


@router.get("/update/frontend/check", summary="检查前端 dist 更新（CI 构建）")
def check_frontend_update(_user: models.User = Depends(get_current_user)):
    from ..services import update_service

    return ok(update_service.frontend_check())


@router.post("/update/frontend/apply", summary="热更前端 dist（仅管理员）")
def apply_frontend_update(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    from ..services import update_service

    try:
        result = update_service.frontend_apply()
    except ValueError as exc:
        return err(7010, str(exc), status=400)
    except Exception as exc:
        log.exception("前端热更新未知异常")
        return err(7011, f"前端热更新失败：{str(exc)[:200]}", status=500)
    write_log(
        db, user.id, "system.update_frontend_apply",
        f"前端热更新至 {result['asset_updated_at']}，{result['files']} 个文件",
    )
    return ok(result)
