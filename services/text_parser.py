"""Turn free text and iCalendar text into Event objects."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from models.event import Event

_I = re.I
_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
          r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b")
_WD = (r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
       r"mon|tues?|wed|thu(?:rs?)?|fri)\b\.?")
_NOT_TIME = r"(?!\d|:|\s*[ap]\.?m\b)"
_TOK = r"\d{1,2}:\d{2}\s*(?:[ap]\.?m\b\.?)?|\d{1,2}\s*[ap]\.?m\b\.?"


class TextParser:
    """Heuristically finds dates, times, titles and locations in free text."""

    MONTH_NUM = {m: i for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
    WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    MAX_LINE = 400
    MAX_TITLE = 120

    WEEKDAY_RX = re.compile(rf"\b{_WD},?", _I)
    DATE_PATTERNS = [
        ("iso", re.compile(r"\b(?P<y>\d{4})-(?P<mo>\d{1,2})-(?P<d>\d{1,2})\b")),
        ("us", re.compile(r"\b(?P<mo>\d{1,2})/(?P<d>\d{1,2})(?:/(?P<y>\d{2,4}))?\b")),
        ("mdy", re.compile(rf"\b(?P<mon>{_MONTH})\.?\s+(?P<d>\d{{1,2}}){_NOT_TIME}(?:st|nd|rd|th)?"
                           rf"(?:,?\s+(?P<y>\d{{4}})\b)?", _I)),
        ("dmy", re.compile(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<mon>{_MONTH})\.?"
                           rf"(?:,?\s+(?P<y>\d{{4}})\b)?", _I)),
        ("rel", re.compile(r"\b(?P<rel>today|tomorrow)\b", _I)),
        ("wd", re.compile(rf"\b(?:(?P<pre>next|this)\s+)?(?P<wd>{_WD})", _I)),
    ]
    RANGE_RX = re.compile(
        rf"(?:\bfrom\s+)?\b(?P<a>\d{{1,2}}(?::\d{{2}})?\s*(?:[ap]\.?m\b\.?)?)\s*"
        rf"(?:-|\u2013|\u2014|to|until|till)\s*(?P<b>{_TOK})", _I)
    SINGLE_RX = re.compile(rf"(?:(?:\bat|@)\s*)?(?P<t>{_TOK})", _I)
    LOC_RX = re.compile(r"(?:@|\bat\b|\blocation\s*:)\s*(?P<loc>[^,;|()\u2013\u2014]+)", _I)

    # ---- times --------------------------------------------------------------
    @staticmethod
    def parse_time_token(tok: str, default_ap: str | None = None):
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

    @staticmethod
    def format_time(hm) -> str:
        return f"{hm[0]:02d}:{hm[1]:02d}"

    @classmethod
    def normalize_time(cls, text: str) -> str:
        """Lenient user input -> 'HH:MM' or '' (raises ValueError if invalid)."""
        text = text.strip()
        if not text:
            return ""
        t = cls.parse_time_token(text)
        if t is None:
            raise ValueError(f"Invalid time: {text!r}")
        return cls.format_time(t)

    def find_times(self, text: str):
        """Return (start, end, remaining_text); start/end are 'HH:MM' or ''."""
        m = self.RANGE_RX.search(text)
        if m:
            b_ap = re.search(r"([ap])\.?m", m.group("b").lower())
            t2 = self.parse_time_token(m.group("b"))
            t1 = self.parse_time_token(m.group("a"), b_ap.group(1) if b_ap else None)
            if t1 and t2:
                if t1 > t2 and b_ap and b_ap.group(1) == "p" and t1[0] >= 12:
                    t1 = (t1[0] - 12, t1[1])               # e.g. "11-1pm" -> 11am-1pm
                return (self.format_time(t1), self.format_time(t2),
                        text[:m.start()] + " " + text[m.end():])
        m = self.SINGLE_RX.search(text)
        if m:
            t = self.parse_time_token(m.group("t"))
            if t:
                return self.format_time(t), "", text[:m.start()] + " " + text[m.end():]
        return "", "", text

    # ---- dates --------------------------------------------------------------
    @staticmethod
    def _with_year(mo, d, y, today: date) -> date:
        if y is None:
            dt = date(today.year, mo, d)
            if (dt - today).days < -90:          # a date well in the past -> assume next year
                dt = date(today.year + 1, mo, d)
            return dt
        y = int(y)
        return date(y + 2000 if y < 100 else y, mo, d)

    def _resolve(self, kind: str, m: re.Match, today: date):
        g = m.groupdict()
        if kind == "iso":
            return date(int(g["y"]), int(g["mo"]), int(g["d"]))
        if kind == "us":
            return self._with_year(int(g["mo"]), int(g["d"]), g["y"], today)
        if kind in ("mdy", "dmy"):
            return self._with_year(self.MONTH_NUM[g["mon"][:3].lower()], int(g["d"]), g["y"], today)
        if kind == "rel":
            return today + timedelta(days=1 if g["rel"].lower() == "tomorrow" else 0)
        if kind == "wd":
            idx = next(i for i, n in enumerate(self.WEEKDAYS) if n.startswith(g["wd"].lower()[:3]))
            delta = (idx - today.weekday()) % 7
            if delta == 0 and (g["pre"] or "").lower() == "next":
                delta = 7
            return today + timedelta(days=delta)
        return None

    def find_date(self, text: str, today: date):
        """Return (date, remaining_text) for the earliest valid date in text, else (None, text)."""
        found = []
        for kind, rx in self.DATE_PATTERNS:
            for m in rx.finditer(text):
                try:
                    d = self._resolve(kind, m, today)
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
        rest = self.WEEKDAY_RX.sub(" ", rest)             # drop stray weekday names
        return d, rest

    # ---- titles -------------------------------------------------------------
    @staticmethod
    def clean_title(s: str) -> str:
        s = re.sub(r"^\s*(?:[-*\u2022>]+|\d+[.)])\s*", "", s)
        for _ in range(3):
            s = s.strip(" \t-:|,;\u2013\u2014@()[]")
            s = re.sub(r"^(?:on|at|from|by)\s+|\s+(?:on|at|from|by|until|till|to)$", "", s, flags=_I)
        return re.sub(r"\s{2,}", " ", s).strip()

    # ---- main entry point ---------------------------------------------------
    def parse(self, text: str, origin: str, today: date | None = None) -> list[Event]:
        """Turn free text into events, line by line."""
        today = today or date.today()
        events, ctx_date = [], None
        for raw in text.splitlines():
            line = raw.strip()
            if not line or len(line) > self.MAX_LINE:
                continue
            d, rest = self.find_date(line, today)
            start, end, rest = self.find_times(rest)
            loc = ""
            lm = self.LOC_RX.search(rest)
            if lm:
                loc = lm.group("loc").strip(" .")
                rest = rest[:lm.start()] + " " + rest[lm.end():]
            title = self.clean_title(rest)
            if d:
                ctx_date = d
            day = d or ctx_date
            if not day or not (d or start):
                continue
            if not start and not title:          # a bare date heading: just sets context
                continue
            events.append(Event(
                title=(title or "Untitled event")[:self.MAX_TITLE], date=day.isoformat(),
                start=start, end=end, location=loc, notes=f"From: {line[:300]}",
                origin=origin, imported=True))
        return events


class ICalParser:
    """Reads VEVENT entries from iCalendar (.ics) text."""

    @staticmethod
    def _to_datetime(value: str):
        value = value.strip()
        if re.fullmatch(r"\d{8}", value):
            return datetime.strptime(value, "%Y%m%d"), True
        utc = value.endswith("Z")
        dt = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
        if utc:
            dt = dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        return dt, False

    @staticmethod
    def _unescape(s: str) -> str:
        return re.sub(r"\\([,;nN\\])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), s)

    def _build_event(self, props: dict, origin: str) -> Event | None:
        if "DTSTART" not in props:
            return None
        start, all_day = self._to_datetime(props["DTSTART"])
        end = self._to_datetime(props["DTEND"])[0] if "DTEND" in props else None
        same_day_end = end is not None and end.date() == start.date()
        return Event(
            title=self._unescape(props.get("SUMMARY", "Untitled event")),
            date=start.date().isoformat(),
            start="" if all_day else start.strftime("%H:%M"),
            end="" if (all_day or not same_day_end) else end.strftime("%H:%M"),
            location=self._unescape(props.get("LOCATION", "")),
            notes=self._unescape(props.get("DESCRIPTION", ""))[:500],
            origin=origin, imported=True)

    def parse(self, text: str, origin: str) -> list[Event]:
        text = re.sub(r"\r?\n[ \t]", "", text)           # unfold long lines
        events, cur = [], None
        for line in text.splitlines():
            if line.startswith("BEGIN:VEVENT"):
                cur = {}
            elif line.startswith("END:VEVENT") and cur is not None:
                try:
                    ev = self._build_event(cur, origin)
                    if ev:
                        events.append(ev)
                except ValueError:
                    pass
                cur = None
            elif cur is not None and ":" in line:
                key, _, val = line.partition(":")
                cur[key.split(";")[0].upper()] = val
        return events
