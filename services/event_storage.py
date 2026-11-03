"""Load and save the schedule as a JSON file."""
from __future__ import annotations

import json
from pathlib import Path

from models.event import Event
from models.source import Source


class EventStorage:
    VERSION = 1
    DEFAULT_PATH = Path.home() / ".smart_scheduler" / "schedule.json"

    def __init__(self, default_path: Path | None = None):
        self.default_path = Path(default_path) if default_path else self.DEFAULT_PATH

    def load(self, path) -> tuple[list[Event], list[Source]]:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        events = [Event.from_dict(e) for e in data.get("events", [])]
        sources = [Source.from_dict(s) for s in data.get("sources", [])]
        return events, sources

    def save(self, path, events: list[Event], sources: list[Source]) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": self.VERSION,
                   "events": [e.to_dict() for e in events],
                   "sources": [s.to_dict() for s in sources]}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
