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
    azure_di_endpoint: str = ""  # Azure AI Document Intelligence (live OCR)
    azure_di_key: str = ""
    ocr_review_threshold: float = 0.5  # rows with a key field below this go to human review (E2-09)
    use_live_llm: bool = False
    llm_provider: str = "anthropic"  # the gateway's only live adapter today
    llm_model: str = "claude-opus-5"
    llm_timeout_s: float = 30.0
    connector_mode: str = "sandbox"  # "sandbox" or "live"
    # Signing key of the sandbox "source bank" for dStatement (E3-04). Not a secret: sandbox only.
    dstatement_sandbox_key: str = "finsona-dstatement-sandbox"
    storage_key: str = ""  # Fernet key for files at rest; generated into backend/.storage_key when empty
    secret_key: str = ""  # token signing key; generated into backend/.secret when empty
    demo_password: str = "finsona-demo"  # seeded demo accounts only
    demo_mode: bool = True  # show demo accounts on the login screen; set false outside demos
    snapshot_dir: Path = BACKEND_DIR / ".demo_snapshot"  # E16-01 instant reset
    llm_cache_file: Path | None = REPO_DIR / "data" / "llm_cache.json"  # E16-02 offline replay
    frontend_dist: Path = REPO_DIR / "frontend" / "dist"  # served by the API in production (E16-05)


settings = Settings()
