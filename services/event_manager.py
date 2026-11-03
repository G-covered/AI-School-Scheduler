"""EventManager: the application's data layer.

Owns the list of events and sources, and coordinates storage, importing,
conflict detection and exporting. It knows nothing about the user interface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from models.event import Event
from models.source import Source
from services.calendar_exporter import CalendarExporter
from services.conflict_detector import ConflictDetector
from services.document_reader import DocumentReader
from services.event_storage import EventStorage


@dataclass
class CompileResult:
    """Outcome of reading all sources (produced off the UI thread)."""
    parsed: list[Event] = field(default_factory=list)
    report: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)     # Source.value of failed sources


class EventManager:
    JS_HINT = ("\n   (Many sites load schedules with JavaScript, which can't be read. "
               "Try the site's calendar/.ics link, or save the page and add it as a file.)")

    def __init__(self, storage: EventStorage | None = None, reader: DocumentReader | None = None,
                 detector: ConflictDetector | None = None,
                 exporter: CalendarExporter | None = None):
        self.storage = storage or EventStorage()
        self.reader = reader or DocumentReader()
        self.detector = detector or ConflictDetector()
        self.exporter = exporter or CalendarExporter()
        self.events: list[Event] = []
        self.sources: list[Source] = []
        self.path: Path | None = self.storage.default_path
        self.dirty = False

    # ---- file lifecycle -----------------------------------------------------
    def new(self) -> None:
        self.events, self.sources, self.path, self.dirty = [], [], None, False

    def load_default(self) -> None:
        """Load the default schedule file if it exists; ignore problems."""
        if self.storage.default_path.exists():
            try:
                self.open(self.storage.default_path)
            except Exception:
                pass
        self.dirty = False

    def open(self, path) -> None:
        self.events, self.sources = self.storage.load(path)
        self.path = Path(path)
        self.dirty = False

    def save(self, path=None) -> None:
        if path is not None:
            self.path = Path(path)
        if self.path is None:
            raise ValueError("No file path set; use save(path).")
        self.storage.save(self.path, self.events, self.sources)
        self.dirty = False

    # ---- queries ------------------------------------------------------------
    def get(self, event_id: str) -> Event | None:
        return next((e for e in self.events if e.id == event_id), None)

    def events_by_day(self, needle: str = "") -> dict[str, list[Event]]:
        out: dict[str, list[Event]] = {}
        for e in self.events:
            if e.matches(needle):
                out.setdefault(e.date, []).append(e)
        for day_events in out.values():
            day_events.sort(key=lambda e: (e.start or "00:00", e.title.lower()))
        return out

    def filtered(self, needle: str = "", include_past: bool = True,
                 today: str | None = None) -> list[Event]:
        """Events matching the search text, sorted chronologically."""
        today = today or date.today().isoformat()
        shown = [e for e in self.events
                 if (include_past or e.date >= today) and e.matches(needle)]
        return sorted(shown, key=lambda e: e.sort_key)

    def conflicts(self) -> set[str]:
        return self.detector.find(self.events)

    # ---- event editing ------------------------------------------------------
    def add_event(self, event: Event) -> None:
        self.events.append(event)
        self.dirty = True

    def update_event(self, event: Event) -> None:
        for i, e in enumerate(self.events):
            if e.id == event.id:
                self.events[i] = event
                self.dirty = True
                return
        raise KeyError(event.id)

    def delete_event(self, event: Event) -> None:
        self.events = [e for e in self.events if e.id != event.id]
        self.dirty = True

    # ---- sources ------------------------------------------------------------
    def add_sources(self, sources: list[Source]) -> None:
        self.sources.extend(sources)
        self.dirty = True

    @staticmethod
    def is_from_sources(event: Event, sources: list[Source]) -> bool:
        if not event.imported:
            return False
        values = {s.value for s in sources}
        labels = {s.label for s in sources}
        return event.source in values or (not event.source and event.origin in labels)

    def imported_count_from(self, sources: list[Source]) -> int:
        return sum(1 for e in self.events if self.is_from_sources(e, sources))

    def remove_sources(self, indices: list[int]) -> None:
        """Remove sources by list index, plus the events imported from them."""
        removed = [self.sources[i] for i in indices]
        self.events = [e for e in self.events if not self.is_from_sources(e, removed)]
        for i in sorted(indices, reverse=True):
            del self.sources[i]
        self.dirty = True

    # ---- compiling ----------------------------------------------------------
    def fetch_sources(self, sources: list[Source] | None = None) -> CompileResult:
        """Read every source. Does not touch manager state, so it is thread-safe."""
        result = CompileResult()
        for s in (sources if sources is not None else list(self.sources)):
            try:
                evs = self.reader.read(s)
                result.parsed.extend(evs)
                line = f"{s.label}: {len(evs)} event(s) found"
                if not evs and s.is_link:
                    line += self.JS_HINT
                result.report.append(line)
            except Exception as exc:
                result.failed.append(s.value)
                result.report.append(f"{s.label}: FAILED - {exc}")
        return result

    @staticmethod
    def merge(existing: list[Event], parsed: list[Event], failed_sources=()):
        """Keep manual events; replace imported ones with freshly parsed events.
        Imported events from sources that failed this time are kept."""
        keep = [e for e in existing if not e.imported or e.source in failed_sources]
        seen = {e.dedupe_key for e in keep}
        added = []
        for e in parsed:
            if e.dedupe_key not in seen:
                seen.add(e.dedupe_key)
                added.append(e)
        return keep + added, len(added)

    def apply_compile(self, result: CompileResult) -> int:
        """Merge a CompileResult into the schedule; returns the number of events added."""
        self.events, added = self.merge(self.events, result.parsed, result.failed)
        self.dirty = True
        return added

    # ---- export -------------------------------------------------------------
    def export(self, kind: str, path) -> int:
        self.exporter.export(kind, self.events, path)
        return len(self.events)
