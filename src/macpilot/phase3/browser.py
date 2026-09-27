"""Allowlisted browser tools for research and safe form drafting.

The browser is still conservative by design: navigation and draft filling are
available only on allowlisted domains, while final form submission is not
exposed as an agent action yet. A submitted application is an external side
effect and will be added behind a dedicated approval-and-resume executor.
"""

from __future__ import annotations

import re
import json
from pathlib import Path
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
    browser_state: dict[str, Any] = {"context": None, "page": None, "fields": {}}

    def _state_path() -> Path:
        suffix = task_id or "ad-hoc"
        safe_suffix = re.sub(r"[^A-Za-z0-9_-]", "_", suffix)
        return settings.browser_session_dir.expanduser().resolve() / safe_suffix / "form_state.json"

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

    def _get_page() -> Any:
        page = browser_state.get("page")
        if page is None or page.is_closed():
            raise RuntimeError("No active browser page. Call open_page first.")
        return page

    def _launch_context() -> Any:
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        session_root = settings.browser_session_dir.expanduser().resolve()
        session_root.mkdir(parents=True, exist_ok=True)
        suffix = task_id or "ad-hoc"
        user_data_dir = session_root / re.sub(r"[^A-Za-z0-9_-]", "_", suffix)
        context = playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=settings.browser_headless,
        )
        browser_state["playwright"] = playwright
        browser_state["context"] = context
        return context

    @tool
    def close_browser() -> dict[str, Any]:
        """Close the task-local browser session and release its resources."""
        context = browser_state.pop("context", None)
        playwright = browser_state.pop("playwright", None)
        browser_state["page"] = None
        browser_state["fields"] = {}
        try:
            if context is not None:
                context.close()
        except Exception as error:
            return result("close_browser", {}, {"ok": False, "error": str(error)})
        finally:
            if playwright is not None:
                playwright.stop()
        return result("close_browser", {}, {"ok": True, "message": "浏览器会话已关闭。"})

    @tool
    def open_page(url: str) -> dict[str, Any]:
        """Open an allowlisted webpage in a persistent user browser session."""
        try:
            validated_url = validate_browser_url(url, settings.allowed_browser_domains)
        except BrowserPolicyError as error:
            return result("open_page", {"url": url}, {
                "ok": False, "error": str(error), "policy_denied": True,
            })
        try:
            context = browser_state.get("context")
            if context is None:
                context = _launch_context()
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(validated_url, wait_until="domcontentloaded", timeout=settings.browser_timeout_ms)
            browser_state["page"] = page
            return result("open_page", {"url": validated_url}, {
                "ok": True, "url": page.url, "title": page.title(),
                "message": "页面已打开。下一步可调用 inspect_form。",
            })
        except Exception as error:
            return result("open_page", {"url": validated_url}, {
                "ok": False, "error": f"Browser open failed: {error}",
            })

    @tool
    def inspect_form() -> dict[str, Any]:
        """Inspect usable form fields on the active page without changing them."""
        try:
            page = _get_page()
            fields = page.locator("input, textarea, select").evaluate_all(
                """els => els.map((el, index) => {
                    const label = el.labels && el.labels.length
                      ? Array.from(el.labels).map(x => x.innerText).join(' ').trim() : '';
                    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
                    const key = `field_${index}`;
                    return {
                      key, index, tag: el.tagName.toLowerCase(), type,
                      name: el.getAttribute('name') || '', id: el.id || '',
                      label, placeholder: el.getAttribute('placeholder') || '',
                      required: !!el.required, value: el.value || '',
                      options: el.tagName.toLowerCase() === 'select'
                        ? Array.from(el.options).map(x => ({value: x.value, label: x.text})) : []
                    };
                })"""
            )
            browser_state["fields"] = {item["key"]: item for item in fields}
            submit_buttons = page.locator(
                "button, input[type='submit'], input[type='image']"
            ).evaluate_all(
                """els => els.map((el, index) => ({
                    key: `submit_${index}`,
                    text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim(),
                    type: el.getAttribute('type') || 'button',
                    disabled: !!el.disabled
                })).filter(x => !x.disabled)"""
            )
            return result("inspect_form", {}, {
                "ok": True, "url": page.url, "title": page.title(),
                "fields": fields[:100], "truncated": len(fields) > 100,
                "submit_buttons": submit_buttons[:20],
            })
        except Exception as error:
            return result("inspect_form", {}, {"ok": False, "error": str(error)})

    @tool
    def fill_form(values: dict[str, str]) -> dict[str, Any]:
        """Fill inspected text, checkbox, radio, and select fields by field key.

        Values must come from verified local evidence. This tool never submits
        the form and returns the changed fields for human review.
        """
        try:
            page = _get_page()
            if not browser_state["fields"]:
                return result("fill_form", {"values": values}, {
                    "ok": False, "error": "Call inspect_form before fill_form.",
                })
            changed: list[dict[str, Any]] = []
            for key, value in values.items():
                field = browser_state["fields"].get(key)
                if field is None:
                    return result("fill_form", {"values": values}, {
                        "ok": False, "error": f"Unknown field key: {key}",
                    })
                locator = page.locator("input, textarea, select").nth(int(field["index"]))
                field_type = field["type"]
                if field_type in {"checkbox", "radio"}:
                    desired = str(value).strip().lower() in {"1", "true", "yes", "on", "是"}
                    locator.set_checked(desired)
                elif field["tag"] == "select":
                    locator.select_option(str(value))
                else:
                    locator.fill(str(value))
                changed.append({"key": key, "label": field.get("label") or field.get("name") or field.get("id"), "value": str(value)})
            state_path = _state_path()
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "url": page.url,
                        "fields": {
                            key: {**browser_state["fields"][key], "value": str(value)}
                            for key, value in values.items()
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return result("fill_form", {"field_count": len(values)}, {
                "ok": True, "changed_fields": changed,
                "message": "已填写表单草稿，尚未提交。",
            })
        except Exception as error:
            return result("fill_form", {"field_count": len(values)}, {
                "ok": False, "error": f"Form fill failed: {error}",
            })

    @tool
    def save_form_draft(filename: str = "form-draft.json") -> dict[str, Any]:
        """Save a local snapshot of the active page's current form values."""
        try:
            page = _get_page()
            root = settings.workspace.expanduser().resolve()
            safe_name = Path(filename).name
            destination = root / "browser-drafts" / safe_name
            if destination.suffix.lower() != ".json":
                destination = destination.with_suffix(".json")
            if settings.read_only:
                return result("save_form_draft", {"filename": filename}, {
                    "ok": False, "error": "Workspace is read-only; draft was not saved.",
                })
            values = page.locator("input, textarea, select").evaluate_all(
                "els => els.map((el, index) => ({index, name: el.name || '', id: el.id || '', value: el.value || ''}))"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps({"url": page.url, "title": page.title(), "fields": values}, ensure_ascii=False, indent=2), encoding="utf-8")
            return result("save_form_draft", {"filename": filename}, {
                "ok": True, "path": str(destination.relative_to(root)),
            })
        except Exception as error:
            return result("save_form_draft", {"filename": filename}, {"ok": False, "error": str(error)})

    @tool
    def submit_form(approval_id: str) -> dict[str, Any]:
        """Submit the prepared form only after this task's approval is approved."""
        input_data = {"approval_id": approval_id}
        if audit_store is None or task_id is None:
            return result("submit_form", input_data, {
                "ok": False, "error": "Form submission requires a task approval context.",
                "policy_denied": True,
            })
        approvals = {item["id"]: item for item in audit_store.list_approvals(task_id)}
        approval = approvals.get(approval_id)
        if approval is None or approval.get("status") != "approved":
            return result("submit_form", input_data, {
                "ok": False,
                "error": "Form submission is blocked until the matching approval is approved.",
                "policy_denied": True,
            })
        state_path = _state_path()
        if not state_path.is_file():
            return result("submit_form", input_data, {
                "ok": False,
                "error": "No prepared form was found. Inspect and fill the form before approval.",
            })
        try:
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            validated_url = validate_browser_url(
                str(saved.get("url", "")), settings.allowed_browser_domains
            )
            context = browser_state.get("context") or _launch_context()
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(validated_url, wait_until="domcontentloaded", timeout=settings.browser_timeout_ms)
            browser_state["page"] = page
            fields = saved.get("fields", {})
            for field in fields.values():
                selector = field.get("id") or field.get("name")
                locator = page.locator(f"#{selector}") if selector else page.locator(
                    "input, textarea, select"
                ).nth(int(field.get("index", 0)))
                if selector and page.locator(f"#{selector}").count() == 0:
                    locator = page.locator(
                        f"[name={json.dumps(str(field.get('name')))}]"
                    )
                field_type = str(field.get("type", "")).lower()
                value = str(field.get("value", ""))
                if field_type in {"checkbox", "radio"}:
                    locator.set_checked(value.strip().lower() in {"1", "true", "yes", "on", "是"})
                elif str(field.get("tag", "")) == "select":
                    locator.select_option(value)
                else:
                    locator.fill(value)
            buttons = page.locator(
                "button:not([type]), button[type='submit'], input[type='submit'], input[type='image']"
            )
            if buttons.count() != 1:
                return result("submit_form", input_data, {
                    "ok": False,
                    "error": f"Expected exactly one submit button, found {buttons.count()}; no submission was made.",
                    "policy_denied": True,
                })
            buttons.first.click(timeout=settings.browser_timeout_ms)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=settings.browser_timeout_ms)
            except Exception:
                pass
            return result("submit_form", input_data, {
                "ok": True, "url": page.url, "title": page.title(),
                "message": "表单已在审批后提交。",
            })
        except Exception as error:
            return result("submit_form", input_data, {
                "ok": False, "error": f"Form submission failed: {error}",
            })

    return [fetch_page, open_page, inspect_form, fill_form, save_form_draft, submit_form, close_browser]
