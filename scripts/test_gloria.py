"""Run the joined Gloria checks with the same file selection on every OS."""
from pathlib import Path
import sys
import pytest


def main():
    root = Path(__file__).resolve().parents[1]
    return pytest.main(["-q", *[str(path) for path in sorted((root / "tests").glob("test_gloria*.py"))],
        str(root / "frontend/tests"), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
