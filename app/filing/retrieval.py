from __future__ import annotations

import re

from app.filing.models import FilingSection, SectionMatch
from app.utils.text import normalize_name

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def split_sentences(text: str) -> list[str]:
    sentences = [sentence.strip() for sentence in SENTENCE_RE.split(text or "")]
    return [sentence for sentence in sentences if len(sentence) >= 20]


def retrieve_section_matches(
    sections: list[FilingSection],
    *,
    keywords: list[str],
    section_types: set[str] | None = None,
    filing_types: set[str] | None = None,
    fiscal_period: str | None = None,
    limit: int = 5,
) -> list[SectionMatch]:
    filtered_sections = [
        section
        for section in sections
        if (not section_types or section.section_type in section_types)
        and (not filing_types or section.filing_type in filing_types)
        and (not fiscal_period or section.fiscal_period == fiscal_period)
    ]
    if not filtered_sections and section_types:
        filtered_sections = [section for section in sections if not filing_types or section.filing_type in filing_types]

    matches: list[SectionMatch] = []
    for section in filtered_sections:
        for sentence in split_sentences(section.text):
            score = _score_sentence(sentence, section.heading, keywords)
            if score <= 0:
                continue
            matches.append(SectionMatch(section=section, snippet=sentence, score=score))

    matches.sort(key=lambda item: (-item.score, item.section.order, len(item.snippet)))
    deduped: list[SectionMatch] = []
    seen: set[str] = set()
    for match in matches:
        key = f"{match.section.section_type}|{normalize_name(match.snippet)}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(match)
        if len(deduped) >= limit:
            break
    return deduped


def _score_sentence(sentence: str, heading: str, keywords: list[str]) -> int:
    normalized_sentence = normalize_name(sentence)
    normalized_heading = normalize_name(heading)
    score = 0
    for keyword in keywords:
        normalized_keyword = normalize_name(keyword)
        if not normalized_keyword:
            continue
        if normalized_keyword in normalized_sentence:
            score += 3 if " " in normalized_keyword else 2
        if normalized_keyword in normalized_heading:
            score += 1
    if score > 0 and ("$" in sentence or "%" in sentence):
        score += 1
    return score
