"""
Unit tests for command_parser.classify_segment — the "new paragraph" command.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.realtime.command_parser import classify_segment


def test_new_paragraph_phrases():
    """All four trigger phrases classify as a paragraph break."""
    for phrase in ("new paragraph", "new para", "next paragraph", "new line"):
        assert classify_segment(phrase) == {"kind": "paragraph_break"}, phrase
    print("✅ test_new_paragraph_phrases PASSED")


def test_case_insensitive():
    """Phrases match regardless of case."""
    assert classify_segment("New Paragraph") == {"kind": "paragraph_break"}
    assert classify_segment("NEW PARAGRAPH") == {"kind": "paragraph_break"}
    assert classify_segment("Next Paragraph") == {"kind": "paragraph_break"}
    assert classify_segment("New Line") == {"kind": "paragraph_break"}
    print("✅ test_case_insensitive PASSED")


def test_surrounding_whitespace_and_period():
    """Leading/trailing whitespace and a trailing period are tolerated."""
    assert classify_segment("  new paragraph  ") == {"kind": "paragraph_break"}
    assert classify_segment("new paragraph.") == {"kind": "paragraph_break"}
    assert classify_segment("  new line.  ") == {"kind": "paragraph_break"}
    assert classify_segment("new  paragraph") == {"kind": "paragraph_break"}  # collapsed whitespace
    print("✅ test_surrounding_whitespace_and_period PASSED")


def test_mid_segment_not_a_command():
    """Trigger words appearing mid-segment must NOT be classified as commands."""
    assert classify_segment("please new paragraph") is None
    assert classify_segment("start a new paragraph here") is None
    assert classify_segment("go to the next paragraph of the brief") is None
    assert classify_segment("draw a new line on the diagram") is None
    print("✅ test_mid_segment_not_a_command PASSED")


def test_normal_content():
    """Normal dictation content returns None."""
    assert classify_segment("Good afternoon, I have reviewed the documents.") is None
    assert classify_segment("Under the law, wrongful termination claims require evidence.") is None
    assert classify_segment("") is None
    assert classify_segment("   ") is None
    print("✅ test_normal_content PASSED")


def test_scratch_replace_no_longer_commands():
    """The removed scratch/replace phrases are now plain content, not commands."""
    assert classify_segment("scratch that") is None
    assert classify_segment("change that to the defendant was present") is None
    print("✅ test_scratch_replace_no_longer_commands PASSED")


def test_non_english_short_circuit():
    """Non-English segments are never classified as commands."""
    assert classify_segment("new paragraph", language="te-IN") is None
    assert classify_segment("new line", language="hi-IN") is None
    assert classify_segment("new paragraph", language="mr-IN") is None
    print("✅ test_non_english_short_circuit PASSED")


def test_english_variants_allowed():
    """English language codes do trigger classification."""
    assert classify_segment("new paragraph", language="en-IN") == {"kind": "paragraph_break"}
    assert classify_segment("new paragraph", language="en") == {"kind": "paragraph_break"}
    assert classify_segment("new paragraph", language="en-US") == {"kind": "paragraph_break"}
    assert classify_segment("new paragraph", language="unknown") == {"kind": "paragraph_break"}
    assert classify_segment("new paragraph", language=None) == {"kind": "paragraph_break"}
    print("✅ test_english_variants_allowed PASSED")


if __name__ == "__main__":
    test_new_paragraph_phrases()
    test_case_insensitive()
    test_surrounding_whitespace_and_period()
    test_mid_segment_not_a_command()
    test_normal_content()
    test_scratch_replace_no_longer_commands()
    test_non_english_short_circuit()
    test_english_variants_allowed()
    print("\n🎉 All command_parser tests passed!")
