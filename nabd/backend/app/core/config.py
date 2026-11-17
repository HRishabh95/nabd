"""Settings. Values come from the environment or nabd/.env; no secrets are committed."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]  # .../nabd


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NABD_", env_file=ROOT / ".env", extra="ignore")

    data_dir: Path = ROOT / "data"
    # LLM provider: "codex" (ChatGPT sign-in via the Codex CLI; demo only, prompts go to OpenAI),
    # "azure_openai" (UAE North) or "local" (on-premise open-weight model). Only codex is wired in phase 0.
    llm_provider: str = "codex"
    codex_bin: str = "codex"
    codex_home: str | None = None
    codex_model: str | None = None
    llm_timeout_seconds: int = 180
    heartbeat_seconds: float = 15.0
    fred_api_key: str | None = None
    # SEC asks for a requester name and contact email; Nabd never fills this in for you.
    sec_user_agent: str | None = None
    refresh_enabled: bool = True
    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "nabd.sqlite"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s
