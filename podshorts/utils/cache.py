from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from podshorts.exceptions import CacheError
from podshorts.utils.logging import get_logger

logger = get_logger(__name__)


def cache_path(cache_dir: Path, video_id: str, stage: str, ext: str = "json") -> Path:
    return cache_dir / video_id / f"{stage}.{ext}"


def cache_exists(cache_dir: Path, video_id: str, stage: str, ext: str = "json") -> bool:
    return cache_path(cache_dir, video_id, stage, ext).exists()


def cache_read(cache_dir: Path, video_id: str, stage: str) -> Any:
    path = cache_path(cache_dir, video_id, stage)
    if not path.exists():
        raise CacheError(f"Cache miss: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise CacheError(f"Failed to read cache at {path}: {exc}") from exc


def cache_write(cache_dir: Path, video_id: str, stage: str, data: Any) -> Path:
    path = cache_path(cache_dir, video_id, stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except (TypeError, OSError) as exc:
        raise CacheError(f"Failed to write cache at {path}: {exc}") from exc
    logger.debug("Cache written: %s", path)
    return path


def video_cache_dir(cache_dir: Path, video_id: str) -> Path:
    return cache_dir / video_id
