import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = ROOT_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
EXPORT_DIR = DATA_DIR / "exports"
UPLOAD_DIR = DATA_DIR / "uploads"
REVIEW_SESSION_DIR = DATA_DIR / "review_session"

for _d in (DATA_DIR, CACHE_DIR, EXPORT_DIR, UPLOAD_DIR, REVIEW_SESSION_DIR):
    _d.mkdir(parents=True, exist_ok=True)


@dataclass
class Settings:
    db_host: str = os.getenv("ANNOMATE_DB_HOST", "10.27.24.242")
    db_port: int = int(os.getenv("ANNOMATE_DB_PORT", "5432"))
    db_name: str = os.getenv("ANNOMATE_DB_NAME", "nmfs_annotation_db")
    db_user: str = os.getenv("ANNOMATE_DB_USER", "shannon_ai_agent")
    db_password: str = os.getenv("ANNOMATE_DB_PASSWORD", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gcp_project: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    demo_mode: bool = os.getenv("ANNOMATE_DEMO_MODE", "false").strip().lower() in ("1", "true", "yes", "on")
    marimo_port: int = int(os.getenv("ANNOMATE_MARIMO_PORT", "2718"))
    app_port: int = int(os.getenv("ANNOMATE_PORT", "8000"))
    erd_url: str = "https://anndb-frontend-app-948464146942.us-east4.run.app/"

    @property
    def pg_conninfo(self) -> str:
        return (
            f"host={self.db_host} "
            f"port={self.db_port} "
            f"dbname={self.db_name} "
            f"user={self.db_user} "
            f"password='{self.db_password}' "
            f"connect_timeout=8"
        )


def get_settings() -> Settings:
    load_dotenv(ROOT_DIR / ".env", override=True)
    return Settings()
