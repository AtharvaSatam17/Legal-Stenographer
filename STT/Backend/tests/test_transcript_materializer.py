"""
Phase 1, Step 4 — Unit tests for transcript_materializer.materialize()
"""

import sys
import os
import logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.realtime.transcript_materializer import materialize

# Capture warnings
logging.basicConfig(level=logging.WARNING)


def make_segments():
    return [
        {"segment_id": "seg_A", "transcript": "Segment A text."},
        {"segment_id": "seg_B", "transcript": "Segment B text."},
        {"segment_id": "seg_C", "transcript": "Segment C text."},
    ]


def test_no_corrections():
    """With no corrections, all segments are visible and text is concatenated."""
    segments = make_segments()
    text, msgs = materialize(segments, [])
    assert text == "Segment A text. Segment B text. Segment C text."
    assert all(not m["hidden"] for m in msgs)
    print("✅ test_no_corrections PASSED")


def test_scratch_hides_segment():
    """A scratch correction hides the target segment."""
    segments = make_segments()
    corrections = [
        {"correction_id": "corr_00001", "kind": "scratch", "target_segment_id": "seg_B",
         "replacement_text": None, "reverses_correction_id": None},
    ]
    text, msgs = materialize(segments, corrections)
    assert "Segment B text." not in text
    assert text == "Segment A text. Segment C text."
    assert msgs[1]["hidden"] is True
    assert msgs[0]["hidden"] is False
    assert msgs[2]["hidden"] is False
    print("✅ test_scratch_hides_segment PASSED")


def test_replace_changes_text():
    """A replace correction changes the effective text of the target."""
    segments = make_segments()
    corrections = [
        {"correction_id": "corr_00001", "kind": "replace", "target_segment_id": "seg_C",
         "replacement_text": "Replaced C.", "reverses_correction_id": None},
    ]
    text, msgs = materialize(segments, corrections)
    assert "Segment C text." not in text
    assert "Replaced C." in text
    assert msgs[2]["effective_text"] == "Replaced C."
    print("✅ test_replace_changes_text PASSED")


def test_reverse_undoes_scratch():
    """A reverse entry undoes a prior scratch — segment becomes visible again."""
    segments = make_segments()
    corrections = [
        {"correction_id": "corr_00001", "kind": "scratch", "target_segment_id": "seg_B",
         "replacement_text": None, "reverses_correction_id": None},
        {"correction_id": "corr_00002", "kind": "reverse", "target_segment_id": "seg_B",
         "replacement_text": None, "reverses_correction_id": "corr_00001"},
    ]
    text, msgs = materialize(segments, corrections)
    assert "Segment B text." in text
    assert msgs[1]["hidden"] is False
    print("✅ test_reverse_undoes_scratch PASSED")


def test_reverse_undoes_replace():
    """A reverse entry undoes a prior replace — original text returns."""
    segments = make_segments()
    corrections = [
        {"correction_id": "corr_00001", "kind": "replace", "target_segment_id": "seg_A",
         "replacement_text": "New A.", "reverses_correction_id": None},
        {"correction_id": "corr_00002", "kind": "reverse", "target_segment_id": "seg_A",
         "replacement_text": None, "reverses_correction_id": "corr_00001"},
    ]
    text, msgs = materialize(segments, corrections)
    assert "Segment A text." in text
    assert "New A." not in text
    assert msgs[0]["effective_text"] == "Segment A text."
    print("✅ test_reverse_undoes_replace PASSED")


def test_replace_on_hidden_segment_logged_not_applied(capfd=None):
    """Replace targeting a scratched segment: logged as warning, not applied."""
    segments = make_segments()
    corrections = [
        {"correction_id": "corr_00001", "kind": "scratch", "target_segment_id": "seg_B",
         "replacement_text": None, "reverses_correction_id": None},
        {"correction_id": "corr_00002", "kind": "replace", "target_segment_id": "seg_B",
         "replacement_text": "Should not appear.", "reverses_correction_id": None},
    ]

    # Capture log output
    with LogCapture() as log:
        text, msgs = materialize(segments, corrections)

    # Segment B should still be hidden (scratch wins)
    assert msgs[1]["hidden"] is True
    assert "Should not appear." not in text
    # The warning should have been logged
    assert any("replace" in r.lower() and "hidden" in r.lower() for r in log.records)

    print("✅ test_replace_on_hidden_segment_logged_not_applied PASSED")


def test_scratch_on_already_hidden_logged():
    """Double-scratch on same segment: logged, no crash."""
    segments = make_segments()
    corrections = [
        {"correction_id": "corr_00001", "kind": "scratch", "target_segment_id": "seg_A",
         "replacement_text": None, "reverses_correction_id": None},
        {"correction_id": "corr_00002", "kind": "scratch", "target_segment_id": "seg_A",
         "replacement_text": None, "reverses_correction_id": None},
    ]

    with LogCapture() as log:
        text, msgs = materialize(segments, corrections)

    assert msgs[0]["hidden"] is True
    assert any("already-hidden" in r.lower() for r in log.records)
    print("✅ test_scratch_on_already_hidden_logged PASSED")


def test_rejected_entries_ignored():
    """Rejected corrections don't affect the transcript."""
    segments = make_segments()
    corrections = [
        {"correction_id": "corr_00001", "kind": "rejected", "target_segment_id": "seg_B",
         "replacement_text": None, "reverses_correction_id": None,
         "confirmed_by": "rejected_by:staff"},
    ]
    text, msgs = materialize(segments, corrections)
    assert "Segment B text." in text
    assert msgs[1]["hidden"] is False
    print("✅ test_rejected_entries_ignored PASSED")


def test_empty_segments():
    """Empty segment list produces empty output."""
    text, msgs = materialize([], [])
    assert text == ""
    assert msgs == []
    print("✅ test_empty_segments PASSED")


# -- Utility --

class LogCapture:
    """Context manager to capture logging output."""
    def __init__(self):
        self.records = []
        self._handler = None

    def __enter__(self):
        self._handler = logging.Handler()
        self._handler.emit = lambda record: self.records.append(record.getMessage())
        logging.getLogger("services.realtime.transcript_materializer").addHandler(self._handler)
        return self

    def __exit__(self, *args):
        logging.getLogger("services.realtime.transcript_materializer").removeHandler(self._handler)


if __name__ == "__main__":
    test_no_corrections()
    test_scratch_hides_segment()
    test_replace_changes_text()
    test_reverse_undoes_scratch()
    test_reverse_undoes_replace()
    test_replace_on_hidden_segment_logged_not_applied()
    test_scratch_on_already_hidden_logged()
    test_rejected_entries_ignored()
    test_empty_segments()
    print("\n🎉 All transcript_materializer tests passed!")
