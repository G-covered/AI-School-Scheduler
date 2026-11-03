"""Export events to .ics and .csv files."""
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from models.event import Event


class CalendarExporter:
    CSV_HEADER = ["Date", "Start", "End", "Title", "Location", "Notes", "Source"]

    def export(self, kind: str, events: list[Event], path) -> None:
        ordered = sorted(events, key=lambda e: (e.date, e.start))
        if kind == "ics":
            self.to_ics(ordered, path)
        elif kind == "csv":
            self.to_csv(ordered, path)
        else:
            raise ValueError(f"Unsupported export format: {kind!r}")

    @staticmethod
    def _escape(s: str) -> str:
        return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    def to_ics(self, events: list[Event], path) -> None:
        now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Smart Scheduler//EN"]
        for e in events:
            d = e.date.replace("-", "")
            lines += ["BEGIN:VEVENT", f"UID:{e.id}@smartscheduler", f"DTSTAMP:{now}"]
            if e.start:
                lines.append(f"DTSTART:{d}T{e.start.replace(':', '')}00")
                if e.end:
                    lines.append(f"DTEND:{d}T{e.end.replace(':', '')}00")
            else:
                nxt = (date.fromisoformat(e.date) + timedelta(days=1)).strftime("%Y%m%d")
                lines += [f"DTSTART;VALUE=DATE:{d}", f"DTEND;VALUE=DATE:{nxt}"]
            lines.append(f"SUMMARY:{self._escape(e.title)}")
            if e.location:
                lines.append(f"LOCATION:{self._escape(e.location)}")
            if e.notes:
                lines.append(f"DESCRIPTION:{self._escape(e.notes)}")
            lines.append("END:VEVENT")
        lines.append("END:VCALENDAR")
        Path(path).write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")

    def to_csv(self, events: list[Event], path) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(self.CSV_HEADER)
            for e in events:
                w.writerow([e.date, e.start, e.end, e.title, e.location, e.notes, e.origin])
