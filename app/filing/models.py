from __future__ import annotations

from dataclasses import dataclass, field


PERIODIC_FORMS = {"10-K", "10-Q", "20-F", "40-F"}
SUPPLEMENTAL_FORMS = {"8-K", "6-K"}
SUPPORTED_FORMS = PERIODIC_FORMS | SUPPLEMENTAL_FORMS


@dataclass
class FilingSection:
    filing_type: str
    filed_at: str
    fiscal_period: str | None
    section_type: str
    heading: str
    text: str
    url: str
    title: str
    order: int


@dataclass
class ParsedFiling:
    filing_type: str
    filed_at: str
    title: str
    url: str
    fiscal_period: str | None
    sections: list[FilingSection] = field(default_factory=list)


@dataclass(frozen=True)
class SectionMatch:
    section: FilingSection
    snippet: str
    score: int
