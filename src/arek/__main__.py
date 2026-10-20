"""``python -m arek`` is the ``arek`` command line (for environments where
the console script is not on PATH)."""
import sys

from .cli import main

sys.exit(main())
