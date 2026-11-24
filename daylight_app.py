"""Smart Scheduler with the Daylight interface.

Setup:  pip install pywebview        (add: pip install pypdf  for PDF support)
Files:  keep your original code saved as smart_scheduler.py next to this file,
        plus daylight_ui.html.
Run:    python daylight_app.py
"""
import json
from datetime import date
from pathlib import Path

import webview

import smart_scheduler as ss  # your original file: parsing, merging, conflicts, .ics export

UI = Path(__file__).with_name("daylight_ui.html")


def _dialog(kind):
    """File-dialog constants differ between pywebview versions."""
    fd = getattr(webview, "FileDialog", None)
    return getattr(fd, kind) if fd else getattr(webview, kind + "_DIALOG")


class Api:
    """Every public method here can be called from the page via window.pywebview.api."""

    def __init__(self):
        self._ev, self._src = [], []
        if ss.DEFAULT_PATH.exists():
            try:
                data = json.loads(ss.DEFAULT_PATH.read_text(encoding="utf-8"))
                self._ev, self._src = data.get("events", []), data.get("sources", [])
            except Exception:
                pass

    # ---- helpers (underscore = not exposed to the page) ----
    def _save(self):
        ss.DEFAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        ss.DEFAULT_PATH.write_text(
            json.dumps({"version": 1, "events": self._ev, "sources": self._src}, indent=2),
            encoding="utf-8")

    def _state(self):
        bad = ss.find_conflicts(self._ev)
        return {"events": [{**e, "conflict": e["id"] in bad} for e in self._ev],
                "sources": [{**s, "label": ss.source_label(s)} for s in self._src]}

    def _commit(self):
        self._save()
        return self._state()

    # ---- called from the page ----
    def state(self):
        return self._state()

    def save_event(self, ev):
        try:
            title = ev.get("title", "").strip()
            if not title:
                raise ValueError("Title is required.")
            date.fromisoformat(ev.get("date", ""))
            start, end = ss.norm_time(ev.get("start", "")), ss.norm_time(ev.get("end", ""))
            if end and not start:
                raise ValueError("Set a start time or clear the end time.")
            if end and end <= start:
                raise ValueError("End time must be after the start time.")
        except ValueError as exc:
            msg = str(exc)
            return {"error": "Please enter a valid date." if "isoformat" in msg else msg}
        fields = dict(title=title, date=ev["date"], start=start, end=end,
                      location=ev.get("location", "").strip(), notes=ev.get("notes", "").strip())
        old = next((e for e in self._ev if e["id"] == ev.get("id")), None)
        if old:
            old.update(fields, imported=False)  # edited events are never overwritten by a recompile
        else:
            self._ev.append({**ss.new_event(title, ev["date"]), **fields})
        return self._commit()

    def delete_event(self, event_id):
        self._ev = [e for e in self._ev if e["id"] != event_id]
        return self._commit()

    def add_link(self, url):
        url = url.strip()
        if url and not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
        if url:
            self._src.append({"type": "link", "value": url})
        return self._commit()

    def add_files(self):
        paths = webview.windows[0].create_file_dialog(_dialog("OPEN"), allow_multiple=True)
        for p in paths or []:
            self._src.append({"type": "file", "value": p})
        return self._commit()

    def remove_source(self, index):
        if 0 <= index < len(self._src):
            s = self._src.pop(index)
            label = ss.source_label(s)
            self._ev = [e for e in self._ev if not (
                e.get("imported") and (e.get("source") == s["value"]
                                       or (not e.get("source") and e.get("origin") == label)))]
        return self._commit()

    def compile(self):
        parsed, report, failed = [], [], []
        for s in self._src:
            label = ss.source_label(s)
            try:
                found = ss.events_from_source(s)
                parsed.extend(found)
                line = f"{label}: {len(found)} event(s) found"
                if not found and s["type"] == "link":
                    line += ("\n   (Many sites load schedules with JavaScript, which can't be read. "
                             "Try the site's .ics link, or save the page and add it as a document.)")
                report.append(line)
            except Exception as exc:
                failed.append(s["value"])
                report.append(f"{label}: FAILED - {exc}")
        self._ev, added = ss.merge(self._ev, parsed, failed)
        return {"state": self._commit(), "report": report or ["No sources to compile."], "added": added}

    def export_ics(self):
        if not self._ev:
            return "There are no events to export."
        path = webview.windows[0].create_file_dialog(_dialog("SAVE"), save_filename="schedule.ics")
        if not path:
            return "Export cancelled."
        path = path if isinstance(path, str) else path[0]
        ss.export_ics(sorted(self._ev, key=lambda e: (e["date"], e["start"])), path)
        return f"Exported {len(self._ev)} events."


if __name__ == "__main__":
    webview.create_window("Smart Scheduler", html=UI.read_text(encoding="utf-8"), js_api=Api(),
                          width=1440, height=900, min_size=(1000, 700))
    webview.start()