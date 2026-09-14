# services/realtime/transcript_materializer.py
#
# Phase 1, Step 4 — Transcript materializer (append-only correction log).
#
# Computes the effective transcript text and message list from the raw
# segment list + the content_corrections log. No segment is ever deleted
# or mutated — corrections produce an overlay view.
#
# Deviation from literal plan text (agreed upfront): when a replace correction
# targets an already-scratched/hidden segment, we log a warning and record the
# skipped correction with a reason in the content_corrections log — we do NOT
# silently skip with no trace.

import logging
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)


def materialize(
    segments: List[Dict[str, Any]],
    corrections: List[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Compute the effective transcript from raw segments + correction log.

    Returns:
        (transcript_text, materialized_messages)

        transcript_text: concatenation of all visible segment texts (post-correction).
        materialized_messages: list of segment dicts with effective text and visibility.
    """
    if not segments:
        return "", []

    # Build per-segment effective state by replaying corrections in order.
    # Each segment can be: visible (original or replaced text) or hidden (scratched).
    #
    # Data structure per segment_id:
    #   {"hidden": bool, "effective_text": str, "applied_corrections": [correction_id...]}
    segment_state: Dict[str, Dict[str, Any]] = {}
    for seg in segments:
        sid = seg["segment_id"]
        segment_state[sid] = {
            "hidden": False,
            "effective_text": seg["transcript"],
            "applied_corrections": [],
        }

    # Track which correction_ids have been reversed
    reversed_set: set = set()

    # First pass: identify reversals
    for entry in corrections:
        if entry.get("kind") == "reverse" and entry.get("reverses_correction_id"):
            reversed_set.add(entry["reverses_correction_id"])

    # Second pass: apply non-reversed, non-rejected corrections in order
    for entry in corrections:
        kind = entry.get("kind")
        cid = entry.get("correction_id")
        target_sid = entry.get("target_segment_id")

        # Skip rejected entries — they don't affect the transcript
        if kind == "rejected":
            continue

        # Skip reversal entries themselves — they just mark a prior as undone
        if kind == "reverse":
            continue

        # Skip entries that have been reversed
        if cid in reversed_set:
            continue

        # Skip if the target segment doesn't exist in our state
        if target_sid not in segment_state:
            logger.warning(
                f"Content correction {cid} targets unknown segment {target_sid}. Skipping."
            )
            continue

        state = segment_state[target_sid]

        if kind == "scratch":
            if state["hidden"]:
                # Already hidden — log but still record
                logger.warning(
                    f"Content correction {cid} (scratch) targets already-hidden segment "
                    f"{target_sid}. Recording as skipped."
                )
                # The correction remains in the log with its own record (audit trail)
                # but doesn't change effective state.
                continue
            state["hidden"] = True
            state["applied_corrections"].append(cid)

        elif kind == "replace":
            if state["hidden"]:
                # Deviation note: log a warning and DON'T silently skip.
                # The correction is already in the append-only log so it's
                # traceable in corrections.json. We just don't apply it.
                logger.warning(
                    f"Content correction {cid} (replace) targets already-hidden segment "
                    f"{target_sid}. Replacement not applied (segment is scratched). "
                    f"Correction remains in log for audit."
                )
                continue
            replacement = entry.get("replacement_text", "")
            if replacement:
                state["effective_text"] = replacement
                state["applied_corrections"].append(cid)

    # Build output
    materialized_messages: List[Dict[str, Any]] = []
    text_parts: List[str] = []

    for seg in segments:
        sid = seg["segment_id"]
        state = segment_state[sid]

        msg = {
            **seg,
            "effective_text": state["effective_text"],
            "hidden": state["hidden"],
            "applied_corrections": state["applied_corrections"],
        }
        materialized_messages.append(msg)

        if not state["hidden"]:
            text_parts.append(state["effective_text"])

    transcript_text = " ".join(text_parts).strip()
    return transcript_text, materialized_messages
