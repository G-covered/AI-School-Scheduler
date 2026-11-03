"""The Source model: a link or a file that contains schedule information."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

LINK = "link"
FILE = "file"


@dataclass(frozen=True)
class Source:
    type: str      # LINK or FILE
    value: str     # URL or file path

    @classmethod
    def link(cls, url: str) -> "Source":
        url = url.strip()
        if not re.match(r"https?://", url):
            url = "https://" + url
        return cls(LINK, url)

    @classmethod
    def file(cls, path) -> "Source":
        return cls(FILE, str(path))

    @property
    def is_link(self) -> bool:
        return self.type == LINK

    @property
    def label(self) -> str:
        return self.value if self.is_link else Path(self.value).name

    def to_dict(self) -> dict:
        return {"type": self.type, "value": self.value}

    @classmethod
    def from_dict(cls, data: dict) -> "Source":
        return cls(data["type"], data["value"])
