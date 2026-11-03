"""Read links and documents and turn them into events."""
from __future__ import annotations

import io
import re
import ssl
import urllib.error
import urllib.request
import zipfile
from html.parser import HTMLParser
from pathlib import Path

from models.event import Event
from models.source import Source
from services.text_parser import ICalParser, TextParser


class HtmlTextExtractor(HTMLParser):
    """Strips tags from HTML, keeping block structure as line breaks."""

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

    @classmethod
    def extract(cls, html: str) -> str:
        p = cls()
        p.feed(html)
        text = "".join(p.out)
        return "\n".join(re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in text.splitlines())


class DocumentReader:
    """Fetches a Source (web link or local file) and extracts its events."""

    USER_AGENT = "Mozilla/5.0 SmartScheduler"
    TIMEOUT = 20
    MAX_BYTES = 8_000_000
    SSL_HELP = ("SSL certificate check failed. On macOS, open /Applications/Python 3.x/ and run "
                "'Install Certificates.command', or run:  pip install certifi  and restart the app.")

    def __init__(self, text_parser: TextParser | None = None,
                 ical_parser: ICalParser | None = None):
        self.text_parser = text_parser or TextParser()
        self.ical_parser = ical_parser or ICalParser()

    # ---- public API ---------------------------------------------------------
    def read(self, source: Source) -> list[Event]:
        if source.is_link:
            data, ctype = self._fetch(source.value)
            events = self.parse_bytes(data, source.value, ctype, source.label)
        else:
            path = Path(source.value)
            events = self.parse_bytes(path.read_bytes(), path.name, "", source.label)
        for e in events:
            e.source = source.value
        return events

    def parse_bytes(self, data: bytes, name: str, content_type: str | None, origin: str) -> list[Event]:
        low = name.lower().split("?")[0]
        ctype = (content_type or "").lower()
        if low.endswith(".pdf") or "pdf" in ctype:
            return self.text_parser.parse(self.pdf_to_text(data), origin)
        if low.endswith(".docx"):
            return self.text_parser.parse(self.docx_to_text(data), origin)
        text = self.decode(data)
        if low.endswith(".ics") or "calendar" in ctype or text.lstrip().startswith("BEGIN:VCALENDAR"):
            return self.ical_parser.parse(text, origin)
        if low.endswith((".html", ".htm")) or "html" in ctype or "<html" in text[:2000].lower():
            text = HtmlTextExtractor.extract(text)
        return self.text_parser.parse(text, origin)

    # ---- network ------------------------------------------------------------
    @staticmethod
    def _ssl_context() -> ssl.SSLContext:
        """Use certifi's CA bundle when available (fixes python.org Python on macOS)."""
        try:
            import certifi
            return ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            return ssl.create_default_context()

    def _fetch(self, url: str):
        req = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=self.TIMEOUT, context=self._ssl_context()) as r:
                return r.read(self.MAX_BYTES), r.headers.get("Content-Type")
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLError):
                raise RuntimeError(self.SSL_HELP)
            raise

    # ---- format converters --------------------------------------------------
    @staticmethod
    def pdf_to_text(data: bytes) -> str:
        try:
            from pypdf import PdfReader
        except ImportError:
            raise RuntimeError("PDF support needs pypdf  (pip install pypdf)")
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(data)).pages)

    @staticmethod
    def docx_to_text(data: bytes) -> str:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf8", "replace")
        paras = []
        for p in xml.split("</w:p>"):
            parts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>|(<w:tab\s*/>)", p)
            paras.append("".join(a if a else "\t" for a, _ in parts))
        text = "\n".join(paras)
        return (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&apos;", "'"))

    @staticmethod
    def decode(data: bytes, charset: str | None = None) -> str:
        for enc in (charset, "utf-8-sig", "latin-1"):
            if enc:
                try:
                    return data.decode(enc)
                except (UnicodeDecodeError, LookupError):
                    continue
        return data.decode("utf-8", "replace")
