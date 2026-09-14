# services/legal_transcript_formatter.py

import re
from typing import List, Dict, Any, Optional
from datetime import timedelta


# Tolerance (seconds) when matching a live correction's audio anchor to
# a diarization segment. If no segment contains the anchor exactly, the
# nearest segment within this tolerance is used.
_TIME_MATCH_TOLERANCE_SECONDS = 2.0


class LegalTranscriptFormatter:
    """
    Formats diarized transcripts into a lawyer-client consultation format.

    Consultation transcript format:
    [HH:MM:SS] ROLE: Statement

    Default speaker role mapping (2-party):
    - SPEAKER_1 → LAWYER
    - SPEAKER_2 → CLIENT_ROLE (PLAINTIFF or DEFENDANT, configurable per session)
    """

    # Filler words to remove (only when safe)
    FILLER_WORDS = {
        "um", "uh", "er", "ah", "like", "you know", "i mean",
        "sort of", "kind of", "basically", "actually", "literally"
    }

    def __init__(self, client_role: str = "PLAINTIFF", custom_role_mapping: Dict[str, str] = None):
        """
        Initialize the consultation transcript formatter.

        Args:
            client_role: The client's role for this session — "PLAINTIFF" or "DEFENDANT"
            custom_role_mapping: Optional custom mapping of speaker IDs to roles
        """
        self.client_role = client_role.upper()
        if self.client_role not in ("PLAINTIFF", "DEFENDANT"):
            self.client_role = "PLAINTIFF"

        if custom_role_mapping:
            self.role_mapping = custom_role_mapping
        else:
            self.role_mapping = {
                "SPEAKER_1": "LAWYER",
                "SPEAKER_2": self.client_role,
            }

    # ------------------------------------------------------------------
    # Phase 0, Step 0.3.3 — resolve corrections by audio time anchor
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_corrections_by_time(
        diarized_segments: List[Dict[str, Any]],
        corrections: Dict[str, Any],
    ) -> Dict[int, str]:
        """
        Build a mapping of {diarized_segment_index: corrected_role} by matching
        each correction's start_time_seconds anchor to the nearest diarization
        segment (by time overlap or proximity).

        Supports both legacy corrections (plain string value) and new-format
        corrections (dict with "role" and "start_time_seconds" keys).

        Returns:
            Dict mapping segment list index → corrected role string.
        """
        if not corrections or not diarized_segments:
            return {}

        # Normalize corrections into a list of (role, anchor_time) tuples.
        anchored: List[tuple] = []  # (role, start_time_seconds | None)
        for key, value in corrections.items():
            if isinstance(value, dict):
                # New format: {"role": "LAWYER", "start_time_seconds": 12.3}
                role = value.get("role", "").upper()
                anchor = value.get("start_time_seconds")
            elif isinstance(value, str):
                # Legacy format (plain string role) — no anchor available.
                role = value.upper()
                anchor = None
            else:
                continue
            if role:
                anchored.append((role, anchor))

        corrections_by_index: Dict[int, str] = {}

        for role, anchor in anchored:
            if anchor is None:
                # Legacy correction with no time anchor — cannot match to
                # diarization segment. Skip silently (this was already a no-op
                # in the old code due to id mismatch; no regression).
                continue

            # Find the diarization segment that contains this anchor time,
            # or failing that, the nearest by midpoint within tolerance.
            best_idx: Optional[int] = None
            best_distance: float = float("inf")

            for idx, seg in enumerate(diarized_segments):
                seg_start = seg.get("start_time_seconds", 0.0)
                seg_end = seg.get("end_time_seconds", 0.0)

                # Exact containment check
                if seg_start <= anchor <= seg_end:
                    best_idx = idx
                    best_distance = 0.0
                    break

                # Proximity check (midpoint distance)
                midpoint = (seg_start + seg_end) / 2.0
                distance = abs(midpoint - anchor)
                if distance < best_distance:
                    best_distance = distance
                    best_idx = idx

            if best_idx is not None and best_distance <= _TIME_MATCH_TOLERANCE_SECONDS:
                corrections_by_index[best_idx] = role

        return corrections_by_index

    @staticmethod
    def _resolve_content_corrections_by_time(
        diarized_segments: List[Dict[str, Any]],
        content_corrections: List[Dict[str, Any]],
    ) -> Dict[int, Dict[str, Any]]:
        """
        Build a mapping of {diarized_segment_index: effective_edit} from the
        content_corrections log.

        Uses the same time-anchor matching as speaker corrections.
        Replays the log to compute net-effective edits (accounting for reversals).

        Returns:
            Dict mapping segment index → {"kind": "scratch"|"replace", "replacement_text": ...}
        """
        if not content_corrections or not diarized_segments:
            return {}

        # Identify reversed correction IDs
        reversed_ids: set = set()
        for entry in content_corrections:
            if entry.get("kind") == "reverse" and entry.get("reverses_correction_id"):
                reversed_ids.add(entry["reverses_correction_id"])

        # Collect effective corrections (not reversed, not rejected)
        effective: List[Dict[str, Any]] = []
        for entry in content_corrections:
            kind = entry.get("kind")
            if kind in ("rejected", "reverse"):
                continue
            if entry.get("correction_id") in reversed_ids:
                continue
            effective.append(entry)

        # Match each effective correction to the nearest diarization segment
        edits_by_index: Dict[int, Dict[str, Any]] = {}

        for entry in effective:
            anchor = entry.get("target_start_time_seconds")
            if anchor is None:
                continue

            best_idx: Optional[int] = None
            best_distance: float = float("inf")

            for idx, seg in enumerate(diarized_segments):
                seg_start = seg.get("start_time_seconds", 0.0)
                seg_end = seg.get("end_time_seconds", 0.0)

                if seg_start <= anchor <= seg_end:
                    best_idx = idx
                    best_distance = 0.0
                    break

                midpoint = (seg_start + seg_end) / 2.0
                distance = abs(midpoint - anchor)
                if distance < best_distance:
                    best_distance = distance
                    best_idx = idx

            if best_idx is not None and best_distance <= _TIME_MATCH_TOLERANCE_SECONDS:
                # Later corrections override earlier ones for the same index
                edits_by_index[best_idx] = {
                    "kind": entry["kind"],
                    "replacement_text": entry.get("replacement_text"),
                }

        return edits_by_index

    def format_timestamp(self, seconds: float) -> str:
        """Format seconds to [HH:MM:SS] format."""
        td = timedelta(seconds=int(seconds))
        hours = td.seconds // 3600
        minutes = (td.seconds % 3600) // 60
        secs = td.seconds % 60
        return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"

    def get_speaker_role(self, speaker_id: str) -> str:
        """
        Get the role for a speaker ID.

        Args:
            speaker_id: Speaker identifier from diarization

        Returns:
            Role name (LAWYER, PLAINTIFF, DEFENDANT, or raw speaker_id)
        """
        speaker_id = speaker_id.upper().strip()

        if speaker_id in self.role_mapping:
            return self.role_mapping[speaker_id]

        return speaker_id

    def clean_transcript_text(self, text: str, aggressive_cleaning: bool = False) -> str:
        """Clean transcript text with minimal grammar fixes."""
        if not text:
            return ""

        cleaned = text.strip()

        # Fix spacing around punctuation
        cleaned = re.sub(r'\s+([.,!?;:])', r'\1', cleaned)
        cleaned = re.sub(r'([.,!?;:])\s*', r'\1 ', cleaned)

        # Remove multiple spaces
        cleaned = re.sub(r'\s+', ' ', cleaned)

        if aggressive_cleaning:
            filler_pattern = r'\b(' + '|'.join(re.escape(f) for f in self.FILLER_WORDS) + r')\b'
            cleaned = re.sub(filler_pattern, '', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'\s+', ' ', cleaned)

        # Capitalize first letter
        if cleaned:
            cleaned = cleaned[0].upper() + cleaned[1:]

        # Ensure proper sentence ending
        if cleaned and cleaned[-1] not in '.!?':
            cleaned += '.'

        return cleaned.strip()

    def format_legal_transcript(
        self,
        diarized_segments: List[Dict[str, Any]],
        speaker_corrections: Optional[Dict[str, Any]] = None,
        content_corrections: Optional[List[Dict[str, Any]]] = None,
        remove_fillers: bool = False,
        include_duration: bool = False
    ) -> str:
        """
        Format diarized segments into consultation transcript format.

        Speaker precedence: manual correction (by time anchor) > diarization
        role mapping > heuristic guess.

        Content corrections: applied via nearest-by-time matching. Lines with
        applied corrections get a † marker.

        Args:
            diarized_segments: List of diarization segments
            speaker_corrections: Dict of speaker corrections
            content_corrections: Append-only list of content correction entries (Phase 1)
            remove_fillers: Whether to remove filler words
            include_duration: Whether to include segment duration

        Returns:
            Formatted transcript string
        """
        if not diarized_segments:
            return ""

        corrections = speaker_corrections or {}

        # Phase 0, Step 0.3.3 — resolve speaker corrections by audio time
        corrections_by_index = self._resolve_corrections_by_time(
            diarized_segments, corrections
        )

        # Phase 1, Step 7 — resolve content corrections by audio time
        content_edits_by_index = self._resolve_content_corrections_by_time(
            diarized_segments, content_corrections or []
        )

        formatted_lines = []
        formatted_lines.append("=" * 80)
        formatted_lines.append("CONSULTATION TRANSCRIPT")
        formatted_lines.append(f"Roles: LAWYER / {self.client_role}")
        formatted_lines.append("=" * 80)
        formatted_lines.append("")

        for idx, segment in enumerate(diarized_segments):
            speaker_id = segment.get('speaker_id', 'UNKNOWN')
            start_time = segment.get('start_time_seconds', 0)
            end_time = segment.get('end_time_seconds', 0)
            transcript = segment.get('transcript', '')

            # Apply speaker precedence: time-anchored correction > diarization mapping
            if idx in corrections_by_index:
                role = corrections_by_index[idx]
            else:
                role = self.get_speaker_role(speaker_id)

            # Apply content correction if present
            content_edit = content_edits_by_index.get(idx)
            if content_edit:
                if content_edit["kind"] == "scratch":
                    # Skip this line entirely (hidden by scratch)
                    continue
                elif content_edit["kind"] == "replace" and content_edit.get("replacement_text"):
                    transcript = content_edit["replacement_text"]

            cleaned_text = self.clean_transcript_text(transcript, aggressive_cleaning=remove_fillers)
            timestamp = self.format_timestamp(start_time)

            # † marker for lines that had a live content correction applied
            marker = " †" if content_edit else ""

            if include_duration:
                duration = end_time - start_time
                line = f"{timestamp} {role} ({duration:.1f}s): {cleaned_text}{marker}"
            else:
                line = f"{timestamp} {role}: {cleaned_text}{marker}"

            formatted_lines.append(line)

        formatted_lines.append("")
        formatted_lines.append("=" * 80)
        formatted_lines.append("END OF TRANSCRIPT")
        formatted_lines.append("=" * 80)

        return "\n".join(formatted_lines)

    def format_legal_transcript_json(
        self,
        diarized_segments: List[Dict[str, Any]],
        metadata: Dict[str, Any] = None,
        speaker_corrections: Optional[Dict[str, Any]] = None,
        content_corrections: Optional[List[Dict[str, Any]]] = None,
        remove_fillers: bool = False
    ) -> Dict[str, Any]:
        """
        Format diarized segments into structured JSON format.

        Args:
            diarized_segments: List of diarization segments
            metadata: Optional metadata to include
            speaker_corrections: Dict of speaker corrections
            content_corrections: Append-only list of content correction entries (Phase 1)
            remove_fillers: Whether to remove filler words

        Returns:
            Dictionary with formatted transcript data
        """
        corrections = speaker_corrections or {}

        # Phase 0, Step 0.3.3 — resolve speaker corrections by audio time
        corrections_by_index = self._resolve_corrections_by_time(
            diarized_segments, corrections
        )

        # Phase 1, Step 7 — resolve content corrections by audio time
        content_edits_by_index = self._resolve_content_corrections_by_time(
            diarized_segments, content_corrections or []
        )

        formatted_segments = []

        for i, segment in enumerate(diarized_segments, 1):
            idx = i - 1  # 0-based index for corrections_by_index lookup
            segment_id = segment.get('segment_id', f"seg_{i}")
            speaker_id = segment.get('speaker_id', 'UNKNOWN')
            start_time = segment.get('start_time_seconds', 0)
            end_time = segment.get('end_time_seconds', 0)
            transcript = segment.get('transcript', '')

            # Apply speaker precedence
            if idx in corrections_by_index:
                role = corrections_by_index[idx]
                speaker_was_corrected = True
            else:
                role = self.get_speaker_role(speaker_id)
                speaker_was_corrected = False

            # Apply content correction
            content_edit = content_edits_by_index.get(idx)
            content_was_corrected = False
            hidden = False

            if content_edit:
                if content_edit["kind"] == "scratch":
                    hidden = True
                    content_was_corrected = True
                elif content_edit["kind"] == "replace" and content_edit.get("replacement_text"):
                    transcript = content_edit["replacement_text"]
                    content_was_corrected = True

            cleaned_text = self.clean_transcript_text(transcript, aggressive_cleaning=remove_fillers)

            formatted_segments.append({
                "sequence_number": i,
                "segment_id": segment_id,
                "timestamp": self.format_timestamp(start_time),
                "timestamp_seconds": start_time,
                "speaker_id": speaker_id,
                "speaker_role": role,
                "duration_seconds": end_time - start_time,
                "statement": cleaned_text,
                "original_transcript": segment.get('transcript', ''),
                "was_corrected": speaker_was_corrected or content_was_corrected,
                "content_corrected": content_was_corrected,
                "hidden": hidden,
            })

        # Filter hidden segments from the visible output but keep them in data
        visible_segments = [s for s in formatted_segments if not s.get("hidden")]

        result = {
            "transcript_type": "lawyer_client_consultation",
            "client_role": self.client_role,
            "metadata": metadata or {},
            "segments": visible_segments,
            "hidden_segments": [s for s in formatted_segments if s.get("hidden")],
            "total_segments": len(formatted_segments),
            "visible_segments": len(visible_segments),
            "speakers": list(set(seg["speaker_role"] for seg in visible_segments)),
            "speaker_corrections_applied": len(corrections_by_index),
            "content_corrections_applied": len(content_edits_by_index),
        }

        return result

    # ------------------------------------------------------------------
    # Petition prose formatting (lawyer-only, no timestamps / no speakers)
    #
    # Produces a single continuous body of text from the live session
    # segments. This path does NOT depend on diarization — it works from
    # the segments captured during the live VAD stream. Content
    # corrections (scratch / replace) are still applied by matching each
    # correction's audio-time anchor to the nearest segment.
    # ------------------------------------------------------------------
    def format_petition_prose(
        self,
        segments: List[Dict[str, Any]],
        content_corrections: Optional[List[Dict[str, Any]]] = None,
        remove_fillers: bool = False,
    ) -> str:
        """
        Format live session segments into continuous petition prose.

        Args:
            segments: List of live segments, each with at least
                      'transcript' and 'start_time_seconds'.
            content_corrections: Append-only list of content correction entries.
            remove_fillers: Whether to remove filler words.

        Returns:
            A single continuous prose string (no timestamps, no speaker labels).
        """
        if not segments:
            return ""

        # Resolve content corrections (scratch/replace) by audio time anchor,
        # reusing the same matching logic used for diarized output.
        content_edits_by_index = self._resolve_content_corrections_by_time(
            segments, content_corrections or []
        )

        pieces: List[str] = []

        for idx, segment in enumerate(segments):
            transcript = segment.get("transcript", "")

            content_edit = content_edits_by_index.get(idx)
            if content_edit:
                if content_edit["kind"] == "scratch":
                    # Scratched content is dropped from the petition entirely.
                    continue
                elif content_edit["kind"] == "replace" and content_edit.get("replacement_text"):
                    transcript = content_edit["replacement_text"]

            cleaned = self.clean_transcript_text(
                transcript, aggressive_cleaning=remove_fillers
            )
            if cleaned:
                pieces.append(cleaned)

        # Join into a single flowing paragraph of prose.
        prose = " ".join(pieces)
        prose = re.sub(r"\s+", " ", prose).strip()
        return prose

    def update_role_mapping(self, speaker_id: str, role: str):
        """Update the role mapping for a specific speaker."""
        self.role_mapping[speaker_id.upper().strip()] = role.upper().strip()

    def get_role_mapping(self) -> Dict[str, str]:
        """Get current role mapping."""
        return self.role_mapping.copy()
