"""一键更新服务：检查更新 + 上传更新包应用。

检查更新：对比本地版本与更新源（GitHub Releases API 格式，可配置）。
应用更新：上传 oci-panel.zip（与交付包同结构）-> 校验 -> 备份 -> 解压覆盖
  后端代码（保护 .env / data / *.db）-> 依赖变化时重装 -> 进程自杀重启
  （docker restart: unless-stopped 会拉起新代码；裸机需手动重启）。

前端 dist 在构建时 baked，无法热更：若更新包含前端变更，返回
frontend_changed=True，前端提示用户执行 docker compose up --build -d。
"""
import io
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import zipfile

import httpx

from ..db import models
from ..db.session import SessionLocal

log = logging.getLogger(__name__)

APP_VERSION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION"
)
FEED_KEY = "update_feed_url"

# ---- GitHub 更新配置 ----
GH_REPO_KEY = "update_github_repo"        # 形如 owner/repo
GH_BRANCH_KEY = "update_github_branch"   # 默认 main
GH_TOKEN_KEY = "update_github_token"     # 私有仓库用的 Token（加密存储，可选）
GH_SHA_KEY = "update_github_last_sha"    # 上次从 GitHub 应用的 commit sha
GH_API = "https://api.github.com"
GH_RAW = "https://raw.githubusercontent.com"


def get_current_version() -> str:
    try:
        with open(APP_VERSION_FILE, encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except Exception:
        return "0.0.0"


def get_feed_url() -> str:
    db = SessionLocal()
    try:
        row = db.get(models.SystemSetting, FEED_KEY)
        return (row.value if row and row.value else "").strip()
    finally:
        db.close()


def set_feed_url(url: str) -> str:
    db = SessionLocal()
    try:
        row = db.get(models.SystemSetting, FEED_KEY)
        if row is None:
            db.add(models.SystemSetting(key=FEED_KEY, value=url.strip(), is_secret=False))
        else:
            row.value = url.strip()
        db.commit()
        return url.strip()
    finally:
        db.close()


def check_update() -> dict:
    """检查更新。返回 {current_version, feed_url, latest_version, has_update, notes, download_url}。"""
    current = get_current_version()
    feed = get_feed_url()
    result = {
        "current_version": current, "feed_url": feed,
        "latest_version": None, "has_update": False, "notes": "", "download_url": None,
    }
    if not feed:
        result["notes"] = "未配置更新源"
        return result
    try:
        resp = httpx.get(feed, timeout=20, headers={"Accept": "application/vnd.github+json"})
        data = resp.json()
        # 兼容 GitHub releases API（单个 latest 或数组取第一条）
        rel = data if isinstance(data, dict) else (data[0] if data else {})
        latest = str(rel.get("tag_name") or rel.get("version") or "").lstrip("v")
        result["latest_version"] = latest or None
        assets = rel.get("assets") or []
        dl = next((a.get("browser_download_url") for a in assets if a.get("browser_download_url")), None)
        result["download_url"] = dl
        result["notes"] = str(rel.get("body") or "")[:500]
        result["has_update"] = bool(latest) and _ver_gt(latest, current)
    except Exception as exc:
        result["notes"] = f"检查失败：{str(exc)[:150]}"
    return result


def _ver_gt(a: str, b: str) -> bool:
    def parts(v: str):
        out = []
        for p in v.split("."):
            try:
                out.append(int("".join(c for c in p if c.isdigit()) or 0))
            except Exception:
                out.append(0)
        return out

    return parts(a) > parts(b)


# ============ 从 GitHub 更新 ============

def _parse_repo(repo: str) -> tuple[str, str]:
    repo = (repo or "").strip().strip("/")
    # 兼容粘贴完整 URL：https://github.com/owner/repo(.git)
    if "github.com/" in repo:
        repo = repo.split("github.com/", 1)[1]
    repo = repo[:-4] if repo.endswith(".git") else repo
    parts = [p for p in repo.split("/") if p]
    if len(parts) != 2 or not all(parts):
        raise ValueError("仓库地址格式应为 owner/repo（可粘贴 GitHub 仓库 URL）")
    return parts[0], parts[1]


def _gh_headers(token: str = "") -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "oci-panel"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get_fernet():
    # 复用 cloudflare_service 的密钥体系（同一 FERNET_KEY）
    from .cloudflare_service import _get_fernet as _cf_fernet

    return _cf_fernet()


def _get_setting(key: str, default: str = "") -> str:
    db = SessionLocal()
    try:
        row = db.get(models.SystemSetting, key)
        return (row.value if row and row.value else default)
    finally:
        db.close()


def _set_setting(key: str, value: str, secret: bool = False) -> None:
    db = SessionLocal()
    try:
        store = _get_fernet().encrypt(value.encode()).decode() if secret and value else value
        row = db.get(models.SystemSetting, key)
        if row is None:
            db.add(models.SystemSetting(key=key, value=store, is_secret=secret))
        else:
            row.value = store
            row.is_secret = secret
        db.commit()
    finally:
        db.close()


def _get_gh_token() -> str:
    cipher = _get_setting(GH_TOKEN_KEY)
    if not cipher:
        return ""
    try:
        return _get_fernet().decrypt(cipher.encode()).decode()
    except Exception:
        log.warning("GitHub Token 解密失败，可能 FERNET_KEY 已更换")
        return ""


def get_github_config() -> dict:
    return {
        "repo": _get_setting(GH_REPO_KEY),
        "branch": _get_setting(GH_BRANCH_KEY, "main"),
        "has_token": bool(_get_setting(GH_TOKEN_KEY)),
        "last_applied_sha": _get_setting(GH_SHA_KEY),
    }


def set_github_config(repo: str, branch: str, token: str = "", clear_token: bool = False) -> dict:
    """保存 GitHub 更新配置。token 传空字符串表示不改动；clear_token=True 则清除。"""
    owner, name = _parse_repo(repo)
    branch = (branch or "main").strip() or "main"
    _set_setting(GH_REPO_KEY, f"{owner}/{name}")
    _set_setting(GH_BRANCH_KEY, branch)
    if clear_token:
        _set_setting(GH_TOKEN_KEY, "", secret=True)
    elif token:
        _set_setting(GH_TOKEN_KEY, token.strip(), secret=True)
    return get_github_config()


def _gh_branch_info(owner: str, name: str, branch: str, token: str) -> dict:
    """取分支最新提交信息。失败抛 ValueError（带中文说明）。"""
    url = f"{GH_API}/repos/{owner}/{name}/branches/{branch}"
    try:
        resp = httpx.get(url, headers=_gh_headers(token), timeout=20, follow_redirects=True)
    except Exception as exc:
        raise ValueError(f"连接 GitHub 失败：{str(exc)[:120]}")
    if resp.status_code == 404:
        raise ValueError("仓库或分支不存在（私有仓库请填写有读取权限的 Token）")
    if resp.status_code in (401, 403):
        remain = resp.headers.get("x-ratelimit-remaining")
        if resp.status_code == 403 and remain == "0":
            raise ValueError("GitHub API 限流（匿名每小时 60 次），请稍后再试或填写 Token")
        raise ValueError("GitHub 认证失败：Token 无效或无权访问该仓库")
    if resp.status_code != 200:
        raise ValueError(f"GitHub 返回异常状态码 {resp.status_code}")
    data = resp.json()
    commit = data.get("commit") or {}
    info = commit.get("commit") or {}
    return {
        "sha": commit.get("sha") or "",
        "date": (info.get("author") or {}).get("date") or "",
        "message": (info.get("message") or "").strip()[:300],
    }


def _gh_remote_version(owner: str, name: str, branch: str, token: str) -> str:
    """从仓库读取 backend/app/VERSION。读不到返回空字符串。"""
    url = f"{GH_RAW}/{owner}/{name}/{branch}/backend/app/VERSION"
    try:
        resp = httpx.get(url, headers=_gh_headers(token), timeout=20, follow_redirects=True)
        if resp.status_code == 200:
            return resp.text.strip().split()[0][:32]
    except Exception:
        pass
    return ""


def github_check() -> dict:
    """检查 GitHub 仓库是否有新提交。"""
    cfg = get_github_config()
    result = {
        "current_version": get_current_version(),
        "repo": cfg["repo"], "branch": cfg["branch"],
        "has_token": cfg["has_token"],
        "last_applied_sha": cfg["last_applied_sha"],
        "latest_sha": "", "latest_date": "", "latest_message": "",
        "remote_version": "", "has_update": False, "notes": "",
    }
    if not cfg["repo"]:
        result["notes"] = "未配置 GitHub 仓库地址"
        return result
    try:
        owner, name = _parse_repo(cfg["repo"])
    except ValueError as exc:
        result["notes"] = str(exc)
        return result
    token = _get_gh_token()
    try:
        info = _gh_branch_info(owner, name, cfg["branch"], token)
    except ValueError as exc:
        result["notes"] = str(exc)
        return result
    result.update({
        "latest_sha": info["sha"][:12],
        "latest_date": info["date"],
        "latest_message": info["message"],
    })
    remote_ver = _gh_remote_version(owner, name, cfg["branch"], token)
    result["remote_version"] = remote_ver
    last = cfg["last_applied_sha"]
    if last:
        result["has_update"] = bool(info["sha"]) and info["sha"] != last
        if not result["has_update"]:
            result["notes"] = "已是该分支最新提交"
    elif remote_ver:
        result["has_update"] = _ver_gt(remote_ver, result["current_version"])
        if not result["has_update"]:
            result["notes"] = f"远端版本 v{remote_ver}，本地 v{result['current_version']}"
    else:
        result["notes"] = "无法读取远端 VERSION，先应用一次后将按提交跟踪"
        result["has_update"] = True
    return result


def github_apply() -> dict:
    """从 GitHub 下载分支 zip 包并应用更新，成功后记录 commit sha。"""
    cfg = get_github_config()
    if not cfg["repo"]:
        raise ValueError("未配置 GitHub 仓库地址")
    owner, name = _parse_repo(cfg["repo"])
    branch = cfg["branch"]
    token = _get_gh_token()
    info = _gh_branch_info(owner, name, branch, token)  # 先拿 sha，失败直接抛
    url = f"{GH_API}/repos/{owner}/{name}/zipball/{branch}"
    try:
        resp = httpx.get(url, headers=_gh_headers(token), timeout=180, follow_redirects=True)
    except Exception as exc:
        raise ValueError(f"下载更新包失败：{str(exc)[:150]}")
    if resp.status_code != 200 or not resp.content.startswith(b"PK"):
        raise ValueError(f"下载更新包失败：GitHub 返回 {resp.status_code}")
    result = apply_update(resp.content)
    if info["sha"]:
        _set_setting(GH_SHA_KEY, info["sha"])
    result["github"] = {
        "repo": f"{owner}/{name}", "branch": branch,
        "sha": info["sha"][:12], "message": info["message"],
    }
    return result


def _app_root() -> str:
    """后端代码根目录（包含 app/ 的那层）：docker 内为 /app。"""
    import app as _app_pkg

    return os.path.dirname(os.path.dirname(os.path.abspath(_app_pkg.__file__)))


def apply_update(zip_bytes: bytes, max_bytes: int = 200 * 1024 * 1024) -> dict:
    """应用更新包。返回 {applied, backend_changed, frontend_changed, backup_dir, notes}。"""
    if not zip_bytes or len(zip_bytes) > max_bytes:
        raise ValueError("更新包为空或超过大小上限")
    tmp = tempfile.mkdtemp(prefix="oci-update-")
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        # 校验包结构：必须包含 backend/app/main.py（与交付包同构）
        names = zf.namelist()
        if not any(n == "backend/app/main.py" or n.endswith("/backend/app/main.py") for n in names):
            raise ValueError("更新包结构不正确：未找到 backend/app/main.py")
        zf.extractall(tmp)
        # 处理可能的多余顶层目录（如 zip 根下直接是文件或包了一层目录）
        root = tmp
        entries = os.listdir(tmp)
        if len(entries) == 1 and os.path.isdir(os.path.join(tmp, entries[0])):
            maybe = os.path.join(tmp, entries[0])
            if os.path.isdir(os.path.join(maybe, "backend")):
                root = maybe
        backend_src = os.path.join(root, "backend")
        frontend_src = os.path.join(root, "frontend", "src")
        if not os.path.isdir(os.path.join(backend_src, "app")):
            raise ValueError("更新包中 backend/app 缺失")

        app_root = _app_root()
        ts = time.strftime("%Y%m%d-%H%M%S")
        data_dir = os.path.join(app_root, "data")
        backup_dir = os.path.join(data_dir, "update_backups", ts)
        os.makedirs(backup_dir, exist_ok=True)

        # 备份当前后端 app/
        cur_app = os.path.join(app_root, "app")
        if os.path.isdir(cur_app):
            shutil.copytree(cur_app, os.path.join(backup_dir, "app"))

        # 覆盖后端代码（排除 data/.env/*.db/__pycache__）
        backend_changed, frontend_changed = False, False
        for dirpath, dirnames, filenames in os.walk(backend_src):
            dirnames[:] = [d for d in dirnames
                           if d not in ("__pycache__", ".venv", "node_modules", "dist", "data")]
            rel = os.path.relpath(dirpath, backend_src)
            dst_dir = os.path.join(app_root, rel) if rel != "." else app_root
            os.makedirs(dst_dir, exist_ok=True)
            for fn in filenames:
                if fn == ".env" or fn.endswith((".db", ".db-journal", ".log")):
                    continue
                src_f = os.path.join(dirpath, fn)
                dst_f = os.path.join(dst_dir, fn)
                if not os.path.exists(dst_f) or _file_changed(src_f, dst_f):
                    shutil.copy2(src_f, dst_f)
                    backend_changed = True

        # 前端是否有变更（仅检测，不应用：dist 需重新构建）
        cur_fe = os.path.join(app_root, "..", "frontend", "src")
        if os.path.isdir(frontend_src):
            for dirpath, dirnames, filenames in os.walk(frontend_src):
                dirnames[:] = [d for d in dirnames if d != "node_modules"]
                for fn in filenames:
                    if not fn.endswith((".ts", ".tsx", ".css")):
                        continue
                    # 与仓库内前端对比（docker 内无 frontend 源码则视为变更）
                    if not os.path.isdir(cur_fe):
                        frontend_changed = True
                        break
                if frontend_changed:
                    break

        # 依赖变化则重装（pyproject.toml 变更时）
        notes = []
        new_pyproject = os.path.join(backend_src, "pyproject.toml")
        if os.path.exists(new_pyproject):
            try:
                with open(new_pyproject, "rb") as f:
                    new_pp = f.read()
                cur_pp = os.path.join(app_root, "pyproject.toml")
                old_pp = b""
                if os.path.exists(cur_pp):
                    with open(cur_pp, "rb") as f:
                        old_pp = f.read()
                if new_pp != old_pp:
                    shutil.copy2(new_pyproject, cur_pp)
                    log.info("依赖描述变更，开始重装依赖…")
                    subprocess.run(
                        ["pip", "install", "--no-cache-dir", "."],
                        cwd=app_root, timeout=600, check=False,
                    )
                    notes.append("依赖已重装")
            except Exception as exc:
                notes.append(f"依赖重装失败（可手动 pip install .）：{exc}")

        _schedule_restart()
        return {
            "applied": True,
            "backend_changed": backend_changed,
            "frontend_changed": frontend_changed,
            "backup_dir": backup_dir,
            "notes": "；".join(notes) if notes else "",
            "restart": "服务将在 3 秒后重启以加载新代码（docker 会自动拉起；裸机部署请手动重启）",
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _file_changed(a: str, b: str) -> bool:
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return True
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() != fb.read()
    except Exception:
        return True


def _schedule_restart(delay: int = 3):
    def _kill():
        time.sleep(delay)
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception:
            pass

    threading.Thread(target=_kill, daemon=True).start()
