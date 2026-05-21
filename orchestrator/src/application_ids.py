"""
Helpers for normalizing application identifiers across the orchestrator.
"""

from __future__ import annotations

import re
import uuid
from typing import Any


UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}"
)


def normalize_application_id(value: Any) -> str:
    """
    Return a canonical UUID string for any incoming application identifier.

    Accepted inputs:
    - native UUID objects
    - plain UUID strings
    - decorated IDs such as "preview-<uuid>" or "decision-<uuid>"

    Falls back to a newly generated UUID when no valid UUID can be recovered.
    """
    if isinstance(value, uuid.UUID):
        return str(value)

    if value not in (None, ""):
        raw = str(value).strip()
        try:
            return str(uuid.UUID(raw))
        except (ValueError, TypeError, AttributeError):
            match = UUID_PATTERN.search(raw)
            if match:
                return str(uuid.UUID(match.group(0)))

    return str(uuid.uuid4())


def to_uuid(value: Any) -> uuid.UUID:
    """Convert any supported application identifier to a UUID object."""
    return uuid.UUID(normalize_application_id(value))
