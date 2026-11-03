"""The main application window: wires the manager to the views."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk

from services.event_manager import CompileResult, EventManager
from ui.calendar_view import CalendarView, EventListView
from ui.event_dialog import EventDialog
from ui.source_panel import SourcePanel

APP_NAME = "Smart Scheduler"


class SchedulerApp(tk.Tk):
    def __init__(self, manager: EventManager | None = None):
        super().__init__()
        self.manager = manager or EventManager()
        self.geometry("1100x650")
        self.minsize(800, 450)
        self.results: queue.Queue = queue.Queue()
        self._build_style()
        self._build_menu()
        self._build_ui()
        self.manager.load_default()
        self.source_panel.refresh()
        self.protocol("WM_DELETE_WINDOW", self._quit)
        self.refresh()
        self._update_title()

    # ---- construction -------------------------------------------------------
    def _build_style(self) -> None:
        st = ttk.Style(self)

        def fixed(opt):
            # work around a Tk 8.6 bug where Treeview tag colours are ignored
            return [e for e in st.map("Treeview", query_opt=opt) if e[:2] != ("!disabled", "!selected")]
        st.map("Treeview", foreground=fixed("foreground"), background=fixed("background"))
        st.configure("Treeview", rowheight=26)

    def _build_menu(self) -> None:
        mb = tk.Menu(self)
        fm = tk.Menu(mb, tearoff=0)
        for label, cmd, key in [("New", self.file_new, "<Control-n>"),
                                ("Open...", self.file_open, "<Control-o>"),
                                ("Save", self.file_save, "<Control-s>")]:
            fm.add_command(label=label, command=cmd, accelerator=key[1:-1].replace("Control", "Ctrl"))
            self.bind(key, lambda _e, c=cmd: c())
        fm.add_command(label="Save As...", command=self.file_save_as)
        fm.add_separator()
        fm.add_command(label="Export as .ics (calendar)...", command=lambda: self.export("ics"))
        fm.add_command(label="Export as .csv...", command=lambda: self.export("csv"))
        fm.add_separator()
        fm.add_command(label="Exit", command=self._quit)
        mb.add_cascade(label="File", menu=fm)
        self.config(menu=mb)

    def _build_ui(self) -> None:
        self.status = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status, anchor="w", relief="sunken",
                  padding=(8, 2)).pack(fill="x", side="bottom")

        pw = ttk.PanedWindow(self, orient="horizontal")
        pw.pack(fill="both", expand=True)

        self.source_panel = SourcePanel(pw, self.manager, on_changed=self._on_data_changed,
                                        on_compile=self.compile_schedule, app_name=APP_NAME)
        pw.add(self.source_panel, weight=1)

        right = ttk.Frame(pw, padding=8)
        pw.add(right, weight=5)
        self._build_toolbar(right)

        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)
        self.calendar_view = CalendarView(
            self.tabs, self.manager, get_needle=self.search.get, on_add=self.add_event,
            on_edit=self.edit_event, on_delete=self.delete_event)
        self.list_view = EventListView(
            self.tabs, self.manager, get_needle=self.search.get, get_show_past=self.show_past.get,
            on_edit=self.edit_event, on_delete=self.delete_event, on_status=self.status.set)
        self.tabs.add(self.calendar_view, text="Calendar")
        self.tabs.add(self.list_view, text="List")

        # Only start reacting to search/show-past once both views exist.
        self.search.trace_add("write", lambda *_: self.refresh())

    def _build_toolbar(self, parent) -> None:
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Add event", command=self.add_event).pack(side="left")
        ttk.Button(bar, text="Edit", command=self.edit_event).pack(side="left", padx=4)
        ttk.Button(bar, text="Delete", command=self.delete_event).pack(side="left")
        self.show_past = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show past (list)", variable=self.show_past,
                        command=self.refresh).pack(side="right")
        self.search = tk.StringVar()
        ttk.Entry(bar, textvariable=self.search, width=22).pack(side="right", padx=8)
        ttk.Label(bar, text="Search:").pack(side="right")

    # ---- shared state helpers -----------------------------------------------
    @property
    def active_view(self):
        return self.calendar_view if self.tabs.index(self.tabs.select()) == 0 else self.list_view

    def _update_title(self) -> None:
        path = self.manager.path
        name = path.name if path else "Untitled"
        self.title(f"{APP_NAME} - {name}{' *' if self.manager.dirty else ''}")

    def refresh(self) -> None:
        self.calendar_view.refresh()
        self.list_view.refresh()      # last, so its status text ("N events shown") wins

    def _on_data_changed(self) -> None:
        self.refresh()
        self._update_title()

    def _reload_everything(self) -> None:
        self.source_panel.refresh()
        self._on_data_changed()

    # ---- file menu ----------------------------------------------------------
    def _confirm_discard(self) -> bool:
        if not self.manager.dirty:
            return True
        ans = messagebox.askyesnocancel(APP_NAME, "Save changes first?")
        if ans is None:
            return False
        return self.file_save() if ans else True

    def file_new(self) -> None:
        if self._confirm_discard():
            self.manager.new()
            self._reload_everything()

    def file_open(self) -> None:
        if not self._confirm_discard():
            return
        p = filedialog.askopenfilename(filetypes=[("Schedule files", "*.json"), ("All files", "*.*")])
        if not p:
            return
        try:
            self.manager.open(p)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not open file:\n{exc}")
            return
        self._reload_everything()

    def file_save(self) -> bool:
        if not self.manager.path:
            return self.file_save_as()
        return self._save_to(None)

    def file_save_as(self) -> bool:
        p = filedialog.asksaveasfilename(defaultextension=".json",
                                         filetypes=[("Schedule files", "*.json")])
        return self._save_to(p) if p else False

    def _save_to(self, path) -> bool:
        try:
            self.manager.save(path)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not save:\n{exc}")
            return False
        self._update_title()
        self.status.set(f"Saved to {self.manager.path}")
        return True

    def export(self, kind: str) -> None:
        if not self.manager.events:
            messagebox.showinfo(APP_NAME, "There are no events to export.")
            return
        p = filedialog.asksaveasfilename(defaultextension=f".{kind}",
                                         filetypes=[(kind.upper(), f"*.{kind}")])
        if not p:
            return
        try:
            n = self.manager.export(kind, p)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not export:\n{exc}")
            return
        self.status.set(f"Exported {n} events to {p}")

    def _quit(self) -> None:
        if self._confirm_discard():
            self.destroy()

    # ---- compiling sources (background thread) ------------------------------
    def compile_schedule(self) -> None:
        if not self.manager.sources:
            messagebox.showinfo(APP_NAME, "Add at least one link or document first.")
            return
        self.source_panel.set_busy(True)
        self.status.set("Compiling schedule...")
        sources = list(self.manager.sources)
        threading.Thread(target=self._worker, args=(sources,), daemon=True).start()
        self.after(100, self._poll)

    def _worker(self, sources) -> None:
        self.results.put(self.manager.fetch_sources(sources))

    def _poll(self) -> None:
        try:
            result: CompileResult = self.results.get_nowait()
        except queue.Empty:
            self.after(100, self._poll)
            return
        added = self.manager.apply_compile(result)
        self.source_panel.set_busy(False)
        self._on_data_changed()
        self.status.set(f"Compiled: {added} imported event(s) added.")
        messagebox.showinfo("Compile report", "\n".join(result.report) +
                            "\n\nImported events are blue; double-click any to correct it.")

    # ---- event actions ------------------------------------------------------
    def add_event(self, day: date | None = None) -> None:
        default = day.isoformat() if isinstance(day, date) else self.active_view.default_date()
        dlg = EventDialog(self, default_date=default)
        self.wait_window(dlg)
        if dlg.result:
            self.manager.add_event(dlg.result)
            self._on_data_changed()

    def edit_event(self) -> None:
        ev = self.active_view.selected_event()
        if not ev:
            return
        dlg = EventDialog(self, event=ev)
        self.wait_window(dlg)
        if dlg.result:
            self.manager.update_event(dlg.result)
            self._on_data_changed()

    def delete_event(self) -> None:
        ev = self.active_view.selected_event()
        if ev and messagebox.askyesno(APP_NAME, f"Delete '{ev.title}'?"):
            self.manager.delete_event(ev)
            self._on_data_changed()
