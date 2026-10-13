"""
Application configuration for localfin.

Decouples internal engine naming (localfin) from user-facing product branding.
"""

import os
from pathlib import Path

# Core Internal Engine Identity
ENGINE_NAME: str = "localfin"

# User-facing Brand / Product Name (override via APP_DISPLAY_NAME env var)
APP_DISPLAY_NAME: str = os.getenv("APP_DISPLAY_NAME", "LocalFin")
APP_DESCRIPTION: str = (
    "Privacy-first, zero-egress financial statement intelligence and reconciliation agent."
)

# Persistence Paths
DATA_DIR: Path = Path(os.getenv("LOCALFIN_DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_DB_PATH: Path = DATA_DIR / f"{ENGINE_NAME}.db"

# Local LLM / Ollama Configuration
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
