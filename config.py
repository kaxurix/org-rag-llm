"""Configuration without model downloads or database connections at import time."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def flag(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes"}


def local_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = local_path(os.getenv("DATA_DIR", "data"))
    dataset_dir: Path = local_path(os.getenv("DATASET_DIR", "."))
    dataset_glob: str = os.getenv("DATASET_GLOB", "NOTULA RABES STECH 2026 *.pdf")
    auto_import: bool = flag("AUTO_IMPORT", True)
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "25"))
    max_pdf_pages: int = int(os.getenv("MAX_PDF_PAGES", "300"))
    answer_mode: str = os.getenv("ANSWER_MODE", "auto")
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    gemini_api_key: str = field(default=os.getenv("GEMINI_API_KEY", ""), repr=False)
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    gemini_timeout: float = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "40"))
    gemini_max_tokens: int = int(os.getenv("GEMINI_MAX_TOKENS", "2048"))
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
    ollama_timeout: float = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "25"))
    ollama_context_tokens: int = int(os.getenv("OLLAMA_CONTEXT_TOKENS", "4096"))
    ollama_max_tokens: int = int(os.getenv("OLLAMA_MAX_TOKENS", "256"))
    ollama_max_sources: int = int(os.getenv("OLLAMA_MAX_SOURCES", "4"))
    ollama_source_chars: int = int(os.getenv("OLLAMA_SOURCE_CHARS", "650"))
    ollama_keep_alive: str = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
    ollama_preload: bool = flag("OLLAMA_PRELOAD", True)
    semantic_search: bool = flag("SEMANTIC_SEARCH", False)
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    embedding_local_only: bool = flag("EMBEDDING_LOCAL_ONLY", True)
    api_key: str = os.getenv("API_KEY", "")

    def __post_init__(self):
        if self.answer_mode not in {"auto", "extractive", "ollama", "gemini"}:
            raise ValueError("ANSWER_MODE harus auto, extractive, ollama, atau gemini.")
        if self.llm_provider not in {"ollama", "gemini"}:
            raise ValueError("LLM_PROVIDER harus ollama atau gemini.")
        if self.gemini_timeout <= 0 or not 256 <= self.gemini_max_tokens <= 8192:
            raise ValueError("Timeout atau batas token Gemini tidak valid.")
        if min(self.max_upload_mb, self.max_pdf_pages, self.ollama_timeout) <= 0:
            raise ValueError("Batas unggahan, halaman, dan timeout harus positif.")
        if not 2048 <= self.ollama_context_tokens <= 32768:
            raise ValueError("OLLAMA_CONTEXT_TOKENS harus 2048–32768.")
        if not 64 <= self.ollama_max_tokens <= 2048 or not 1 <= self.ollama_max_sources <= 8:
            raise ValueError("Batas keluaran AI atau jumlah sumber tidak valid.")
        if not 300 <= self.ollama_source_chars <= 1600:
            raise ValueError("OLLAMA_SOURCE_CHARS harus 300–1600.")

    @property
    def provider(self) -> str:
        return self.answer_mode if self.answer_mode in {"ollama", "gemini"} else self.llm_provider

    @property
    def generation_timeout(self) -> float:
        return self.gemini_timeout if self.provider == "gemini" else self.ollama_timeout

    @property
    def db_path(self) -> Path:
        return self.data_dir / "campusorg.sqlite3"
