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
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_core.tools import StructuredTool
from langchain_core.tools import tool

from macpilot.core.config import Settings
from macpilot.phase3.security import BrowserPolicyError, DomainAllowlist, validate_browser_url


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
    allowlist: DomainAllowlist | None = None,
) -> list[StructuredTool]:
    runtime_allowlist = allowlist or DomainAllowlist.from_domains(settings.allowed_browser_domains)
    browser_state: dict[str, Any] = {
        "context": None,
        "page": None,
        "fields": {},
        "requires_user_login": False,
    }
    browser_executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix=f"macpilot-browser-{task_id or 'ad-hoc'}",
    )

    def _browser_call(function: Any, *args: Any) -> Any:
        """Run all stateful Playwright operations on one stable thread."""
        return browser_executor.submit(function, *args).result()

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
            validated_url = validate_browser_url(url, tuple(runtime_allowlist.permanent | runtime_allowlist.temporary))
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
        def close_impl() -> dict[str, Any]:
            context = browser_state.pop("context", None)
            playwright = browser_state.pop("playwright", None)
            browser_state["page"] = None
            browser_state["fields"] = {}
            browser_state["requires_user_login"] = False
            try:
                if context is not None:
                    context.close()
            except Exception as error:
                return {"ok": False, "error": str(error)}
            finally:
                if playwright is not None:
                    playwright.stop()
            return {"ok": True, "message": "浏览器会话已关闭。"}

        return result("close_browser", {}, _browser_call(close_impl))

    @tool
    def open_page(url: str) -> dict[str, Any]:
        """Open an allowlisted webpage in a persistent user browser session."""
        try:
            validated_url = validate_browser_url(url, tuple(runtime_allowlist.permanent | runtime_allowlist.temporary))
        except BrowserPolicyError as error:
            return result("open_page", {"url": url}, {
                "ok": False, "error": str(error), "policy_denied": True,
            })
        def open_impl() -> dict[str, Any]:
            if browser_state.get("requires_user_login"):
                return {
                    "ok": False,
                    "requires_user_login": True,
                    "message": "当前页面需要用户登录；已停止重复导航，请在浏览器中完成登录后再继续。",
                }
            context = browser_state.get("context")
            if context is None:
                context = _launch_context()
            page = context.pages[0] if context.pages else context.new_page()
            # Never reload an already-open page during one agent run. A model
            # retry must not interrupt a user who is typing a login code.
            if browser_state.get("page") is not None and not page.is_closed():
                return {
                    "ok": True,
                    "url": page.url,
                    "title": page.title(),
                    "message": "页面已保持打开，禁止重复导航；请继续当前页面上的人工操作。",
                }
            page.goto(validated_url, wait_until="domcontentloaded", timeout=settings.browser_timeout_ms)
            browser_state["page"] = page
            return {
                "ok": True, "url": page.url, "title": page.title(),
                "message": "页面已打开。下一步可调用 inspect_form。",
            }

        try:
            return result("open_page", {"url": validated_url}, _browser_call(open_impl))
        except Exception as error:
            return result("open_page", {"url": validated_url}, {
                "ok": False, "error": f"Browser open failed: {error}",
            })

    @tool
    def inspect_form() -> dict[str, Any]:
        """Inspect usable form fields on the active page without changing them."""
        def inspect_impl() -> dict[str, Any]:
            page = _get_page()
            fields = page.locator("input, textarea, select").evaluate_all(
                """els => els.map((el, index) => {
                    const label = el.labels && el.labels.length
                      ? Array.from(el.labels).map(x => x.innerText).join(' ').trim() : '';
                    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
                    const identity = [el.getAttribute('name') || '', el.id || '', label,
                      el.getAttribute('placeholder') || ''].join(' ').toLowerCase();
                    const sensitive = type === 'password' || /(password|passwd|pwd|username|user|account|login|phone|mobile|captcha|verification|otp|账号|密码|用户名|登录|手机号|验证码|验证)/i.test(identity);
                    const key = `field_${index}`;
                    return {
                      key, index, tag: el.tagName.toLowerCase(), type,
                      name: el.getAttribute('name') || '', id: el.id || '',
                      label, placeholder: el.getAttribute('placeholder') || '',
                      required: !!el.required, value: el.value || '', sensitive,
                      options: el.tagName.toLowerCase() === 'select'
                        ? Array.from(el.options).map(x => ({value: x.value, label: x.text})) : []
                    };
                })"""
            )
            browser_state["fields"] = {item["key"]: item for item in fields}
            login_fields = [
                {"key": item["key"], "label": item.get("label") or item.get("name") or item.get("id") or item["key"], "type": item.get("type")}
                for item in fields if item.get("sensitive")
            ]
            page_identity = f"{page.url} {page.title()}".lower()
            login_page = bool(re.search(r"/login|登录|sign[ -]?in|log[ -]?in", page_identity, re.I))
            browser_state["requires_user_login"] = bool(login_fields) or login_page
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
            return {
                "ok": True, "url": page.url, "title": page.title(),
                "fields": fields[:100], "truncated": len(fields) > 100,
                "submit_buttons": submit_buttons[:20],
                "requires_user_login": bool(login_fields) or login_page,
                "login_fields": login_fields,
                "message": (
                    "检测到账号或密码字段。请在当前浏览器窗口手动完成登录，"
                    "Agent 不会读取或填写账号密码。登录完成后再继续填写简历表单。"
                    if login_fields or login_page else "未检测到登录凭据字段。"
                ),
            }

        try:
            return result("inspect_form", {}, _browser_call(inspect_impl))
        except Exception as error:
            return result("inspect_form", {}, {"ok": False, "error": str(error)})

    @tool
    def add_form_entries(section: str, count: int) -> dict[str, Any]:
        """Add repeatable form sections without submitting the page.

        The Form Filler uses this after inspect_form when ResumeProfile contains
        multiple education, experience, or project entries. Only buttons whose
        text clearly means add/new/more are eligible; submit buttons are never
        clicked by this tool.
        """
        safe_count = max(0, min(int(count), 20))

        def add_impl() -> dict[str, Any]:
            page = _get_page()
            clicked: list[str] = []
            for _ in range(safe_count):
                candidates = page.locator("button, [role='button']").evaluate_all(
                    r"""els => els.map((el, index) => ({
                        index,
                        text: (el.innerText || el.getAttribute('aria-label') || '').trim()
                    })).filter(x => x.text && !/(submit|apply|提交|发送)/i.test(x.text) && /(add|new|another|more|plus|新增|添加|再加|更多|＋|[+])/i.test(x.text))"""
                )
                section_lower = section.strip().lower()
                matching = [item for item in candidates if not section_lower or section_lower in str(item["text"]).lower()]
                chosen = (matching or candidates)
                if not chosen:
                    break
                item = chosen[0]
                page.locator("button, [role='button']").nth(int(item["index"])).click(timeout=settings.browser_timeout_ms)
                clicked.append(str(item["text"]))
            return {"ok": True, "requested": safe_count, "clicked": len(clicked), "buttons": clicked, "message": "已按条目数量展开可重复表单，尚未提交。"}

        try:
            return result("add_form_entries", {"section": section, "count": safe_count}, _browser_call(add_impl))
        except Exception as error:
            return result("add_form_entries", {"section": section, "count": safe_count}, {"ok": False, "error": str(error)})

    @tool
    def request_domain_access(url: str) -> dict[str, Any]:
        """Return a user approval request for an HTTPS domain not yet allowed."""
        parsed = re.match(r"^https://([^/:?#]+)", url.strip(), re.I)
        domain = parsed.group(1).lower().rstrip(".") if parsed else ""
        output = {
            "ok": False,
            "approval_required": True,
            "domain": domain,
            "message": f"发现网址 {domain or url} 尚未获得访问授权，请用户确认后再继续。",
        }
        return result("request_domain_access", {"url": url}, output)

    @tool
    def fill_form(values: dict[str, str]) -> dict[str, Any]:
        """Fill inspected text, checkbox, radio, and select fields by field key.

        Values must come from verified local evidence. This tool never submits
        the form and returns the changed fields for human review.
        """
        def fill_impl() -> dict[str, Any]:
            page = _get_page()
            if not browser_state["fields"]:
                return {
                    "ok": False, "error": "Call inspect_form before fill_form.",
                }
            changed: list[dict[str, Any]] = []
            for key, value in values.items():
                field = browser_state["fields"].get(key)
                if field is None:
                    return {
                        "ok": False, "error": f"Unknown field key: {key}",
                    }
                if field.get("sensitive"):
                    return {
                        "ok": False,
                        "error": "账号、用户名和密码字段必须由用户手动填写，Agent 不会写入敏感凭据。",
                        "policy_denied": True,
                        "field": key,
                    }
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
            return {
                "ok": True, "changed_fields": changed,
                "message": "已填写表单草稿，尚未提交。",
            }

        try:
            return result("fill_form", {"field_count": len(values)}, _browser_call(fill_impl))
        except Exception as error:
            return result("fill_form", {"field_count": len(values)}, {
                "ok": False, "error": f"Form fill failed: {error}",
            })

    @tool
    def save_form_draft(filename: str = "form-draft.json") -> dict[str, Any]:
        """Save a local snapshot of the active page's current form values."""
        def save_impl() -> dict[str, Any]:
            page = _get_page()
            root = settings.workspace.expanduser().resolve()
            safe_name = Path(filename).name
            destination = root / "browser-drafts" / safe_name
            if destination.suffix.lower() != ".json":
                destination = destination.with_suffix(".json")
            if settings.read_only:
                return {
                    "ok": False, "error": "Workspace is read-only; draft was not saved.",
                }
            values = page.locator("input, textarea, select").evaluate_all(
                "els => els.map((el, index) => ({index, name: el.name || '', id: el.id || '', value: el.value || ''}))"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps({"url": page.url, "title": page.title(), "fields": values}, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                "ok": True, "path": str(destination.relative_to(root)),
            }

        try:
            return result("save_form_draft", {"filename": filename}, _browser_call(save_impl))
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
        def submit_impl() -> dict[str, Any]:
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            validated_url = validate_browser_url(
                str(saved.get("url", "")), tuple(runtime_allowlist.permanent | runtime_allowlist.temporary)
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
                return {
                    "ok": False,
                    "error": f"Expected exactly one submit button, found {buttons.count()}; no submission was made.",
                    "policy_denied": True,
                }
            buttons.first.click(timeout=settings.browser_timeout_ms)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=settings.browser_timeout_ms)
            except Exception:
                pass
            return {
                "ok": True, "url": page.url, "title": page.title(),
                "message": "表单已在审批后提交。",
            }

        try:
            return result("submit_form", input_data, _browser_call(submit_impl))
        except Exception as error:
            return result("submit_form", input_data, {
                "ok": False, "error": f"Form submission failed: {error}",
            })

    return [fetch_page, open_page, inspect_form, add_form_entries, request_domain_access, fill_form, save_form_draft, submit_form, close_browser]
