import subprocess
import sys


def test_module_help():
    proc = subprocess.run(
        [sys.executable, "-m", "apply_engine", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    out = proc.stdout
    assert "tailor" in out
    assert "fill" in out
    assert "confirm" in out
    assert "status" in out


def test_help_mentions_hard_stop():
    proc = subprocess.run(
        [sys.executable, "-m", "apply_engine", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "hard-stop" in proc.stdout.lower() or "submit" in proc.stdout.lower()
