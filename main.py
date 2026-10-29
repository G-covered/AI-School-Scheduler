#!/usr/bin/env python3
"""
Smart Scheduler - a desktop scheduler that builds an organized agenda from
manually entered events plus links and documents that contain schedule info.

Run:   python smart_scheduler.py
Needs: Python 3.9+ (Tkinter included). Optional: `pip install pypdf` for PDFs.

Supported sources
  - Web links (HTML pages, .ics calendar feeds, PDFs)
  - Files: .txt .md .csv .ics .docx .html .pdf (PDF needs pypdf)
"""
import calendar
import csv
import io
import json
import queue
import re
import ssl
import threading
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

APP_NAME = "Smart Scheduler"
DEFAULT_PATH = Path.home() / ".smart_scheduler" / "schedule.json"

# ----------------------------------------------------------------------------
# Text parsing: find dates, times, titles and locations in free text
# ----------------------------------------------------------------------------
I = re.I
MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
         r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b")
MONTH_NUM = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WD_RX = (r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
         r"mon|tues?|wed|thu(?:rs?)?|fri)\b\.?")
NOT_TIME = r"(?!\d|:|\s*[ap]\.?m\b)"

DATE_REGEXES = [
    ("iso", re.compile(r"\b(?P<y>\d{4})-(?P<mo>\d{1,2})-(?P<d>\d{1,2})\b")),
    ("us", re.compile(r"\b(?P<mo>\d{1,2})/(?P<d>\d{1,2})(?:/(?P<y>\d{2,4}))?\b")),
    ("mdy", re.compile(rf"\b(?P<mon>{MONTH})\.?\s+(?P<d>\d{{1,2}}){NOT_TIME}(?:st|nd|rd|th)?"
                       rf"(?:,?\s+(?P<y>\d{{4}})\b)?", I)),
    ("dmy", re.compile(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<mon>{MONTH})\.?"
                       rf"(?:,?\s+(?P<y>\d{{4}})\b)?", I)),
    ("rel", re.compile(r"\b(?P<rel>today|tomorrow)\b", I)),
    ("wd", re.compile(rf"\b(?:(?P<pre>next|this)\s+)?(?P<wd>{WD_RX})", I)),
]

TOK = r"\d{1,2}:\d{2}\s*(?:[ap]\.?m\b\.?)?|\d{1,2}\s*[ap]\.?m\b\.?"
RANGE_RX = re.compile(
    rf"(?:\bfrom\s+)?\b(?P<a>\d{{1,2}}(?::\d{{2}})?\s*(?:[ap]\.?m\b\.?)?)\s*"
    rf"(?:-|\u2013|\u2014|to|until|till)\s*(?P<b>{TOK})", I)
SINGLE_RX = re.compile(rf"(?:(?:\bat|@)\s*)?(?P<t>{TOK})", I)
LOC_RX = re.compile(r"(?:@|\bat\b|\blocation\s*:)\s*(?P<loc>[^,;|()\u2013\u2014]+)", I)


def parse_tok(tok, default_ap=None):
    """'3pm', '15:30', '9' (with default am/pm) -> (hour, minute) or None."""
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(?:([ap])\.?m?\.?)?", tok.strip().lower())
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3) or default_ap
    if mi > 59:
        return None
    if ap and 1 <= h <= 12:
        h = (h % 12) + (12 if ap == "p" else 0)
    elif h > 23:
        return None
    return h, mi


def fmt_time(hm):
    return f"{hm[0]:02d}:{hm[1]:02d}"


def norm_time(text):
    """Lenient user input -> 'HH:MM' or '' (raises ValueError if invalid)."""
    text = text.strip()
    if not text:
        return ""
    t = parse_tok(text)
    if t is None:
        raise ValueError(f"Invalid time: {text!r}")
    return fmt_time(t)


def _with_year(mo, d, y, today):
    if y is None:
        dt = date(today.year, mo, d)
        if (dt - today).days < -90:      # a date well in the past -> assume next year
            dt = date(today.year + 1, mo, d)
        return dt
    y = int(y)
    return date(y + 2000 if y < 100 else y, mo, d)


def _resolve(kind, m, today):
    g = m.groupdict()
    if kind == "iso":
        return date(int(g["y"]), int(g["mo"]), int(g["d"]))
    if kind == "us":
        return _with_year(int(g["mo"]), int(g["d"]), g["y"], today)
    if kind in ("mdy", "dmy"):
        return _with_year(MONTH_NUM[g["mon"][:3].lower()], int(g["d"]), g["y"], today)
    if kind == "rel":
        return today + timedelta(days=1 if g["rel"].lower() == "tomorrow" else 0)
    if kind == "wd":
        idx = next(i for i, n in enumerate(WEEKDAYS) if n.startswith(g["wd"].lower()[:3]))
        delta = (idx - today.weekday()) % 7
        if delta == 0 and (g["pre"] or "").lower() == "next":
            delta = 7
        return today + timedelta(days=delta)
    return None


def find_date(text, today):
    """Return (date, remaining_text) for the earliest valid date in text, else (None, text)."""
    found = []
    for kind, rx in DATE_REGEXES:
        for m in rx.finditer(text):
            try:
                d = _resolve(kind, m, today)
            except (ValueError, StopIteration, KeyError):
                continue
            if d:
                found.append((m.start(), kind, m, d))
                break
    if not found:
        return None, text
    found.sort(key=lambda f: (f[1] in ("wd", "rel"), f[0]))
    _, _, m, d = found[0]
    rest = text[:m.start()] + " " + text[m.end():]
    rest = re.sub(rf"\b{WD_RX},?", " ", rest, flags=I)      # drop stray weekday names
    return d, rest


def find_times(text):
    """Return (start, end, remaining_text); start/end are 'HH:MM' or ''."""
    m = RANGE_RX.search(text)
    if m:
        b_ap = re.search(r"([ap])\.?m", m.group("b").lower())
        t2 = parse_tok(m.group("b"))
        t1 = parse_tok(m.group("a"), b_ap.group(1) if b_ap else None)
        if t1 and t2:
            if t1 > t2 and b_ap and b_ap.group(1) == "p" and t1[0] >= 12:
                t1 = (t1[0] - 12, t1[1])                   # e.g. "11-1pm" -> 11am-1pm
            return fmt_time(t1), fmt_time(t2), text[:m.start()] + " " + text[m.end():]
    m = SINGLE_RX.search(text)
    if m:
        t = parse_tok(m.group("t"))
        if t:
            return fmt_time(t), "", text[:m.start()] + " " + text[m.end():]
    return "", "", text


def clean_title(s):
    s = re.sub(r"^\s*(?:[-*\u2022>]+|\d+[.)])\s*", "", s)
    for _ in range(3):
        s = s.strip(" \t-:|,;\u2013\u2014@()[]")
        s = re.sub(r"^(?:on|at|from|by)\s+|\s+(?:on|at|from|by|until|till|to)$", "", s, flags=I)
    return re.sub(r"\s{2,}", " ", s).strip()


def new_event(title, d, start="", end="", location="", notes="", origin="Manual", imported=False):
    return {"id": uuid.uuid4().hex, "title": title, "date": d, "start": start, "end": end,
            "location": location, "notes": notes, "origin": origin, "imported": imported,
            "source": ""}


def parse_text(text, origin, today=None):
    """Heuristically turn free text into events, line by line."""
    today = today or date.today()
    events, ctx_date = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or len(line) > 400:
            continue
        d, rest = find_date(line, today)
        start, end, rest = find_times(rest)
        loc = ""
        lm = LOC_RX.search(rest)
        if lm:
            loc = lm.group("loc").strip(" .")
            rest = rest[:lm.start()] + " " + rest[lm.end():]
        title = clean_title(rest)
        if d:
            ctx_date = d
        day = d or ctx_date
        if not day or not (d or start):
            continue
        if not start and not title:          # a bare date heading: just sets context
            continue
        if not title:
            title = "Untitled event"
        events.append(new_event(title[:120], day.isoformat(), start, end, loc,
                                f"From: {line[:300]}", origin, True))
    return events


# ---- iCalendar -------------------------------------------------------------
def _ics_dt(value):
    value = value.strip()
    if re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value, "%Y%m%d"), True
    utc = value.endswith("Z")
    dt = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    if utc:
        dt = dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    return dt, False


def _ics_unescape(s):
    return re.sub(r"\\([,;nN\\])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), s)


def parse_ics(text, origin):
    text = re.sub(r"\r?\n[ \t]", "", text)           # unfold long lines
    events, cur = [], None
    for line in text.splitlines():
        if line.startswith("BEGIN:VEVENT"):
            cur = {}
        elif line.startswith("END:VEVENT") and cur is not None:
            try:
                if "DTSTART" in cur:
                    s, all_day = _ics_dt(cur["DTSTART"])
                    e = _ics_dt(cur["DTEND"])[0] if "DTEND" in cur else None
                    events.append(new_event(
                        _ics_unescape(cur.get("SUMMARY", "Untitled event")), s.date().isoformat(),
                        "" if all_day else s.strftime("%H:%M"),
                        "" if (all_day or not e or e.date() != s.date()) else e.strftime("%H:%M"),
                        _ics_unescape(cur.get("LOCATION", "")),
                        _ics_unescape(cur.get("DESCRIPTION", ""))[:500], origin, True))
            except ValueError:
                pass
            cur = None
        elif cur is not None and ":" in line:
            key, _, val = line.partition(":")
            cur[key.split(";")[0].upper()] = val
    return events


# ----------------------------------------------------------------------------
# Source extraction: links and documents -> text
# ----------------------------------------------------------------------------
class _HTMLText(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section",
             "article", "table", "ul", "ol", "dt", "dd", "header", "footer"}

    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(html):
    p = _HTMLText()
    p.feed(html)
    text = "".join(p.out)
    return "\n".join(re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in text.splitlines())


def pdf_to_text(data):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("PDF support needs pypdf  (pip install pypdf)")
    return "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(data)).pages)


def docx_to_text(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf8", "replace")
    paras = []
    for p in xml.split("</w:p>"):
        parts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>|(<w:tab\s*/>)", p)
        paras.append("".join(a if a else "\t" for a, _ in parts))
    text = "\n".join(paras)
    return (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&apos;", "'"))


def decode(data, charset=None):
    for enc in (charset, "utf-8-sig", "latin-1"):
        if enc:
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
    return data.decode("utf-8", "replace")


def events_from_bytes(data, name, content_type, origin):
    low = name.lower().split("?")[0]
    ctype = (content_type or "").lower()
    if low.endswith(".pdf") or "pdf" in ctype:
        return parse_text(pdf_to_text(data), origin)
    if low.endswith(".docx"):
        return parse_text(docx_to_text(data), origin)
    text = decode(data)
    if low.endswith(".ics") or "calendar" in ctype or text.lstrip().startswith("BEGIN:VCALENDAR"):
        return parse_ics(text, origin)
    if low.endswith((".html", ".htm")) or "html" in ctype or "<html" in text[:2000].lower():
        text = html_to_text(text)
    return parse_text(text, origin)


def ssl_context():
    """Use certifi's CA bundle when available (fixes python.org Python on macOS)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_HELP = ("SSL certificate check failed. On macOS, open /Applications/Python 3.x/ and run "
            "'Install Certificates.command', or run:  pip install certifi  and restart the app.")


def events_from_source(src):
    if src["type"] == "link":
        url = src["value"]
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 SmartScheduler"})
        try:
            with urllib.request.urlopen(req, timeout=20, context=ssl_context()) as r:
                data = r.read(8_000_000)
                ctype = r.headers.get("Content-Type")
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLError):
                raise RuntimeError(SSL_HELP)
            raise
        evs = events_from_bytes(data, url, ctype, source_label(src))
    else:
        path = Path(src["value"])
        evs = events_from_bytes(path.read_bytes(), path.name, "", source_label(src))
    for e in evs:
        e["source"] = src["value"]
    return evs


def source_label(src):
    return src["value"] if src["type"] == "link" else Path(src["value"]).name


# ----------------------------------------------------------------------------
# Scheduling helpers
# ----------------------------------------------------------------------------
def merge(existing, parsed, failed_sources=()):
    """Keep manual events; replace imported ones with freshly parsed events.
    Imported events from sources that failed this time are kept."""
    keep = [e for e in existing if not e.get("imported") or e.get("source") in failed_sources]
    seen = {(e["title"].lower(), e["date"], e["start"]) for e in keep}
    added = []
    for e in parsed:
        k = (e["title"].lower(), e["date"], e["start"])
        if k not in seen:
            seen.add(k)
            added.append(e)
    return keep + added, len(added)


def find_conflicts(events):
    by_day, bad = {}, set()
    for e in events:
        if e["start"]:
            by_day.setdefault(e["date"], []).append(e)
    for evs in by_day.values():
        spans = []
        for e in evs:
            s = int(e["start"][:2]) * 60 + int(e["start"][3:])
            en = int(e["end"][:2]) * 60 + int(e["end"][3:]) if e["end"] else s + 1
            spans.append((s, max(en, s + 1), e["id"]))
        for i, a in enumerate(spans):
            for b in spans[i + 1:]:
                if a[0] < b[1] and b[0] < a[1]:
                    bad.update((a[2], b[2]))
    return bad


def export_ics(events, path):
    def esc(s):
        return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Smart Scheduler//EN"]
    for e in events:
        d = e["date"].replace("-", "")
        lines += ["BEGIN:VEVENT", f"UID:{e['id']}@smartscheduler", f"DTSTAMP:{now}"]
        if e["start"]:
            lines.append(f"DTSTART:{d}T{e['start'].replace(':', '')}00")
            if e["end"]:
                lines.append(f"DTEND:{d}T{e['end'].replace(':', '')}00")
        else:
            nxt = (date.fromisoformat(e["date"]) + timedelta(days=1)).strftime("%Y%m%d")
            lines += [f"DTSTART;VALUE=DATE:{d}", f"DTEND;VALUE=DATE:{nxt}"]
        lines.append(f"SUMMARY:{esc(e['title'])}")
        if e["location"]:
            lines.append(f"LOCATION:{esc(e['location'])}")
        if e["notes"]:
            lines.append(f"DESCRIPTION:{esc(e['notes'])}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    Path(path).write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")


# ----------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------
class EventDialog(tk.Toplevel):
    def __init__(self, parent, event=None, default_date=None):
        super().__init__(parent)
        self.title("Edit event" if event else "New event")
        self.resizable(False, False)
        self.result = None
        self.event = event
        ev = event or {}
        self.vars = {}
        fields = [("Title", "title", ev.get("title", "")),
                  ("Date (YYYY-MM-DD)", "date", ev.get("date") or default_date or date.today().isoformat()),
                  ("Start (e.g. 14:30 or 2:30pm)", "start", ev.get("start", "")),
                  ("End", "end", ev.get("end", "")),
                  ("Location", "location", ev.get("location", ""))]
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)
        for r, (label, key, val) in enumerate(fields):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=3)
            self.vars[key] = tk.StringVar(value=val)
            ttk.Entry(frm, textvariable=self.vars[key], width=38).grid(row=r, column=1, pady=3, padx=(8, 0))
        ttk.Label(frm, text="Notes").grid(row=len(fields), column=0, sticky="nw", pady=3)
        self.notes = tk.Text(frm, width=38, height=5, wrap="word")
        self.notes.grid(row=len(fields), column=1, pady=3, padx=(8, 0))
        self.notes.insert("1.0", ev.get("notes", ""))
        btns = ttk.Frame(frm)
        btns.grid(row=len(fields) + 1, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="Save", command=self._save).pack(side="right")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.transient(parent)
        self.grab_set()
        self.focus_set()

    def _save(self):
        v = {k: var.get().strip() for k, var in self.vars.items()}
        try:
            if not v["title"]:
                raise ValueError("Title is required.")
            datetime.strptime(v["date"], "%Y-%m-%d")
            v["start"], v["end"] = norm_time(v["start"]), norm_time(v["end"])
            if v["end"] and not v["start"]:
                raise ValueError("Set a start time or clear the end time.")
            if v["end"] and v["end"] <= v["start"]:
                raise ValueError("End time must be after the start time.")
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc), parent=self)
            return
        v["notes"] = self.notes.get("1.0", "end").strip()
        ev = dict(self.event) if self.event else new_event("", "")
        ev.update(v)
        ev["imported"] = False       # user-touched events are never overwritten by a recompile
        if not self.event:
            ev["origin"] = "Manual"
        self.result = ev
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.geometry("1100x650")
        self.minsize(800, 450)
        self.events, self.sources = [], []
        self.path, self.dirty = DEFAULT_PATH, False
        self.q = queue.Queue()
        today = date.today()
        self.cal_month, self.sel_day = today.replace(day=1), today
        self.cells = {}
        self._build_style()
        self._build_menu()
        self._build_ui()
        self._load_default()
        self.protocol("WM_DELETE_WINDOW", self._quit)
        self.refresh()

    # ---- construction -------------------------------------------------------
    def _build_style(self):
        st = ttk.Style(self)
        # work around a Tk 8.6 bug where Treeview tag colours are ignored
        def fixed(opt):
            return [e for e in st.map("Treeview", query_opt=opt) if e[:2] != ("!disabled", "!selected")]
        st.map("Treeview", foreground=fixed("foreground"), background=fixed("background"))
        st.configure("Treeview", rowheight=26)

    def _build_menu(self):
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

    def _build_ui(self):
        pw = ttk.PanedWindow(self, orient="horizontal")
        pw.pack(fill="both", expand=True)

        # left: sources
        left = ttk.Frame(pw, padding=8)
        pw.add(left, weight=1)
        ttk.Label(left, text="Sources (links & documents)", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        box = ttk.Frame(left)
        box.pack(fill="both", expand=True, pady=6)
        self.src_list = tk.Listbox(box, activestyle="none", selectmode="extended")
        sb = ttk.Scrollbar(box, command=self.src_list.yview)
        self.src_list.config(yscrollcommand=sb.set)
        self.src_list.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.src_list.bind("<Delete>", lambda _e: self.remove_source())
        self.src_list.bind("<BackSpace>", lambda _e: self.remove_source())
        row = ttk.Frame(left)
        row.pack(fill="x")
        ttk.Button(row, text="Add link", command=self.add_link).pack(side="left", expand=True, fill="x")
        ttk.Button(row, text="Add documents", command=self.add_docs).pack(side="left", expand=True, fill="x", padx=4)
        ttk.Button(row, text="Remove", command=self.remove_source).pack(side="left", expand=True, fill="x")
        self.compile_btn = ttk.Button(left, text="Compile schedule", command=self.compile_schedule)
        self.compile_btn.pack(fill="x", pady=(10, 0), ipady=6)

        # right: toolbar + calendar / list tabs
        right = ttk.Frame(pw, padding=8)
        pw.add(right, weight=5)
        bar = ttk.Frame(right)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Add event", command=self.add_event).pack(side="left")
        ttk.Button(bar, text="Edit", command=self.edit_event).pack(side="left", padx=4)
        ttk.Button(bar, text="Delete", command=self.delete_event).pack(side="left")
        self.show_past = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show past (list)", variable=self.show_past, command=self.refresh).pack(side="right")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.refresh())
        ttk.Entry(bar, textvariable=self.search, width=22).pack(side="right", padx=8)
        ttk.Label(bar, text="Search:").pack(side="right")

        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)
        cal_tab, list_tab = ttk.Frame(self.tabs), ttk.Frame(self.tabs)
        self.tabs.add(cal_tab, text="Calendar")
        self.tabs.add(list_tab, text="List")
        self._build_calendar(cal_tab)
        self._build_list(list_tab)

        self.status = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status, anchor="w", relief="sunken", padding=(8, 2)).pack(fill="x", side="bottom")

    def _tag_colors(self, tree):
        tree.tag_configure("header", background="#e8eef7", foreground="#1b2a41")
        tree.tag_configure("conflict", background="#ffd9d9", foreground="#7a0000")
        tree.tag_configure("imported", foreground="#35557a")

    def _build_list(self, parent):
        cols = ("time", "title", "location", "source")
        self.tree = ttk.Treeview(parent, columns=cols, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Date")
        for c, t, w in [("time", "Time", 110), ("title", "Event", 300),
                        ("location", "Location", 160), ("source", "Source", 160)]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.column("#0", width=190)
        self._tag_colors(self.tree)
        vs = ttk.Scrollbar(parent, command=self.tree.yview)
        self.tree.config(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self.edit_event())
        self.tree.bind("<Delete>", lambda _e: self.delete_event())

    def _build_calendar(self, parent):
        head = ttk.Frame(parent)
        head.pack(fill="x", pady=(6, 4))
        ttk.Button(head, text="\u25C0", width=3, command=lambda: self.shift_month(-1)).pack(side="left")
        self.month_lbl = ttk.Label(head, font=("TkDefaultFont", 14, "bold"), width=18, anchor="center")
        self.month_lbl.pack(side="left", padx=6)
        ttk.Button(head, text="\u25B6", width=3, command=lambda: self.shift_month(1)).pack(side="left")
        ttk.Button(head, text="Today", command=self.go_today).pack(side="left", padx=10)
        ttk.Label(head, text="Click a day to see its events; double-click a day to add one.",
                  foreground="#666").pack(side="right")

        body = ttk.PanedWindow(parent, orient="horizontal")
        body.pack(fill="both", expand=True)
        self.grid_frame = tk.Frame(body, bg="#c9ced6")
        body.add(self.grid_frame, weight=4)

        side = ttk.Frame(body, padding=(8, 0, 0, 0))
        body.add(side, weight=2)
        self.day_lbl = ttk.Label(side, font=("TkDefaultFont", 11, "bold"), wraplength=260)
        self.day_lbl.pack(anchor="w", pady=(0, 6))
        self.day_tree = ttk.Treeview(side, columns=("time", "title", "location"), show="headings",
                                     selectmode="browse")
        for c, t, w in [("time", "Time", 95), ("title", "Event", 150), ("location", "Location", 90)]:
            self.day_tree.heading(c, text=t)
            self.day_tree.column(c, width=w, anchor="w")
        self._tag_colors(self.day_tree)
        self.day_tree.pack(fill="both", expand=True)
        self.day_tree.bind("<Double-1>", lambda _e: self.edit_event())
        self.day_tree.bind("<Delete>", lambda _e: self.delete_event())
        ttk.Button(side, text="Add event on this day", command=self.add_event).pack(fill="x", pady=(6, 0))

    # ---- calendar view --------------------------------------------------------
    CHIP = {"manual": "#cfeccf", "imported": "#d3e1f6", "conflict": "#ffc9c9"}

    def _events_by_day(self):
        needle = self.search.get().strip().lower()
        out = {}
        for e in self.events:
            if needle and needle not in " ".join((e["title"], e["location"], e["notes"], e["origin"])).lower():
                continue
            out.setdefault(e["date"], []).append(e)
        for lst in out.values():
            lst.sort(key=lambda e: (e["start"] or "00:00", e["title"].lower()))
        return out

    def _style_cell(self, d):
        cell = self.cells.get(d)
        if cell:
            sel = d == self.sel_day
            col = "#1a73e8" if sel else "#c9ced6"
            cell.config(highlightthickness=3 if sel else 1, highlightbackground=col, highlightcolor=col)

    def select_day(self, d, event_id=None):
        old, self.sel_day = self.sel_day, d
        if (d.year, d.month) != (self.cal_month.year, self.cal_month.month):
            self.cal_month = d.replace(day=1)
            self._refresh_calendar()
        else:
            self._style_cell(old)
            self._style_cell(d)
            self._refresh_day_panel(event_id)

    def shift_month(self, delta):
        m = self.cal_month.month - 1 + delta
        self.cal_month = date(self.cal_month.year + m // 12, m % 12 + 1, 1)
        self._refresh_calendar()

    def go_today(self):
        self.sel_day = date.today()
        self.cal_month = self.sel_day.replace(day=1)
        self._refresh_calendar()

    def _refresh_calendar(self):
        gf = self.grid_frame
        for w in gf.winfo_children():
            w.destroy()
        self.cells = {}
        y, m = self.cal_month.year, self.cal_month.month
        self.month_lbl.config(text=self.cal_month.strftime("%B %Y"))
        weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(y, m)
        for c, name in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
            tk.Label(gf, text=name, bg="#e8eef7", fg="#1b2a41", pady=3).grid(row=0, column=c, sticky="nsew", padx=1, pady=1)
            gf.columnconfigure(c, weight=1, uniform="c")
        for r in range(1, 7):
            gf.rowconfigure(r, weight=1 if r <= len(weeks) else 0, uniform="r")
        by_day, conflicts, today = self._events_by_day(), find_conflicts(self.events), date.today()
        small = ("TkDefaultFont", 9)
        for r, week in enumerate(weeks, 1):
            for c, d in enumerate(week):
                in_month = d.month == m
                bg = "#ffffff" if in_month else "#f1f2f4"
                cell = tk.Frame(gf, bg=bg, width=10, height=10, highlightthickness=1)
                cell.pack_propagate(False)
                cell.grid(row=r, column=c, sticky="nsew", padx=1, pady=1)
                self.cells[d] = cell
                self._style_cell(d)
                if d == today:
                    num = tk.Label(cell, text=str(d.day), bg="#1a73e8", fg="white", font=small, padx=5)
                    num.pack(anchor="e", padx=3, pady=2)
                else:
                    num = tk.Label(cell, text=str(d.day), bg=bg, fg="#222" if in_month else "#999", font=small)
                    num.pack(anchor="e", padx=5, pady=2)
                for w in (cell, num):
                    w.bind("<Button-1>", lambda _e, d=d: self.select_day(d))
                    w.bind("<Double-1>", lambda _e, d=d: (self.select_day(d), self.add_event(d)))
                evs = by_day.get(d.isoformat(), [])
                for e in evs[:3]:
                    kind = "conflict" if e["id"] in conflicts else ("imported" if e["imported"] else "manual")
                    text = (e["start"] + " " if e["start"] else "") + e["title"]
                    chip = tk.Label(cell, text=text, bg=self.CHIP[kind], fg="#1b2a41", anchor="w", font=small)
                    chip.pack(fill="x", padx=2, pady=1)
                    chip.bind("<Button-1>", lambda _e, d=d, i=e["id"]: self.select_day(d, i))
                    chip.bind("<Double-1>", lambda _e, d=d, i=e["id"]: (self.select_day(d, i), self.edit_event()))
                if len(evs) > 3:
                    more = tk.Label(cell, text=f"+{len(evs) - 3} more", bg=bg, fg="#555", anchor="w", font=small)
                    more.pack(fill="x", padx=4)
                    more.bind("<Button-1>", lambda _e, d=d: self.select_day(d))
        self._refresh_day_panel()

    def _refresh_day_panel(self, select_id=None):
        evs = self._events_by_day().get(self.sel_day.isoformat(), [])
        conflicts = find_conflicts(self.events)
        self.day_lbl.config(text=f"{self.sel_day.strftime('%A, %b %d, %Y')}  \u2022  {len(evs)} event(s)")
        self.day_tree.delete(*self.day_tree.get_children())
        for e in evs:
            t = "All day" if not e["start"] else e["start"] + (f" - {e['end']}" if e["end"] else "")
            tags = ("conflict",) if e["id"] in conflicts else (("imported",) if e["imported"] else ())
            self.day_tree.insert("", "end", iid=e["id"], values=(t, e["title"], e["location"]), tags=tags)
        if select_id and self.day_tree.exists(select_id):
            self.day_tree.selection_set(select_id)

    # ---- state / persistence ------------------------------------------------
    def _set_dirty(self, flag=True):
        self.dirty = flag
        name = self.path.name if self.path else "Untitled"
        self.title(f"{APP_NAME} - {name}{' *' if flag else ''}")

    def _load_default(self):
        if DEFAULT_PATH.exists():
            try:
                self._read(DEFAULT_PATH)
            except Exception:
                pass
        self._set_dirty(False)

    def _read(self, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.events = data.get("events", [])
        self.sources = data.get("sources", [])
        self.path = Path(path)
        self._refresh_sources()

    def _confirm_discard(self):
        if not self.dirty:
            return True
        ans = messagebox.askyesnocancel(APP_NAME, "Save changes first?")
        if ans is None:
            return False
        if ans:
            return self.file_save()
        return True

    def file_new(self):
        if self._confirm_discard():
            self.events, self.sources, self.path = [], [], None
            self._refresh_sources()
            self.refresh()
            self._set_dirty(False)

    def file_open(self):
        if not self._confirm_discard():
            return
        p = filedialog.askopenfilename(filetypes=[("Schedule files", "*.json"), ("All files", "*.*")])
        if p:
            try:
                self._read(p)
            except Exception as exc:
                messagebox.showerror(APP_NAME, f"Could not open file:\n{exc}")
                return
            self.refresh()
            self._set_dirty(False)

    def file_save(self):
        if not self.path:
            return self.file_save_as()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"version": 1, "events": self.events,
                                             "sources": self.sources}, indent=2), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not save:\n{exc}")
            return False
        self._set_dirty(False)
        self.status.set(f"Saved to {self.path}")
        return True

    def file_save_as(self):
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Schedule files", "*.json")])
        if not p:
            return False
        self.path = Path(p)
        return self.file_save()

    def export(self, kind):
        if not self.events:
            messagebox.showinfo(APP_NAME, "There are no events to export.")
            return
        p = filedialog.asksaveasfilename(defaultextension=f".{kind}", filetypes=[(kind.upper(), f"*.{kind}")])
        if not p:
            return
        evs = sorted(self.events, key=lambda e: (e["date"], e["start"]))
        if kind == "ics":
            export_ics(evs, p)
        else:
            with open(p, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Date", "Start", "End", "Title", "Location", "Notes", "Source"])
                for e in evs:
                    w.writerow([e["date"], e["start"], e["end"], e["title"], e["location"],
                                e["notes"], e["origin"]])
        self.status.set(f"Exported {len(evs)} events to {p}")

    def _quit(self):
        if self._confirm_discard():
            self.destroy()

    # ---- sources ------------------------------------------------------------
    def _refresh_sources(self):
        self.src_list.delete(0, "end")
        for s in self.sources:
            self.src_list.insert("end", ("\U0001F517 " if s["type"] == "link" else "\U0001F4C4 ") + source_label(s))

    def add_link(self):
        url = simpledialog.askstring("Add link", "Paste a URL (web page, .ics feed, or PDF):", parent=self)
        if url and url.strip():
            url = url.strip()
            if not re.match(r"https?://", url):
                url = "https://" + url
            self.sources.append({"type": "link", "value": url})
            self._refresh_sources()
            self._set_dirty()

    def add_docs(self):
        files = filedialog.askopenfilenames(filetypes=[
            ("Schedule documents", "*.txt *.md *.csv *.ics *.docx *.html *.htm *.pdf"), ("All files", "*.*")])
        for f in files:
            self.sources.append({"type": "file", "value": f})
        if files:
            self._refresh_sources()
            self._set_dirty()

    @staticmethod
    def _from_sources(e, srcs):
        if not e.get("imported"):
            return False
        values = {x["value"] for x in srcs}
        labels = {source_label(x) for x in srcs}
        return e.get("source") in values or (not e.get("source") and e.get("origin") in labels)

    def remove_source(self):
        idx = list(self.src_list.curselection())
        if not idx:
            messagebox.showinfo(APP_NAME, "Select a source in the list first.")
            return
        srcs = [self.sources[i] for i in idx]
        n = sum(1 for e in self.events if self._from_sources(e, srcs))
        msg = f"Remove {len(srcs)} source(s)?"
        if n:
            msg += (f"\n\nThis also removes {n} event(s) imported from it. "
                    "Events you added or edited yourself are kept.")
        if not messagebox.askyesno(APP_NAME, msg):
            return
        self.events = [e for e in self.events if not self._from_sources(e, srcs)]
        for i in reversed(idx):
            del self.sources[i]
        self._refresh_sources()
        self.refresh()
        self._set_dirty()

    # ---- compile ------------------------------------------------------------
    def compile_schedule(self):
        if not self.sources:
            messagebox.showinfo(APP_NAME, "Add at least one link or document first.")
            return
        self.compile_btn.state(["disabled"])
        self.status.set("Compiling schedule...")
        threading.Thread(target=self._worker, args=(list(self.sources),), daemon=True).start()
        self.after(100, self._poll)

    def _worker(self, sources):
        parsed, report, failed = [], [], []
        for s in sources:
            label = source_label(s)
            try:
                evs = events_from_source(s)
                parsed.extend(evs)
                line = f"{label}: {len(evs)} event(s) found"
                if not evs and s["type"] == "link":
                    line += ("\n   (Many sites load schedules with JavaScript, which can't be read. "
                             "Try the site's calendar/.ics link, or save the page and add it as a file.)")
                report.append(line)
            except Exception as exc:
                failed.append(s["value"])
                report.append(f"{label}: FAILED - {exc}")
        self.q.put((parsed, report, failed))

    def _poll(self):
        try:
            parsed, report, failed = self.q.get_nowait()
        except queue.Empty:
            self.after(100, self._poll)
            return
        self.events, added = merge(self.events, parsed, failed)
        self.compile_btn.state(["!disabled"])
        self._set_dirty()
        self.refresh()
        self.status.set(f"Compiled: {added} imported event(s) added.")
        messagebox.showinfo("Compile report", "\n".join(report) +
                            "\n\nImported events are blue; double-click any to correct it.")

    # ---- events -------------------------------------------------------------
    def _selected(self):
        tree = self.day_tree if self.tabs.index(self.tabs.select()) == 0 else self.tree
        for iid in tree.selection():
            if not iid.startswith("hdr:"):
                return next((e for e in self.events if e["id"] == iid), None)
        return None

    def add_event(self, day=None):
        if isinstance(day, date):
            default = day.isoformat()
        elif self.tabs.index(self.tabs.select()) == 0:
            default = self.sel_day.isoformat()
        else:
            sel = self.tree.selection()
            default = sel[0][4:] if sel and sel[0].startswith("hdr:") else None
        dlg = EventDialog(self, default_date=default)
        self.wait_window(dlg)
        if dlg.result:
            self.events.append(dlg.result)
            self._set_dirty()
            self.refresh()

    def edit_event(self):
        ev = self._selected()
        if not ev:
            return
        dlg = EventDialog(self, event=ev)
        self.wait_window(dlg)
        if dlg.result:
            self.events[self.events.index(ev)] = dlg.result
            self._set_dirty()
            self.refresh()

    def delete_event(self):
        ev = self._selected()
        if ev and messagebox.askyesno(APP_NAME, f"Delete '{ev['title']}'?"):
            self.events.remove(ev)
            self._set_dirty()
            self.refresh()

    def refresh(self):
        self._refresh_list()
        self._refresh_calendar()

    def _refresh_list(self):
        self.tree.delete(*self.tree.get_children())
        needle = self.search.get().strip().lower()
        today = date.today().isoformat()
        conflicts = find_conflicts(self.events)
        shown = [e for e in self.events
                 if (self.show_past.get() or e["date"] >= today)
                 and (not needle or needle in " ".join(
                     (e["title"], e["location"], e["notes"], e["origin"])).lower())]
        shown.sort(key=lambda e: (e["date"], e["start"] or "00:00", e["title"].lower()))
        last = None
        for e in shown:
            if e["date"] != last:
                last = e["date"]
                try:
                    pretty = date.fromisoformat(last).strftime("%a, %b %d, %Y")
                except ValueError:
                    pretty = last
                self.tree.insert("", "end", iid=f"hdr:{last}", text=pretty, open=True, tags=("header",))
            t = ("All day" if not e["start"] else e["start"] + (f" - {e['end']}" if e["end"] else ""))
            tags = ("conflict",) if e["id"] in conflicts else (("imported",) if e["imported"] else ())
            self.tree.insert(f"hdr:{e['date']}", "end", iid=e["id"], text="",
                             values=(t, e["title"], e["location"], e["origin"] if e["imported"] else "Manual"),
                             tags=tags)
        msg = f"{len(shown)} event(s) shown"
        if conflicts:
            msg += f"  |  {len(conflicts)} event(s) overlap (highlighted red)"
        self.status.set(msg)


if __name__ == "__main__":
    App().mainloop()