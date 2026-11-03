"""Modal dialog for creating or editing an event."""
from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from tkinter import messagebox, ttk

from models.event import Event
from services.text_parser import TextParser


class EventDialog(tk.Toplevel):
    """After the dialog closes, ``result`` holds the saved Event (or None if cancelled)."""

    def __init__(self, parent, event: Event | None = None, default_date: str | None = None):
        super().__init__(parent)
        self.title("Edit event" if event else "New event")
        self.resizable(False, False)
        self.result: Event | None = None
        self.event = event
        ev = event or Event(title="", date="")
        self.vars: dict[str, tk.StringVar] = {}
        fields = [("Title", "title", ev.title),
                  ("Date (YYYY-MM-DD)", "date", ev.date or default_date or date.today().isoformat()),
                  ("Start (e.g. 14:30 or 2:30pm)", "start", ev.start),
                  ("End", "end", ev.end),
                  ("Location", "location", ev.location)]
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)
        for r, (label, key, val) in enumerate(fields):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=3)
            self.vars[key] = tk.StringVar(value=val)
            ttk.Entry(frm, textvariable=self.vars[key], width=38).grid(row=r, column=1, pady=3, padx=(8, 0))
        ttk.Label(frm, text="Notes").grid(row=len(fields), column=0, sticky="nw", pady=3)
        self.notes = tk.Text(frm, width=38, height=5, wrap="word")
        self.notes.grid(row=len(fields), column=1, pady=3, padx=(8, 0))
        self.notes.insert("1.0", ev.notes)
        btns = ttk.Frame(frm)
        btns.grid(row=len(fields) + 1, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="Save", command=self._save).pack(side="right")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.transient(parent)
        self.grab_set()
        self.focus_set()

    def _save(self) -> None:
        v = {k: var.get().strip() for k, var in self.vars.items()}
        try:
            if not v["title"]:
                raise ValueError("Title is required.")
            datetime.strptime(v["date"], "%Y-%m-%d")
            v["start"] = TextParser.normalize_time(v["start"])
            v["end"] = TextParser.normalize_time(v["end"])
            if v["end"] and not v["start"]:
                raise ValueError("Set a start time or clear the end time.")
            if v["end"] and v["end"] <= v["start"]:
                raise ValueError("End time must be after the start time.")
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc), parent=self)
            return
        v["notes"] = self.notes.get("1.0", "end").strip()
        # User-touched events are never overwritten by a recompile -> imported=False.
        if self.event:
            self.result = self.event.with_changes(imported=False, **v)
        else:
            self.result = Event(origin="Manual", imported=False, **v)
        self.destroy()
