from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_prefix="FINSONA_", extra="ignore")

    database_url: str = f"sqlite:///{(BACKEND_DIR / 'finsona.db').as_posix()}"
    storage_dir: Path = BACKEND_DIR / "storage"
    data_dir: Path = REPO_DIR / "data"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Feature flags (E0-06). AI calls fall back to cached responses when live is off.
    use_live_ocr: bool = False
    use_live_llm: bool = False
    llm_provider: str = "anthropic"  # the gateway's only live adapter today
    llm_model: str = "claude-opus-5"
    llm_timeout_s: float = 30.0
    connector_mode: str = "sandbox"  # "sandbox" or "live"


settings = Settings()
