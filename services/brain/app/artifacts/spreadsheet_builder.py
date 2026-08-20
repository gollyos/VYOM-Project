from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SheetSpec:
    name: str
    headers: list[str]
    rows: list[list[Any]]
    formulas: dict[str, str] = field(default_factory=dict)
    autofilter: bool = True


@dataclass
class SpreadsheetSpec:
    sheets: list[SheetSpec]
    summary: str = ""


class SpreadsheetBuilder:
    def build(self, *, sheets: list[SheetSpec], summary: str = "") -> SpreadsheetSpec:
        if not sheets:
            raise ValueError("A spreadsheet requires at least one sheet")
        return SpreadsheetSpec(sheets=sheets, summary=summary)
