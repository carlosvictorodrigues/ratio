from __future__ import annotations

from html import unescape
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup


GOOGLE_SEARCH_URL = "https://www.google.com/search"
LEGISLATION_SITE_FILTER = (
    "(site:planalto.gov.br OR site:senado.leg.br OR site:camara.leg.br OR site:lexml.gov.br)"
)


def build_google_legislation_query(terms: str) -> str:
    cleaned = " ".join(str(terms or "").split()).strip()
    return f"{LEGISLATION_SITE_FILTER} legislação brasileira {cleaned}".strip()


def _extract_google_href(raw_href: str) -> str:
    href = str(raw_href or "").strip()
    if href.startswith("/url?"):
        parsed = urlparse(href)
        q = parse_qs(parsed.query).get("q", [""])
        return unescape(q[0] or "")
    return href


def _infer_legislation_fields(title: str, snippet: str, url: str) -> dict[str, str]:
    text = " ".join(part for part in [title, snippet, url] if part)
    lowered = text.lower()

    diploma = ""
    for marker, label in (
        ("constituição federal", "CF"),
        ("codigo de defesa do consumidor", "CDC"),
        ("código de defesa do consumidor", "CDC"),
        ("codigo civil", "CC"),
        ("código civil", "CC"),
        ("codigo de processo civil", "CPC"),
        ("código de processo civil", "CPC"),
        ("clt", "CLT"),
    ):
        if marker in lowered:
            diploma = label
            break

    article = ""
    import re

    match = re.search(r"\bart\.?\s*(\d+[A-Za-z0-9º°\-]*)", text, re.IGNORECASE)
    if match:
        article = match.group(1)

    return {"diploma": diploma, "article": article}


def parse_google_search_results(html: str, *, limit: int = 10) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for anchor in soup.select("a[href]"):
        url = _extract_google_href(anchor.get("href", ""))
        if not url.startswith("http"):
            continue
        if "google." in urlparse(url).netloc:
            continue
        if url in seen_urls:
            continue

        title = anchor.get_text(" ", strip=True)
        if not title:
            continue

        snippet_node = anchor.find_next("div")
        snippet = ""
        if snippet_node is not None:
            snippet = snippet_node.get_text(" ", strip=True)
            if snippet == title:
                snippet = ""

        inferred = _infer_legislation_fields(title, snippet, url)
        rows.append(
            {
                "doc_id": url,
                "url": url,
                "title": title,
                "snippet": snippet,
                "diploma": inferred["diploma"],
                "article": inferred["article"],
                "fonte": "google_search",
            }
        )
        seen_urls.add(url)
        if len(rows) >= limit:
            break

    return rows


def search_google_legislation(
    terms: str,
    *,
    limit: int = 10,
    get_fn: Callable[..., Any] | None = None,
    timeout_seconds: int = 15,
) -> list[dict[str, Any]]:
    requester = get_fn or requests.get
    response = requester(
        GOOGLE_SEARCH_URL,
        params={"q": build_google_legislation_query(terms), "hl": "pt-BR", "num": str(limit)},
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        },
        timeout=timeout_seconds,
    )
    if hasattr(response, "raise_for_status"):
        response.raise_for_status()
    html = getattr(response, "text", "")
    return parse_google_search_results(html, limit=limit)
