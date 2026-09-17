from dataclasses import dataclass
import os
from pathlib import Path


def normalize_qwen_base_url(base_url: str) -> str:
    """Normalize a Qwen OpenAI-compatible base URL from .env."""
    value = base_url.strip().rstrip("/")
    if "://" not in value:
        value = f"https://{value}"
    if not value.endswith("/compatible-mode/v1"):
        value = f"{value}/compatible-mode/v1"
    return value


@dataclass(frozen=True)
class Settings:
    workspace: Path
    max_file_bytes: int = 200_000
    agent_timeout_seconds: float = 120.0
    allowed_browser_domains: tuple[str, ...] = ()
    browser_timeout_ms: int = 30_000
    model_name: str = "qwen3.7-plus"
    api_key: str | None = None
    base_url: str = "https://ws-0d9k5ksti6cnsfmd.cn-hongkong.maas.aliyuncs.com/compatible-mode/v1"
    database_path: Path = Path("./data/macpilot.sqlite3")
    read_only: bool = True
    context_max_tokens: int = 12_000
    cache_enabled: bool = True
    cache_ttl_seconds: float = 86_400.0

    @classmethod
    def from_env(cls) -> "Settings":
        workspace = Path(os.getenv("MACPILOT_WORKSPACE", "./data/workspace"))
        max_file_bytes = int(os.getenv("MACPILOT_MAX_FILE_BYTES", "200000"))
        agent_timeout_seconds = float(
            os.getenv("MACPILOT_AGENT_TIMEOUT_SECONDS", "120")
        )
        allowed_browser_domains = tuple(
            domain.strip().lower().lstrip(".")
            for domain in os.getenv("MACPILOT_ALLOWED_BROWSER_DOMAINS", "").split(",")
            if domain.strip()
        )
        browser_timeout_ms = int(os.getenv("MACPILOT_BROWSER_TIMEOUT_MS", "30000"))
        model_name = os.getenv("QWEN_MODEL", "qwen3.7-plus")
        api_key = os.getenv("DASHSCOPE_API_KEY")
        workspace_id = os.getenv("QWEN_WORKSPACE_ID")
        region = os.getenv("QWEN_REGION", "cn-beijing")
        if workspace_id:
            base_url = (
                f"https://{workspace_id}.{region}.maas.aliyuncs.com/"
                "compatible-mode/v1"
            )
        else:
            base_url = os.getenv(
                "QWEN_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
        base_url = normalize_qwen_base_url(base_url)
        database_path = Path(
            os.getenv("MACPILOT_DB_PATH", "./data/macpilot.sqlite3")
        )
        read_only = os.getenv("MACPILOT_READ_ONLY", "true").lower() not in {
            "0",
            "false",
            "no",
        }
        cache_enabled = os.getenv("MACPILOT_CACHE_ENABLED", "true").lower() not in {
            "0",
            "false",
            "no",
        }
        return cls(
            workspace=workspace,
            max_file_bytes=max_file_bytes,
            agent_timeout_seconds=agent_timeout_seconds,
            allowed_browser_domains=allowed_browser_domains,
            browser_timeout_ms=browser_timeout_ms,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            database_path=database_path,
            read_only=read_only,
            context_max_tokens=int(os.getenv("MACPILOT_CONTEXT_MAX_TOKENS", "12000")),
            cache_enabled=cache_enabled,
            cache_ttl_seconds=float(os.getenv("MACPILOT_CACHE_TTL_SECONDS", "86400")),
        )
