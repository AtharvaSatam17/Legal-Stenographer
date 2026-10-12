# services/realtime/command_parser.py
#
# Leading-token detection for the "new paragraph" voice command.
#
# Scope:
#   - "new paragraph" / "new para" / "next paragraph" / "new line"
#     → {"kind": "paragraph_break"}
#
# When detected, the segment is a COMMAND (a paragraph break), not content.
# The caller must NOT broadcast it as a transcription_update and must NOT
# store its text anywhere — it only inserts a paragraph break so subsequent
# speech starts a new paragraph.
#
# Classification rules:
#   - Segment text is normalized: lowercase (via re.IGNORECASE), strip,
#     collapse whitespace.
#   - Match must be the FIRST (and only) content of the segment, never
#     mid-segment — enforced with ^...$ anchoring.
#   - Only English segments are matched. Non-English segments (detected via
#     the segment's language field) are short-circuited to None.
#
# This module is intentionally pure (no I/O, no session state) for testability.

import re
from typing import Optional, Dict


# Pre-compiled pattern. Anchored at both ends (^...$) to enforce the
# "leading content of the whole segment" rule — never scan mid-segment.
# Allows surrounding whitespace and an optional trailing period.
_NEW_PARAGRAPH_PATTERN = re.compile(
    r"^\s*(new\s+paragraph|new\s+para|next\s+paragraph|new\s+line)\.?\s*$",
    re.IGNORECASE,
)

# Languages considered English for the purpose of command detection.
_ENGLISH_LANGUAGE_CODES = {"en-IN", "en", "en-US", "en-GB", "unknown"}


def classify_segment(text: str, language: Optional[str] = None) -> Optional[Dict[str, str]]:
    """
    Classify whether a transcript segment is the "new paragraph" voice command.

    Args:
        text: The raw transcript text of the segment.
        language: BCP-47 language code detected for this segment.
                  If not English, returns None immediately (English-only scope).

    Returns:
        None if the segment is normal content (should be broadcast as
        transcription_update).
        {"kind": "paragraph_break"} if the segment is the new-paragraph command.
    """
    if not text:
        return None

    # English-only scope. Non-English segments are never commands.
    if language and language not in _ENGLISH_LANGUAGE_CODES:
        return None

    normalized = " ".join(text.strip().split())  # collapse whitespace

    if _NEW_PARAGRAPH_PATTERN.match(normalized):
        return {"kind": "paragraph_break"}

    return None
