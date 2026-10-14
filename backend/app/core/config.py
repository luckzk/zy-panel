"""应用配置：通过环境变量 / .env 文件注入（pydantic-settings）。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "oci-panel"
    debug: bool = False

    # --- JWT ---
    # 生产环境务必通过环境变量 SECRET_KEY 覆盖默认值
    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12

    # --- 租户私钥加密（Fernet 对称加密） ---
    # 生产环境务必设置 FERNET_KEY；生成方式见 README
    fernet_key: str | None = None

    # --- 数据库 ---
    database_url: str = "sqlite:///./data/oci-panel.db"

    # --- CORS ---
    cors_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
