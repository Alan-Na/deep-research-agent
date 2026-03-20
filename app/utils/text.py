from __future__ import annotations

import re
from html import unescape
from typing import Callable, Iterable, TypeVar
from urllib.parse import urlparse

T = TypeVar("T")

SPACE_RE = re.compile(r"\s+")
PUNCT_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+")


def normalize_whitespace(text: str) -> str:
    # 中文注释：将网页和抓取文本压缩成单行，减少噪声。
    return SPACE_RE.sub(" ", unescape(text or "")).strip()


def truncate_text(text: str, max_chars: int = 400) -> str:
    normalized = normalize_whitespace(text)
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."


def normalize_name(text: str) -> str:
    lowered = normalize_whitespace(text).lower()
    cleaned = PUNCT_RE.sub(" ", lowered)
    return SPACE_RE.sub(" ", cleaned).strip()


def extract_domain(url: str | None) -> str | None:
    if not url:
        return None
    return urlparse(url).netloc.lower() or None


def dedupe_items(items: Iterable[T], key_func: Callable[[T], str]) -> list[T]:
    # 中文注释：保留首次出现的元素，适用于证据和新闻去重。
    seen: set[str] = set()
    output: list[T] = []
    for item in items:
        key = key_func(item)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def tokenize_for_similarity(text: str) -> set[str]:
    cleaned = normalize_name(text)
    return {token for token in re.split(r"\d+|\s+", cleaned) if token}
