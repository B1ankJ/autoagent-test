from __future__ import annotations

import json
import threading
from pathlib import Path

from autoagent.config.settings import get_settings
from autoagent.models.api import SampleResult


class ResultWriter:
    def __init__(self, batch_id: str):
        root = get_settings().data_root / "results"
        root.mkdir(parents=True, exist_ok=True)
        self.path: Path = root / f"{batch_id}.jsonl"
        self._fh = self.path.open("a", encoding="utf-8")
        self._lock = threading.Lock()

    def append(self, result: SampleResult) -> None:
        with self._lock:
            self._fh.write(result.model_dump_json() + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if not self._fh.closed:
                self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
