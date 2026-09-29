"""Security policies shared by browser and future external tools."""

from __future__ import annotations

from urllib.parse import urlparse
from dataclasses import dataclass, field


class BrowserPolicyError(ValueError):
    """Raised when a browser request violates the domain policy."""


def normalize_domain(domain: str) -> str:
    value = domain.strip().lower().rstrip(".")
    return value


def is_allowed_domain(hostname: str, allowed_domains: tuple[str, ...] | list[str]) -> bool:
    host = normalize_domain(hostname)
    return any(host == normalize_domain(domain) for domain in allowed_domains if domain)


def validate_browser_url(url: str, allowed_domains: tuple[str, ...] | list[str]) -> str:
    """Validate and normalize an HTTP(S) URL against an explicit allowlist."""
    parsed = urlparse(url.strip())
    if parsed.scheme != "https":
        raise BrowserPolicyError("Only HTTPS URLs are allowed")
    if parsed.username or parsed.password:
        raise BrowserPolicyError("URLs containing embedded credentials are not allowed")
    if not parsed.hostname:
        raise BrowserPolicyError("URL must include a hostname")
    if not is_allowed_domain(parsed.hostname, allowed_domains):
        raise BrowserPolicyError(
            f"Browser domain is not allowlisted: {normalize_domain(parsed.hostname)}"
        )
    return parsed.geturl()


@dataclass
class DomainAllowlist:
    """Runtime allowlist used by browser tools and the local approval API."""

    permanent: set[str] = field(default_factory=set)
    temporary: set[str] = field(default_factory=set)

    @classmethod
    def from_domains(cls, domains: tuple[str, ...] | list[str]) -> "DomainAllowlist":
        return cls(permanent={normalize_domain(item) for item in domains if item})

    def contains(self, hostname: str) -> bool:
        host = normalize_domain(hostname)
        return host in self.permanent or host in self.temporary

    def add_temporary(self, domain: str) -> str:
        normalized = normalize_domain(domain)
        if not normalized or "." not in normalized or "*" in normalized:
            raise BrowserPolicyError("A precise domain is required; wildcards are not allowed")
        self.temporary.add(normalized)
        return normalized

    def remove_temporary(self, domain: str) -> None:
        self.temporary.discard(normalize_domain(domain))
