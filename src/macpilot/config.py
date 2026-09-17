"""Compatibility import; new code should use :mod:`macpilot.core.config`."""

from macpilot.core.config import Settings, normalize_qwen_base_url

__all__ = ["Settings", "normalize_qwen_base_url"]
