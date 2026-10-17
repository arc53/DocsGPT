"""``python -m docsgpt`` runs what the ``docsgpt`` command runs."""

import sys

from docsgpt.cli import main

if __name__ == "__main__":
    sys.exit(main())
