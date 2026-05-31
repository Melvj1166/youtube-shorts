from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Models
    whisper_model: str = "large-v3"
    whisper_compute_type: str = "int8"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    # Pipeline
    top_n_shorts: int = 5
    min_short_duration: int = 20
    max_short_duration: int = 60
    enable_diarization: bool = False

    # Paths
    cache_dir: Path = Path("./cache")
    output_dir: Path = Path("./output")

    # Memory
    graphify_namespace: str = "podshorts"
    graphify_endpoint: str | None = None
    graphify_api_key: str | None = None

    # Behavior
    force_rerun: bool = False
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {valid}, got '{v}'")
        return upper

    @field_validator("whisper_compute_type")
    @classmethod
    def validate_compute_type(cls, v: str) -> str:
        valid = {"int8", "float16", "float32"}
        if v not in valid:
            raise ValueError(f"whisper_compute_type must be one of {valid}")
        return v

    def ensure_dirs(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
