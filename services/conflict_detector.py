"""Find events that overlap in time."""
from __future__ import annotations

from models.event import Event


class ConflictDetector:
    """Detects timed events on the same day whose time ranges overlap."""

    def find(self, events: list[Event]) -> set[str]:
        """Return the ids of every event that overlaps another one."""
        by_day: dict[str, list[Event]] = {}
        for e in events:
            if e.has_time:
                by_day.setdefault(e.date, []).append(e)

        conflicting: set[str] = set()
        for day_events in by_day.values():
            for i, a in enumerate(day_events):
                for b in day_events[i + 1:]:
                    if self._overlap(a, b):
                        conflicting.update((a.id, b.id))
        return conflicting

    @staticmethod
    def _overlap(a: Event, b: Event) -> bool:
        return a.start_minutes < b.end_minutes and b.start_minutes < a.end_minutes
