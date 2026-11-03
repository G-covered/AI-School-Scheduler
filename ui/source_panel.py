"""Left-hand panel: the list of links/documents and the Compile button."""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable

from models.source import Source
from services.event_manager import EventManager


class SourcePanel(ttk.Frame):
    LINK_ICON = "\U0001F517 "
    FILE_ICON = "\U0001F4C4 "
    FILE_TYPES = [("Schedule documents", "*.txt *.md *.csv *.ics *.docx *.html *.htm *.pdf"),
                  ("All files", "*.*")]

    def __init__(self, parent, manager: EventManager,
                 on_changed: Callable[[], None], on_compile: Callable[[], None],
                 app_name: str = "Smart Scheduler"):
        super().__init__(parent, padding=8)
        self.manager = manager
        self.on_changed = on_changed
        self.app_name = app_name

        ttk.Label(self, text="Sources (links & documents)",
                  font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        box = ttk.Frame(self)
        box.pack(fill="both", expand=True, pady=6)
        self.listbox = tk.Listbox(box, activestyle="none", selectmode="extended")
        sb = ttk.Scrollbar(box, command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.listbox.bind("<Delete>", lambda _e: self.remove_selected())
        self.listbox.bind("<BackSpace>", lambda _e: self.remove_selected())

        row = ttk.Frame(self)
        row.pack(fill="x")
        ttk.Button(row, text="Add link", command=self.add_link).pack(side="left", expand=True, fill="x")
        ttk.Button(row, text="Add documents", command=self.add_documents).pack(
            side="left", expand=True, fill="x", padx=4)
        ttk.Button(row, text="Remove", command=self.remove_selected).pack(side="left", expand=True, fill="x")
        self.compile_btn = ttk.Button(self, text="Compile schedule", command=on_compile)
        self.compile_btn.pack(fill="x", pady=(10, 0), ipady=6)

    # ---- display ------------------------------------------------------------
    def refresh(self) -> None:
        self.listbox.delete(0, "end")
        for s in self.manager.sources:
            self.listbox.insert("end", (self.LINK_ICON if s.is_link else self.FILE_ICON) + s.label)

    def set_busy(self, busy: bool) -> None:
        self.compile_btn.state(["disabled"] if busy else ["!disabled"])

    # ---- actions ------------------------------------------------------------
    def add_link(self) -> None:
        url = simpledialog.askstring("Add link", "Paste a URL (web page, .ics feed, or PDF):",
                                     parent=self.winfo_toplevel())
        if url and url.strip():
            self.manager.add_sources([Source.link(url)])
            self.refresh()
            self.on_changed()

    def add_documents(self) -> None:
        files = filedialog.askopenfilenames(filetypes=self.FILE_TYPES)
        if files:
            self.manager.add_sources([Source.file(f) for f in files])
            self.refresh()
            self.on_changed()

    def remove_selected(self) -> None:
        idx = list(self.listbox.curselection())
        if not idx:
            messagebox.showinfo(self.app_name, "Select a source in the list first.")
            return
        chosen = [self.manager.sources[i] for i in idx]
        n = self.manager.imported_count_from(chosen)
        msg = f"Remove {len(chosen)} source(s)?"
        if n:
            msg += (f"\n\nThis also removes {n} event(s) imported from it. "
                    "Events you added or edited yourself are kept.")
        if not messagebox.askyesno(self.app_name, msg):
            return
        self.manager.remove_sources(idx)
        self.refresh()
        self.on_changed()
