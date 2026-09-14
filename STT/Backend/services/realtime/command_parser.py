# services/realtime/command_parser.py
#
# Phase 1, Step 2 — Wake-phrase / leading-token detection for voice-driven
# content corrections.
#
# v1 scope (per design review):
#   - "scratch that" → {"kind": "scratch"}
#   - "change that to <replacement>" → {"kind": "replace", "replacement": <text>}
#
# Classification rules:
#   - Segment text is normalized: lowercase, strip, collapse whitespace.
#   - Match must be on the FIRST token(s) of the segment, never mid-segment.
#   - Only English patterns are matched. Non-English segments (detected via
#     the segment's language field) are short-circuited to None — see Risk C.
#
# This module is intentionally pure (no I/O, no session state) for testability.

import re
from typing import Optional, Dict


# Pre-compiled patterns. Anchored to start of string (^) to enforce the
# "first token only" rule — never scan mid-segment.
_SCRATCH_PATTERN = re.compile(r"^scratch\s+that\.?\s*$", re.IGNORECASE)
_REPLACE_PATTERN = re.compile(r"^change\s+that\s+to\s+(?P<replacement>.+?)\.?\s*$", re.IGNORECASE)

# Languages considered English for the purpose of command detection.
_ENGLISH_LANGUAGE_CODES = {"en-IN", "en", "en-US", "en-GB", "unknown"}


def classify_segment(text: str, language: Optional[str] = None) -> Optional[Dict[str, str]]:
    """
    Classify whether a transcript segment is a voice correction command.

    Args:
        text: The raw transcript text of the segment.
        language: BCP-47 language code detected for this segment.
                  If not English, returns None immediately (Risk C — English-only v1).

    Returns:
        None if the segment is normal content (should be broadcast as transcription_update).
        A dict if it's a command:
            {"kind": "scratch"}
            {"kind": "replace", "replacement": "<captured text>"}
    """
    if not text:
        return None

    # Risk C — English-only scope. Non-English segments are never commands.
    # TODO(v2): Add multilingual wake-word support for Hindi/Marathi etc.
    if language and language not in _ENGLISH_LANGUAGE_CODES:
        return None

    normalized = " ".join(text.strip().split())  # collapse whitespace

    # Pattern 1: "scratch that"
    if _SCRATCH_PATTERN.match(normalized):
        return {"kind": "scratch"}

    # Pattern 2: "change that to <replacement>"
    m = _REPLACE_PATTERN.match(normalized)
    if m:
        replacement = m.group("replacement").strip().rstrip(".")
        if replacement:
            return {"kind": "replace", "replacement": replacement}

    return None
