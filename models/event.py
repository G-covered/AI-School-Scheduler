"""The Event model."""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import asdict, dataclass, field, fields, replace


@dataclass(eq=False)
class Event:
    """A single calendar entry.

    ``date`` is an ISO string (YYYY-MM-DD); ``start`` / ``end`` are "HH:MM" or "".
    Events compare by identity, so use ``id`` to look one up.
    """

    title: str
    date: str
    start: str = ""
    end: str = ""
    location: str = ""
    notes: str = ""
    origin: str = "Manual"       # "Manual" or the label of the source it came from
    imported: bool = False       # True = created by compiling a source (can be replaced)
    source: str = ""             # the Source.value it was imported from
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    # ---- derived values -----------------------------------------------------
    @staticmethod
    def _to_minutes(hhmm: str) -> int:
        return int(hhmm[:2]) * 60 + int(hhmm[3:])

    @property
    def has_time(self) -> bool:
        return bool(self.start)

    @property
    def start_minutes(self) -> int | None:
        return self._to_minutes(self.start) if self.start else None

    @property
    def end_minutes(self) -> int | None:
        """End of the event in minutes (at least one minute after the start)."""
        if not self.start:
            return None
        s = self._to_minutes(self.start)
        e = self._to_minutes(self.end) if self.end else s + 1
        return max(e, s + 1)

    @property
    def as_date(self) -> dt.date | None:
        try:
            return dt.date.fromisoformat(self.date)
        except ValueError:
            return None

    @property
    def time_label(self) -> str:
        if not self.start:
            return "All day"
        return self.start + (f" - {self.end}" if self.end else "")

    @property
    def dedupe_key(self) -> tuple:
        return (self.title.lower(), self.date, self.start)

    @property
    def sort_key(self) -> tuple:
        return (self.date, self.start or "00:00", self.title.lower())

    def matches(self, needle: str) -> bool:
        """Case-insensitive search over title, location, notes and origin."""
        needle = needle.strip().lower()
        if not needle:
            return True
        haystack = " ".join((self.title, self.location, self.notes, self.origin)).lower()
        return needle in haystack

    # ---- copying / serialising ----------------------------------------------
    def with_changes(self, **changes) -> "Event":
        return replace(self, **changes)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        names = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in names}
        kwargs.setdefault("title", "")
        kwargs.setdefault("date", "")
        return cls(**kwargs)
