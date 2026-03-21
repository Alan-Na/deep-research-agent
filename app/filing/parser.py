from __future__ import annotations

import re
from html import unescape

from bs4 import BeautifulSoup

from app.filing.models import FilingSection, ParsedFiling
from app.tools.base import FilingDocumentRecord
from app.utils.text import normalize_name, normalize_whitespace

PART_RE = re.compile(r"^part\s+([ivx]+)\b", re.IGNORECASE)
ITEM_RE = re.compile(r"^(?:part\s+([ivx]+)\s+)?item\s+([0-9]+[a-z]?)\.?\s*(.*)$", re.IGNORECASE)
DATE_RE = re.compile(
    r"(?:quarterly period|transition report|fiscal (?:year|quarter)|three months|six months|nine months|year|period)\s+(?:ended|ending)\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)

FORM_SECTION_MAP = {
    "10-K": {
        (None, "1a"): "risk_factors",
        (None, "7"): "mdna",
        (None, "7a"): "market_risk",
        (None, "8"): "financial_statements",
    },
    "10-Q": {
        ("i", "1"): "financial_statements",
        ("i", "2"): "mdna",
        ("i", "3"): "market_risk",
        ("i", "4"): "controls",
        ("ii", "1a"): "risk_factors",
    },
}

MIN_SECTION_LENGTHS = {
    "overview": 40,
    "mdna": 80,
    "results_of_operations": 60,
    "liquidity": 50,
    "risk_factors": 40,
    "guidance": 35,
    "segment_performance": 35,
    "earnings_release": 40,
    "financial_statements": 60,
    "controls": 40,
    "market_risk": 40,
}

KEYWORD_SECTION_MAP = [
    ("management s discussion and analysis", "mdna"),
    ("management discussion and analysis", "mdna"),
    ("results of operations", "results_of_operations"),
    ("liquidity and capital resources", "liquidity"),
    ("financial condition and results of operations", "mdna"),
    ("risk factors", "risk_factors"),
    ("guidance", "guidance"),
    ("outlook", "guidance"),
    ("segment", "segment_performance"),
    ("financial statements", "financial_statements"),
    ("controls and procedures", "controls"),
    ("market risk", "market_risk"),
    ("earnings release", "earnings_release"),
    ("press release", "earnings_release"),
    ("forward looking statements", "guidance"),
    ("business overview", "overview"),
]


def parse_filing_html(record: FilingDocumentRecord) -> ParsedFiling:
    lines = _html_to_lines(record.raw_html or record.text)
    fiscal_period = _derive_fiscal_period(lines, record.filed_at)
    sections = tag_filing_sections(
        lines=lines,
        filing_type=record.form,
        filed_at=record.filed_at,
        title=record.title,
        url=record.url,
        fiscal_period=fiscal_period,
    )
    return ParsedFiling(
        filing_type=record.form,
        filed_at=record.filed_at,
        title=record.title,
        url=record.url,
        fiscal_period=fiscal_period,
        sections=sections,
    )


def tag_filing_sections(
    *,
    lines: list[str],
    filing_type: str,
    filed_at: str,
    title: str,
    url: str,
    fiscal_period: str | None,
) -> list[FilingSection]:
    sections: list[FilingSection] = []
    current_heading = "Overview"
    current_section_type = "overview"
    current_lines: list[str] = []
    current_part: str | None = None
    order = 0

    def flush_section() -> None:
        nonlocal current_heading, current_section_type, current_lines, order
        text = "\n".join(current_lines).strip()
        if not text:
            current_lines = []
            return
        min_chars = MIN_SECTION_LENGTHS.get(current_section_type, 60)
        if len(text) >= min_chars:
            sections.append(
                FilingSection(
                    filing_type=filing_type,
                    filed_at=filed_at,
                    fiscal_period=fiscal_period,
                    section_type=current_section_type,
                    heading=current_heading,
                    text=text,
                    url=url,
                    title=title,
                    order=order,
                )
            )
            order += 1
        current_lines = []

    for line in lines:
        part_match = PART_RE.match(line)
        if part_match and len(line.split()) <= 6:
            current_part = part_match.group(1).lower()
            continue

        heading_info = _detect_heading(line, filing_type, current_part)
        if heading_info:
            flush_section()
            current_heading = line
            current_section_type = heading_info
            continue

        current_lines.append(line)

    flush_section()

    sections = _dedupe_sections(sections)
    if not sections:
        fallback_text = "\n".join(lines).strip()
        if fallback_text:
            sections.append(
                FilingSection(
                    filing_type=filing_type,
                    filed_at=filed_at,
                    fiscal_period=fiscal_period,
                    section_type="overview",
                    heading="Overview",
                    text=fallback_text,
                    url=url,
                    title=title,
                    order=0,
                )
            )
    return sections


def _html_to_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    removable_tags = {"script", "style", "noscript", "svg", "header", "footer"}
    for tag in soup.find_all(True):
        if tag.name in removable_tags or str(tag.name).lower().endswith(":header"):
            tag.decompose()

    for br in soup.find_all("br"):
        br.replace_with("\n")

    for tr in soup.find_all("tr"):
        cells = [normalize_whitespace(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
        row_text = " | ".join(cell for cell in cells if cell)
        if row_text:
            tr.replace_with(f"\n{row_text}\n")

    raw_text = soup.get_text("\n")
    lines: list[str] = []
    previous = ""
    for raw_line in raw_text.splitlines():
        line = normalize_whitespace(unescape(raw_line))
        if not line or _looks_like_noise(line):
            continue
        if line == previous:
            continue
        lines.append(line)
        previous = line
    return lines


def _looks_like_noise(line: str) -> bool:
    lowered = normalize_name(line)
    if not lowered:
        return True
    if lowered in {"table of contents", "index", "document", "exhibit"}:
        return True
    if lowered.startswith("https") or lowered.startswith("www sec gov"):
        return True
    if re.fullmatch(r"[0-9.\- ]+", line):
        return True
    return False


def _detect_heading(line: str, filing_type: str, current_part: str | None) -> str | None:
    item_match = ITEM_RE.match(line)
    if item_match:
        inline_part = (item_match.group(1) or current_part or "").lower() or None
        item_number = item_match.group(2).lower()
        section_type = FORM_SECTION_MAP.get(filing_type, {}).get((inline_part, item_number))
        if section_type:
            return section_type
        remainder_type = _keyword_section_type(item_match.group(3))
        if remainder_type:
            return remainder_type
        if item_number in {"1", "2", "5", "7", "7a", "8", "18"}:
            return "overview"

    normalized = normalize_name(line)
    word_count = len(normalized.split())
    if word_count == 0 or len(line) > 180:
        return None

    keyword_section_type = _keyword_section_type(line)
    if keyword_section_type:
        return keyword_section_type

    if word_count <= 12 and line == line.upper() and re.search(r"[A-Z]", line):
        return "overview"

    return None


def _derive_fiscal_period(lines: list[str], filed_at: str) -> str | None:
    search_space = "\n".join(lines[:120])
    match = DATE_RE.search(search_space)
    if match:
        return match.group(1)
    return filed_at or None


def _dedupe_sections(sections: list[FilingSection]) -> list[FilingSection]:
    seen: dict[tuple[str, str], FilingSection] = {}
    for section in sections:
        key = (section.section_type, normalize_name(section.heading))
        existing = seen.get(key)
        if existing is None or len(section.text) > len(existing.text):
            seen[key] = section
    ordered = sorted(seen.values(), key=lambda section: section.order)
    for index, section in enumerate(ordered):
        section.order = index
    return ordered


def _keyword_section_type(line: str) -> str | None:
    normalized = normalize_name(line)
    word_count = len(normalized.split())
    if not normalized or word_count > 18:
        return None
    if line.endswith('.') or '$' in line or '%' in line:
        return None
    for keyword, section_type in KEYWORD_SECTION_MAP:
        if keyword in normalized:
            return section_type
    return None
