"""Allowlisted, read-only browser tools for Phase 3."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.tools import StructuredTool
from langchain_core.tools import tool

from macpilot.core.config import Settings
from macpilot.phase3.security import BrowserPolicyError, validate_browser_url


INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"system\s+message|developer\s+message", re.I),
    re.compile(r"reveal\s+(your|the)\s+(prompt|instructions)", re.I),
    re.compile(r"disable\s+(your\s+)?safety|bypass\s+safety", re.I),
)


def detect_prompt_injection(text: str) -> list[str]:
    """Return warnings for common instruction-like text found in web content."""
    warnings: list[str] = []
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            warnings.append(f"Matched untrusted webpage pattern: {pattern.pattern}")
    return warnings


def make_browser_tools(
    settings: Settings,
    audit_store: Any | None = None,
    task_id: str | None = None,
) -> list[StructuredTool]:
    def audit(tool_name: str, input_data: Any, output_data: Any) -> None:
        if audit_store is not None:
            audit_store.append_event(
                "tool_call",
                {"tool_name": tool_name, "input": input_data, "output": output_data},
                task_id=task_id,
            )

    def result(tool_name: str, input_data: Any, output_data: dict[str, Any]) -> dict[str, Any]:
        audit(tool_name, input_data, output_data)
        return output_data

    @tool
    def fetch_page(url: str) -> dict[str, Any]:
        """Fetch visible text from an allowlisted webpage in read-only mode."""
        try:
            validated_url = validate_browser_url(url, settings.allowed_browser_domains)
        except BrowserPolicyError as error:
            return result(
                "fetch_page",
                {"url": url},
                {"ok": False, "error": str(error), "policy_denied": True},
            )

        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(
                        validated_url,
                        wait_until="domcontentloaded",
                        timeout=settings.browser_timeout_ms,
                    )
                    text = page.locator("body").inner_text(timeout=settings.browser_timeout_ms)
                    warnings = detect_prompt_injection(text)
                    if warnings and audit_store is not None:
                        audit_store.append_event(
                            "prompt_injection_detected",
                            {"url": validated_url, "warnings": warnings},
                            task_id=task_id,
                        )
                    return result(
                        "fetch_page",
                        {"url": validated_url},
                        {
                            "ok": True,
                            "url": page.url,
                            "title": page.title(),
                            "text": text[: settings.max_file_bytes],
                            "truncated": len(text) > settings.max_file_bytes,
                            "untrusted_content": True,
                            "prompt_injection_warnings": warnings,
                        },
                    )
                finally:
                    browser.close()
        except Exception as error:
            return result(
                "fetch_page",
                {"url": validated_url},
                {"ok": False, "error": f"Browser fetch failed: {error}"},
            )

    return [fetch_page]
