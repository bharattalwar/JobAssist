"""Entry point so the tool runs as `python -m jobassist ...`."""

import sys

from jobassist.cli import main

if __name__ == "__main__":
    sys.exit(main())
