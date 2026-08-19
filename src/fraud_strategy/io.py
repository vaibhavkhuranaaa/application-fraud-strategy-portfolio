"""Small deterministic I/O helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(*parts: object, length: int = 32) -> str:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:length]


def write_json(path: Path, value: Any) -> None:
    def encode(item: Any) -> Any:
        try:
            import numpy as np

            if isinstance(item, np.generic):
                return item.item()
            if isinstance(item, np.ndarray):
                return item.tolist()
        except ImportError:
            pass
        if isinstance(item, Path):
            return item.as_posix()
        raise TypeError(f"cannot serialize {type(item).__name__}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=encode) + "\n", encoding="utf-8")
