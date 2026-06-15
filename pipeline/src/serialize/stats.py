"""Build statistics collector."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class StatsCollector:
    def __init__(self, run_id: str, interview_ids: list[int], config: dict):
        self.run_id = run_id
        self.interview_ids = interview_ids
        self.config = config
        self._counts: dict[str, int] = {}
        self._created = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()

    def add(self, key: str, value: int = 1) -> None:
        self._counts[key] = self._counts.get(key, 0) + value

    def set(self, key: str, value: int) -> None:
        self._counts[key] = value

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "created_at_utc": self._created,
            "interview_count": len(self.interview_ids),
            "config": self.config,
            "stats": dict(sorted(self._counts.items())),
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
