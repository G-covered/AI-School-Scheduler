"""The month-grid calendar view and the flat list view of events."""
from __future__ import annotations

import calendar
import tkinter as tk
from datetime import date
from tkinter import ttk
from typing import Callable

from models.event import Event
from services.event_manager import EventManager


def configure_tag_colors(tree: ttk.Treeview) -> None:
    tree.tag_configure("header", background="#e8eef7", foreground="#1b2a41")
    tree.tag_configure("conflict", background="#ffd9d9", foreground="#7a0000")
    tree.tag_configure("imported", foreground="#35557a")


def row_tags(event: Event, conflicts: set[str]) -> tuple:
    if event.id in conflicts:
        return ("conflict",)
    return ("imported",) if event.imported else ()


class CalendarView(ttk.Frame):
    """Month grid with a side panel listing the selected day's events."""

    CHIP = {"manual": "#cfeccf", "imported": "#d3e1f6", "conflict": "#ffc9c9"}
    DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    MAX_CHIPS = 3

    def __init__(self, parent, manager: EventManager, get_needle: Callable[[], str],
                 on_add: Callable[[date | None], None], on_edit: Callable[[], None],
                 on_delete: Callable[[], None]):
        super().__init__(parent)
        self.manager = manager
        self.get_needle = get_needle
        self.on_add, self.on_edit, self.on_delete = on_add, on_edit, on_delete
        today = date.today()
        self.cal_month = today.replace(day=1)
        self.sel_day = today
        self.cells: dict[date, tk.Frame] = {}
        self._build()

    # ---- construction -------------------------------------------------------
    def _build(self) -> None:
        head = ttk.Frame(self)
        head.pack(fill="x", pady=(6, 4))
        ttk.Button(head, text="\u25C0", width=3, command=lambda: self.shift_month(-1)).pack(side="left")
        self.month_lbl = ttk.Label(head, font=("TkDefaultFont", 14, "bold"), width=18, anchor="center")
        self.month_lbl.pack(side="left", padx=6)
        ttk.Button(head, text="\u25B6", width=3, command=lambda: self.shift_month(1)).pack(side="left")
        ttk.Button(head, text="Today", command=self.go_today).pack(side="left", padx=10)
        ttk.Label(head, text="Click a day to see its events; double-click a day to add one.",
                  foreground="#666").pack(side="right")

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)
        self.grid_frame = tk.Frame(body, bg="#c9ced6")
        body.add(self.grid_frame, weight=4)

        side = ttk.Frame(body, padding=(8, 0, 0, 0))
        body.add(side, weight=2)
        self.day_lbl = ttk.Label(side, font=("TkDefaultFont", 11, "bold"), wraplength=260)
        self.day_lbl.pack(anchor="w", pady=(0, 6))
        self.day_tree = ttk.Treeview(side, columns=("time", "title", "location"),
                                     show="headings", selectmode="browse")
        for c, t, w in [("time", "Time", 95), ("title", "Event", 150), ("location", "Location", 90)]:
            self.day_tree.heading(c, text=t)
            self.day_tree.column(c, width=w, anchor="w")
        configure_tag_colors(self.day_tree)
        self.day_tree.pack(fill="both", expand=True)
        self.day_tree.bind("<Double-1>", lambda _e: self.on_edit())
        self.day_tree.bind("<Delete>", lambda _e: self.on_delete())
        ttk.Button(side, text="Add event on this day",
                   command=lambda: self.on_add(self.sel_day)).pack(fill="x", pady=(6, 0))

    # ---- public API ---------------------------------------------------------
    def selected_event(self) -> Event | None:
        for iid in self.day_tree.selection():
            return self.manager.get(iid)
        return None

    def default_date(self) -> str:
        return self.sel_day.isoformat()

    def select_day(self, d: date, event_id: str | None = None) -> None:
        old, self.sel_day = self.sel_day, d
        if (d.year, d.month) != (self.cal_month.year, self.cal_month.month):
            self.cal_month = d.replace(day=1)
            self.refresh(event_id)
        else:
            self._style_cell(old)
            self._style_cell(d)
            self._refresh_day_panel(event_id)

    def shift_month(self, delta: int) -> None:
        m = self.cal_month.month - 1 + delta
        self.cal_month = date(self.cal_month.year + m // 12, m % 12 + 1, 1)
        self.refresh()

    def go_today(self) -> None:
        self.sel_day = date.today()
        self.cal_month = self.sel_day.replace(day=1)
        self.refresh()

    def refresh(self, select_id: str | None = None) -> None:
        gf = self.grid_frame
        for w in gf.winfo_children():
            w.destroy()
        self.cells = {}
        y, m = self.cal_month.year, self.cal_month.month
        self.month_lbl.config(text=self.cal_month.strftime("%B %Y"))
        weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(y, m)
        for c, name in enumerate(self.DAY_NAMES):
            tk.Label(gf, text=name, bg="#e8eef7", fg="#1b2a41", pady=3).grid(
                row=0, column=c, sticky="nsew", padx=1, pady=1)
            gf.columnconfigure(c, weight=1, uniform="c")
        for r in range(1, 7):
            gf.rowconfigure(r, weight=1 if r <= len(weeks) else 0, uniform="r")
        by_day = self.manager.events_by_day(self.get_needle())
        conflicts = self.manager.conflicts()
        for r, week in enumerate(weeks, 1):
            for c, d in enumerate(week):
                self._build_cell(gf, r, c, d, m, by_day.get(d.isoformat(), []), conflicts)
        self._refresh_day_panel(select_id)

    # ---- internals ----------------------------------------------------------
    def _build_cell(self, gf, r, c, d: date, month: int, evs: list[Event], conflicts: set[str]) -> None:
        small = ("TkDefaultFont", 9)
        in_month = d.month == month
        bg = "#ffffff" if in_month else "#f1f2f4"
        cell = tk.Frame(gf, bg=bg, width=10, height=10, highlightthickness=1)
        cell.pack_propagate(False)
        cell.grid(row=r, column=c, sticky="nsew", padx=1, pady=1)
        self.cells[d] = cell
        self._style_cell(d)
        if d == date.today():
            num = tk.Label(cell, text=str(d.day), bg="#1a73e8", fg="white", font=small, padx=5)
            num.pack(anchor="e", padx=3, pady=2)
        else:
            num = tk.Label(cell, text=str(d.day), bg=bg, fg="#222" if in_month else "#999", font=small)
            num.pack(anchor="e", padx=5, pady=2)
        for w in (cell, num):
            w.bind("<Button-1>", lambda _e, d=d: self.select_day(d))
            w.bind("<Double-1>", lambda _e, d=d: (self.select_day(d), self.on_add(d)))
        for e in evs[:self.MAX_CHIPS]:
            kind = "conflict" if e.id in conflicts else ("imported" if e.imported else "manual")
            text = (e.start + " " if e.start else "") + e.title
            chip = tk.Label(cell, text=text, bg=self.CHIP[kind], fg="#1b2a41", anchor="w", font=small)
            chip.pack(fill="x", padx=2, pady=1)
            chip.bind("<Button-1>", lambda _e, d=d, i=e.id: self.select_day(d, i))
            chip.bind("<Double-1>", lambda _e, d=d, i=e.id: (self.select_day(d, i), self.on_edit()))
        if len(evs) > self.MAX_CHIPS:
            more = tk.Label(cell, text=f"+{len(evs) - self.MAX_CHIPS} more", bg=bg, fg="#555",
                            anchor="w", font=small)
            more.pack(fill="x", padx=4)
            more.bind("<Button-1>", lambda _e, d=d: self.select_day(d))

    def _style_cell(self, d: date) -> None:
        cell = self.cells.get(d)
        if cell:
            sel = d == self.sel_day
            col = "#1a73e8" if sel else "#c9ced6"
            cell.config(highlightthickness=3 if sel else 1, highlightbackground=col, highlightcolor=col)

    def _refresh_day_panel(self, select_id: str | None = None) -> None:
        evs = self.manager.events_by_day(self.get_needle()).get(self.sel_day.isoformat(), [])
        conflicts = self.manager.conflicts()
        self.day_lbl.config(text=f"{self.sel_day.strftime('%A, %b %d, %Y')}  \u2022  {len(evs)} event(s)")
        self.day_tree.delete(*self.day_tree.get_children())
        for e in evs:
            self.day_tree.insert("", "end", iid=e.id, values=(e.time_label, e.title, e.location),
                                 tags=row_tags(e, conflicts))
        if select_id and self.day_tree.exists(select_id):
            self.day_tree.selection_set(select_id)


class EventListView(ttk.Frame):
    """Chronological list of events grouped under date headers."""

    HEADER_PREFIX = "hdr:"

    def __init__(self, parent, manager: EventManager, get_needle: Callable[[], str],
                 get_show_past: Callable[[], bool], on_edit: Callable[[], None],
                 on_delete: Callable[[], None], on_status: Callable[[str], None]):
        super().__init__(parent)
        self.manager = manager
        self.get_needle, self.get_show_past = get_needle, get_show_past
        self.on_status = on_status

        cols = ("time", "title", "location", "source")
        self.tree = ttk.Treeview(self, columns=cols, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Date")
        for c, t, w in [("time", "Time", 110), ("title", "Event", 300),
                        ("location", "Location", 160), ("source", "Source", 160)]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.column("#0", width=190)
        configure_tag_colors(self.tree)
        vs = ttk.Scrollbar(self, command=self.tree.yview)
        self.tree.config(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: on_edit())
        self.tree.bind("<Delete>", lambda _e: on_delete())

    def selected_event(self) -> Event | None:
        for iid in self.tree.selection():
            if not iid.startswith(self.HEADER_PREFIX):
                return self.manager.get(iid)
        return None

    def default_date(self) -> str | None:
        sel = self.tree.selection()
        if sel and sel[0].startswith(self.HEADER_PREFIX):
            return sel[0][len(self.HEADER_PREFIX):]
        return None

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        shown = self.manager.filtered(self.get_needle(), include_past=self.get_show_past())
        conflicts = self.manager.conflicts()
        last = None
        for e in shown:
            if e.date != last:
                last = e.date
                d = e.as_date
                pretty = d.strftime("%a, %b %d, %Y") if d else last
                self.tree.insert("", "end", iid=f"{self.HEADER_PREFIX}{last}", text=pretty,
                                 open=True, tags=("header",))
            self.tree.insert(f"{self.HEADER_PREFIX}{e.date}", "end", iid=e.id, text="",
                             values=(e.time_label, e.title, e.location,
                                     e.origin if e.imported else "Manual"),
                             tags=row_tags(e, conflicts))
        msg = f"{len(shown)} event(s) shown"
        if conflicts:
            msg += f"  |  {len(conflicts)} event(s) overlap (highlighted red)"
        self.on_status(msg)
