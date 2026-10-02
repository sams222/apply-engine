
"""Blank Careers shell should not count as ready."""

def test_entry_notes_document_blank_shell_strategy():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "apply_engine" / "fill.py"
    text = src.read_text(encoding="utf-8")
    assert "blank Careers shell" in text or "blank shell" in text
    assert "_click_header_sign_in" in text
    assert "goto job posting" in text
