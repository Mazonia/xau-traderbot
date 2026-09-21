"""
Utilities for news normalization, hashing, and deduplication.
"""

import re
import hashlib


def normalize_headline(headline: str) -> str:
    """
    Normalize headline by stripping source attribution tags, lowercasing,
    and removing non-alphanumeric punctuation.
    """
    if not headline:
        return ""

    # Strip trailing news agency / publisher indicators like " - Reuters", " | Bloomberg", " - CNBC", etc.
    cleaned = re.sub(
        r"\s*[-|–—:]\s*(Reuters|Bloomberg|CNBC|FXStreet|Investing\.com|MarketWatch|Associated Press|AP|Financial Times|FT|Yahoo Finance|WSJ|BenZinga|Zacks|StreetInsider|Seeking Alpha).*$",
        "",
        headline,
        flags=re.IGNORECASE,
    )
    # Lowercase & collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    # Strip punctuation characters while preserving spaces and alphanumerics
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    return cleaned.strip()


def compute_news_hash(headline: str, url: str = "") -> str:
    """
    Compute a deterministic SHA-256 hash for deduplicating news articles.
    Prefers normalized headline, falls back to normalized URL if headline is empty.
    """
    norm = normalize_headline(headline)
    if not norm and url:
        return hashlib.sha256(url.strip().lower().encode("utf-8")).hexdigest()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def is_headline_relevant(headline: str, summary: str = "", keywords: list[str] | None = None) -> bool:
    """
    Check if an article text is relevant using regex word boundaries to avoid
    false-positive partial matches (e.g. 'war' in 'warms', 'CPI' in 'recipe').
    """
    if not keywords:
        return False

    text = f"{headline} {summary}".lower()
    for kw in keywords:
        kw = kw.strip().lower()
        if not kw:
            continue
        # Support optional trailing 's' for plurals (e.g., war -> wars, tariff -> tariffs)
        pattern = r"\b" + re.escape(kw) + r"s?\b"
        if re.search(pattern, text):
            return True
    return False
