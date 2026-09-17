"""Compatibility import; new code should use :mod:`macpilot.phase3.security`."""

from macpilot.phase3.security import (
    BrowserPolicyError,
    is_allowed_domain,
    normalize_domain,
    validate_browser_url,
)

__all__ = [
    "BrowserPolicyError",
    "is_allowed_domain",
    "normalize_domain",
    "validate_browser_url",
]
