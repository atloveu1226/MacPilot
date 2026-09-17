"""Security policies shared by browser and future external tools."""

from __future__ import annotations

from urllib.parse import urlparse


class BrowserPolicyError(ValueError):
    """Raised when a browser request violates the domain policy."""


def normalize_domain(domain: str) -> str:
    value = domain.strip().lower().rstrip(".")
    if value.startswith("www."):
        value = value[4:]
    return value


def is_allowed_domain(hostname: str, allowed_domains: tuple[str, ...] | list[str]) -> bool:
    host = normalize_domain(hostname)
    return any(
        host == allowed or host.endswith(f".{allowed}")
        for allowed in (normalize_domain(domain) for domain in allowed_domains)
        if allowed
    )


def validate_browser_url(url: str, allowed_domains: tuple[str, ...] | list[str]) -> str:
    """Validate and normalize an HTTP(S) URL against an explicit allowlist."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise BrowserPolicyError("Only http and https URLs are allowed")
    if parsed.username or parsed.password:
        raise BrowserPolicyError("URLs containing embedded credentials are not allowed")
    if not parsed.hostname:
        raise BrowserPolicyError("URL must include a hostname")
    if not is_allowed_domain(parsed.hostname, allowed_domains):
        raise BrowserPolicyError(
            f"Browser domain is not allowlisted: {normalize_domain(parsed.hostname)}"
        )
    return parsed.geturl()
