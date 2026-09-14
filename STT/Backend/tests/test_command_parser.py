"""
Phase 1 Step 2 — Unit tests for command_parser.classify_segment
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.realtime.command_parser import classify_segment


def test_scratch_that_basic():
    assert classify_segment("scratch that") == {"kind": "scratch"}
    assert classify_segment("Scratch that") == {"kind": "scratch"}
    assert classify_segment("SCRATCH THAT") == {"kind": "scratch"}
    assert classify_segment("scratch that.") == {"kind": "scratch"}
    assert classify_segment("  scratch that  ") == {"kind": "scratch"}
    print("✅ test_scratch_that_basic PASSED")


def test_change_that_to_basic():
    result = classify_segment("change that to the defendant was present at 4 PM")
    assert result == {"kind": "replace", "replacement": "the defendant was present at 4 PM"}

    result = classify_segment("Change that to the contract was signed.")
    assert result == {"kind": "replace", "replacement": "the contract was signed"}

    result = classify_segment("CHANGE THAT TO hello world")
    assert result == {"kind": "replace", "replacement": "hello world"}

    print("✅ test_change_that_to_basic PASSED")


def test_not_a_command_mid_segment():
    """Trigger words appearing mid-segment must NOT be classified as commands."""
    assert classify_segment("let me scratch that from the record") is None
    assert classify_segment("I want to change that to something else maybe") is None
    assert classify_segment("the change that to make is minor") is None
    assert classify_segment("please scratch that idea from your mind") is None
    print("✅ test_not_a_command_mid_segment PASSED")


def test_normal_content():
    """Normal dictation content returns None."""
    assert classify_segment("Good afternoon, I have reviewed the documents.") is None
    assert classify_segment("Under the law, wrongful termination claims require evidence.") is None
    assert classify_segment("What happened was they fired me without notice.") is None
    assert classify_segment("") is None
    assert classify_segment("   ") is None
    print("✅ test_normal_content PASSED")


def test_non_english_short_circuit():
    """Non-English segments are never classified as commands (Risk C)."""
    # Even if the text matches the English pattern, non-English language → None
    assert classify_segment("scratch that", language="te-IN") is None
    assert classify_segment("change that to hello", language="hi-IN") is None
    assert classify_segment("scratch that", language="mr-IN") is None
    print("✅ test_non_english_short_circuit PASSED")


def test_english_variants_allowed():
    """English language codes do trigger classification."""
    assert classify_segment("scratch that", language="en-IN") == {"kind": "scratch"}
    assert classify_segment("scratch that", language="en") == {"kind": "scratch"}
    assert classify_segment("scratch that", language="en-US") == {"kind": "scratch"}
    assert classify_segment("scratch that", language="unknown") == {"kind": "scratch"}
    # None language (undetected) should also allow classification
    assert classify_segment("scratch that", language=None) == {"kind": "scratch"}
    print("✅ test_english_variants_allowed PASSED")


def test_out_of_scope_commands():
    """v2/v3 commands are NOT recognized in v1."""
    # Positional addressing
    assert classify_segment("correction, paragraph 3 line 2") is None
    # Multi-segment scratch
    assert classify_segment("scratch the last two") is None
    # Phrase-based lookback
    assert classify_segment("change wrongful termination to unfair dismissal") is None
    print("✅ test_out_of_scope_commands PASSED")


def test_change_that_to_empty_replacement():
    """'change that to' with no actual replacement text should NOT match."""
    assert classify_segment("change that to") is None
    assert classify_segment("change that to .") is None
    assert classify_segment("change that to   ") is None
    print("✅ test_change_that_to_empty_replacement PASSED")


if __name__ == "__main__":
    test_scratch_that_basic()
    test_change_that_to_basic()
    test_not_a_command_mid_segment()
    test_normal_content()
    test_non_english_short_circuit()
    test_english_variants_allowed()
    test_out_of_scope_commands()
    test_change_that_to_empty_replacement()
    print("\n🎉 All command_parser tests passed!")
