"""Run the joined transaction dispute workflow checks with the same file selection on every OS."""
from pathlib import Path
import sys
import pytest


def main():
    root = Path(__file__).resolve().parents[1]
    return pytest.main(["-q", *[str(path) for path in sorted((root / "tests").glob("test_dispute*.py"))],
        str(root / "tests/test_native_dispute_qualification.py"),
        str(root / "frontend/tests"), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
