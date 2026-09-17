"""Small, dependency-light helpers for keeping model context bounded.

The agent should preserve the instruction and the most recent user request,
while dropping the least useful middle of a long trace first.  Token counts
are deliberately estimates: providers do not share a tokenizer and this
module must also work when no model SDK is installed.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def estimate_tokens(value: Any) -> int:
    """Estimate tokens using a conservative four-characters-per-token rule."""
    text = value if isinstance(value, str) else str(value)
    return max(1, (len(text) + 3) // 4) if text else 0


def truncate_text(text: str, max_tokens: int, suffix: str = "\n[…内容已裁剪…]") -> str:
    """Return text within an approximate token budget, preserving both ends."""
    if max_tokens <= 0:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text
    max_chars = max(1, max_tokens * 4)
    suffix = suffix if len(suffix) < max_chars else ""
    available = max_chars - len(suffix)
    head = (available + 1) // 2
    tail = available - head
    return f"{text[:head]}{suffix}{text[-tail:] if tail else ''}"


def trim_text(text: str, max_tokens: int) -> str:
    """Backward-compatible short name used by workflow nodes."""
    return truncate_text(text, max_tokens)


def trim_messages(messages: Iterable[Any], max_tokens: int) -> list[Any]:
    """Keep system messages and the newest messages within ``max_tokens``.

    Message objects are treated structurally (``type``/``content``) so this
    helper works with LangChain messages as well as simple test doubles.
    """
    items = list(messages)
    if max_tokens <= 0 or not items:
        return []

    def message_tokens(message: Any) -> int:
        return estimate_tokens(getattr(message, "content", message))

    system = [item for item in items if getattr(item, "type", "") == "system"]
    others = [item for item in items if item not in system]
    selected: list[Any] = []
    used = 0
    for item in reversed(others):
        cost = message_tokens(item)
        if selected and used + cost > max_tokens:
            break
        if not selected and cost > max_tokens:
            content = getattr(item, "content", str(item))
            if hasattr(item, "model_copy"):
                selected.append(item.model_copy(update={"content": truncate_text(content, max_tokens)}))
            else:
                selected.append(item)
            break
        selected.append(item)
        used += cost

    selected.reverse()
    result: list[Any] = []
    for item in system:
        if used + message_tokens(item) <= max_tokens or not result:
            result.append(item)
            used += message_tokens(item)
    result.extend(selected)
    return result


def trim_text_fields(fields: dict[str, str], max_tokens: int) -> dict[str, str]:
    """Trim a prompt made of named text fields, allocating budget in order."""
    result: dict[str, str] = {}
    remaining = max_tokens
    for name, value in fields.items():
        if remaining <= 0:
            break
        clipped = truncate_text(value, remaining)
        result[name] = clipped
        remaining -= estimate_tokens(clipped)
    return result
