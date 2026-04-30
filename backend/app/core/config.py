from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[3]
BACKEND_DIR = ROOT_DIR / "backend"


class Settings(BaseSettings):
    """应用配置，所有可变参数都从环境变量读取。"""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TripSage Agent API"
    app_version: str = "0.1.0"
    app_env: str = "development"
    app_debug: bool = True
    demo_mode: bool = False
    auth_secret_key: str = "tripsage-dev-auth-secret"
    auth_access_token_minutes: int = 30
    auth_refresh_token_days: int = 14

    database_url: str = f"sqlite:///{ROOT_DIR / 'data' / 'tripsage.db'}"
    chroma_persist_dir: str = str(ROOT_DIR / "data" / "chroma")

    llm_provider: str = "openai_compatible"
    llm_model: str = "deepseek-v4-flash"
    llm_api_key: str = ""
    llm_base_url: str = ""

    embedding_provider: str = "openai_compatible"
    embedding_model: str = ""
    embedding_api_key: str = ""
    embedding_base_url: str = ""

    amap_api_key: str = ""

    mcp_12306_enabled: bool = True
    mcp_12306_config_path: str = str(ROOT_DIR / "mcp_servers.json")
    mcp_12306_server_name: str = "12306"
    mcp_12306_allow_live: bool = False
    mcp_12306_timeout_seconds: float = 20.0

    web_search_enabled: bool = False
    web_search_provider: str = "disabled"
    web_search_api_key: str = ""
    web_search_timeout_seconds: float = 10.0
    web_search_cache_ttl_minutes: int = 60
    web_search_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    )

    auto_seed_guides: bool = True
    auto_rebuild_vector_index: bool = True
    auto_crawl_weibo_on_startup: bool = False

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )

    request_timeout_seconds: float = 12.0

    llm_timeout_seconds: float = 60.0
    llm_max_tokens: int = 1600


def public_url(value: str) -> str:
    """返回可展示的服务地址，避免把空字符串散落到诊断接口。"""
    return value.rstrip("/") if value else ""


@lru_cache
def get_settings() -> Settings:
    """缓存配置对象，避免在每次请求中重复读取环境变量。"""
    return Settings()


settings = get_settings()
