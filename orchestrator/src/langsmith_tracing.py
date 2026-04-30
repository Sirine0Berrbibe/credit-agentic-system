"""
LangSmith tracing helpers for the credit orchestrator.

This module keeps tracing concerns in one place:
- safe imports with graceful fallback when LangSmith is not installed
- shared input/output redaction helpers for sensitive credit data
- small utilities to annotate runs with consistent metadata and tags
"""

from __future__ import annotations

import hashlib
import inspect
import logging
import os
import re
from typing import Any, Callable, Iterable, Optional

logger = logging.getLogger(__name__)

try:
    from langsmith import Client, get_current_run_tree, traceable as _traceable
    LANGSMITH_AVAILABLE = True
except ImportError:
    Client = None
    LANGSMITH_AVAILABLE = False

    def _traceable(*args, **kwargs):
        def decorator(fn):
            return fn

        return decorator

    def get_current_run_tree():
        return None


SENSITIVE_KEY_PARTS = {
    "api_key",
    "authorization",
    "password",
    "secret",
    "token",
    "cin",
    "email",
    "phone",
    "mobile",
    "address",
    "salary",
    "income",
    "ocr_text",
    "bytes",
}

SENSITIVE_EXACT_KEYS = {
    "api-key",
    "api_key",
    "client_data",
    "documents",
    "messages",
    "headers",
}

MAX_STRING_LENGTH = 400
MAX_LIST_ITEMS = 20
MAX_DICT_ITEMS = 50

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_PATTERN = re.compile(r"\+?\d[\d\s().-]{7,}\d")

_LANGSMITH_CLIENT: Optional[Any] = None


def _hash_identifier(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


def _is_sensitive_key(key: Optional[str]) -> bool:
    if not key:
        return False
    key_lower = key.lower()
    if key_lower in SENSITIVE_EXACT_KEYS:
        return True
    return any(part in key_lower for part in SENSITIVE_KEY_PARTS)


def _truncate_string(value: str) -> str:
    redacted = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", value)
    redacted = PHONE_PATTERN.sub("[REDACTED_PHONE]", redacted)
    if len(redacted) <= MAX_STRING_LENGTH:
        return redacted
    return f"{redacted[:MAX_STRING_LENGTH]}...<truncated>"


def _sanitize_value(value: Any, key: Optional[str] = None, depth: int = 0) -> Any:
    if depth > 8:
        return "<max-depth>"

    if value is None:
        return None

    if isinstance(value, (bytes, bytearray)):
        return {"type": "bytes", "length": len(value)}

    if _is_sensitive_key(key):
        if isinstance(value, (list, tuple, set)):
            return f"[REDACTED_COLLECTION:{len(value)}]"
        if isinstance(value, dict):
            return f"[REDACTED_OBJECT:{len(value)}]"
        return "[REDACTED]"

    if isinstance(value, dict):
        items = list(value.items())[:MAX_DICT_ITEMS]
        sanitized = {
            str(child_key): _sanitize_value(child_value, str(child_key), depth + 1)
            for child_key, child_value in items
        }
        if len(value) > MAX_DICT_ITEMS:
            sanitized["__truncated_items__"] = len(value) - MAX_DICT_ITEMS
        return sanitized

    if isinstance(value, (list, tuple, set)):
        values = list(value)[:MAX_LIST_ITEMS]
        sanitized = [_sanitize_value(item, key, depth + 1) for item in values]
        if len(value) > MAX_LIST_ITEMS:
            sanitized.append(f"<truncated:{len(value) - MAX_LIST_ITEMS}>")
        return sanitized

    if isinstance(value, str):
        return _truncate_string(value)

    if isinstance(value, (int, float, bool)):
        return value

    return _truncate_string(str(value))


def process_trace_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    return _sanitize_value(inputs)


def process_trace_outputs(outputs: Any) -> Any:
    return _sanitize_value(outputs)


def sanitize_metadata(metadata: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not metadata:
        return {}
    return _sanitize_value(metadata)


def get_langsmith_client() -> Optional[Any]:
    global _LANGSMITH_CLIENT
    if not LANGSMITH_AVAILABLE:
        return None
    tracing_enabled = os.getenv("LANGSMITH_TRACING", "").lower() == "true"
    api_key_present = bool(os.getenv("LANGSMITH_API_KEY"))
    if not tracing_enabled or not api_key_present:
        return None
    if _LANGSMITH_CLIENT is None:
        client_signature = inspect.signature(Client.__init__)
        client_kwargs: dict[str, Any] = {}

        if "hide_inputs" in client_signature.parameters:
            client_kwargs["hide_inputs"] = process_trace_inputs
        if "hide_outputs" in client_signature.parameters:
            client_kwargs["hide_outputs"] = process_trace_outputs
        if "hide_metadata" in client_signature.parameters:
            client_kwargs["hide_metadata"] = sanitize_metadata
        if "info" in client_signature.parameters:
            # Avoid an eager /info lookup during module import on older SDKs.
            client_kwargs["info"] = {}

        _LANGSMITH_CLIENT = Client(**client_kwargs)
    return _LANGSMITH_CLIENT


def traceable(*args, **kwargs):
    if not LANGSMITH_AVAILABLE:
        return _traceable(*args, **kwargs)

    client = get_langsmith_client()
    if client is not None:
        kwargs.setdefault("client", client)
    return _traceable(*args, **kwargs)


def build_trace_metadata(
    *,
    service: str,
    component: str,
    operation: str,
    application_id: Optional[str] = None,
    client_id: Optional[str] = None,
    flux_type: Optional[str] = None,
    env: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "service": service,
        "component": component,
        "operation": operation,
    }
    if env:
        metadata["environment"] = env
    if application_id:
        metadata["application_id"] = str(application_id)
        metadata["thread_id"] = str(application_id)
    if client_id:
        metadata["client_id_hash"] = _hash_identifier(client_id)
    if flux_type:
        metadata["flux_type"] = flux_type
    if extra:
        metadata.update(extra)
    return sanitize_metadata(metadata)


def build_trace_tags(*values: Optional[str]) -> list[str]:
    tags: list[str] = []
    for value in values:
        if not value:
            continue
        tag = str(value).strip().replace(" ", "-").lower()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def annotate_current_run(
    *,
    metadata: Optional[dict[str, Any]] = None,
    tags: Optional[Iterable[str]] = None,
) -> None:
    run_tree = get_current_run_tree()
    if run_tree is None:
        return

    if metadata:
        if run_tree.metadata is None:
            run_tree.metadata = {}
        safe_metadata = sanitize_metadata(metadata)
        for key, value in safe_metadata.items():
            run_tree.metadata[key] = value

    if tags:
        if run_tree.tags is None:
            run_tree.tags = []
        existing_tags = set(run_tree.tags or [])
        for tag in tags:
            if tag and tag not in existing_tags:
                run_tree.tags.append(tag)
                existing_tags.add(tag)


async def flush_langsmith() -> None:
    client = get_langsmith_client()
    if client is None:
        return
    if not hasattr(client, "flush"):
        return
    try:
        result = client.flush()
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        logger.warning("LangSmith flush failed: %s", exc)
