"""Switch the demo's one-word bug on or off, for the GitHub pull-request part of the demo.

    python scripts/demo_break.py on        # rename the "Dates" button to "Date" in demo_bot/agent.py
    python scripts/demo_break.py off       # put it back
    python scripts/demo_break.py status    # is the bug on?

With the bug on, four example scenarios break (tap-dates-button and the three
exactly-three-buttons ones), and so does the project's own test suite, so a pull request that
contains it gets red crosses on GitHub. Never commit this on `main`: use a throwaway branch.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILE = ROOT / "demo_bot" / "agent.py"
GOOD = b'("dates", "Dates")'
BAD = b'("dates", "Date")'


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("action", choices=["on", "off", "status"])
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE, help="file to edit (for tests)")
    args = parser.parse_args()

    data = args.file.read_bytes()  # bytes, so line endings and the rupee sign are left alone
    is_on = BAD in data
    if args.action == "status":
        print(f"the bug is {'ON' if is_on else 'OFF'} in {args.file}")
        return 0
    wanted_on = args.action == "on"
    if wanted_on == is_on:
        print(f"the bug was already {'ON' if is_on else 'OFF'}; nothing changed")
        return 0
    old, new = (GOOD, BAD) if wanted_on else (BAD, GOOD)
    if old not in data:
        print(f"could not find {old.decode()} in {args.file}", file=sys.stderr)
        return 1
    args.file.write_bytes(data.replace(old, new))
    print(f"the bug is now {'ON' if wanted_on else 'OFF'} in {args.file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
