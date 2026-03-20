from __future__ import annotations

from typing import Any

import requests

from app.config import get_settings

DEFAULT_HEADERS = {
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def build_headers(user_agent: str | None = None) -> dict[str, str]:
    settings = get_settings()
    headers = dict(DEFAULT_HEADERS)
    headers["User-Agent"] = user_agent or settings.sec_user_agent
    return headers

def request_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    response = requests.get(
        url,
        params=params,
        headers=headers or build_headers(),
        timeout=timeout or settings.request_timeout,
    )
    response.raise_for_status()
    return response.json()


def request_text(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int | None = None,
) -> str:
    settings = get_settings()
    response = requests.get(
        url,
        params=params,
        headers=headers or build_headers(),
        timeout=timeout or settings.request_timeout,
    )
    response.raise_for_status()
    return response.text
